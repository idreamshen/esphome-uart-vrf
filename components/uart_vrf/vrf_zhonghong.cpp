#include <bitset>

#include "esphome.h"
#include "esphome/core/log.h"
#include "esphome/core/hal.h"
#include "uart_vrf_timing.h"
#include "vrf_zhonghong.h"

namespace vrf_protocol {

    static const char *const TAG = "vrf_protocol.zhonghong";
    static constexpr uint8_t MAX_CLIMATES_PER_RESPONSE = 64;
    static constexpr uint32_t FRAME_GAP_TIMEOUT_MS = 100;

    static size_t frame_length_at(
        const std::vector<uint8_t>& data,
        size_t offset,
        uint8_t slave_addr
    ) {
        if (data.size() - offset < 6 || data[offset] != slave_addr) {
            return 0;
        }

        uint8_t func = data[offset + 1];
        bool is_control =
            func >= uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_SWITCH) &&
            func <= uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_FAN_MODE);
        if (is_control) {
            return 6;
        }
        if (func != uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_QUERY)) {
            return 0;
        }

        uint8_t func_value = data[offset + 2];
        uint8_t num = data[offset + 3];
        if (num > MAX_CLIMATES_PER_RESPONSE) {
            return 0;
        }

        size_t record_length = 0;
        if (
            func_value == uint8_t(
                VrfZhonghongFuncValue::ZHONG_HONG_FUNC_VALUE_ONLINE
            )
        ) {
            record_length = 3;
        } else if (
            func_value == uint8_t(
                VrfZhonghongFuncValue::ZHONG_HONG_FUNC_VALUE_SINGLE
            )
        ) {
            if (num > 1) {
                return 0;
            }
            record_length = 10;
        } else if (
            func_value == uint8_t(
                VrfZhonghongFuncValue::ZHONG_HONG_FUNC_VALUE_MULTI
            ) ||
            func_value == uint8_t(
                VrfZhonghongFuncValue::ZHONG_HONG_FUNC_VALUE_ALL
            )
        ) {
            record_length = 10;
        } else {
            return 0;
        }

        return 4 + size_t(num) * record_length + 1;
    }

    void VrfZhonghongGateway::consume_data_handle_found_climates() {
        uint8_t num = this->data_[3]; // 空调数量
        for (uint8_t i = 0; i < num; i++)
        {
            uint8_t outdoor_addr = this->data_[4 + i * 3];
            uint8_t indoor_addr = this->data_[4 + i * 3 + 1];
            uint8_t online = this->data_[4 + i * 3 + 2];

            if (online == 1) {
                this->find_or_create_climate(outdoor_addr, indoor_addr);
            }
        }
    }

    void VrfZhonghongGateway::consume_data_handle_query_climate() {
        uint8_t num = this->data_[3]; // 空调数量
        for (uint8_t i = 0; i < num; i++)
        {
            uint8_t outdoor_addr = this->data_[4 + i * 10];
            uint8_t indoor_addr = this->data_[4 + i * 10 + 1];
            uint8_t on_off = this->data_[4 + i * 10 + 2];
            uint8_t target_temperature = this->data_[4 + i * 10 + 3];
            uint8_t mode = this->data_[4 + i * 10 + 4];
            uint8_t fan_mode = this->data_[4 + i * 10 + 5];
            uint8_t current_temperature = this->data_[4 + i * 10 + 6];

            VrfZhonghongClimate* target_climate = this->find_or_create_climate(outdoor_addr, indoor_addr);

            if (VrfZhonghongClimateSwitch(on_off) == VrfZhonghongClimateSwitch::ZHONG_HONG_CLIMATE_SWITCH_OFF) {
                target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_OFF);
            } else {
                switch (VrfZhonghongClimateMode(mode))
                {
                case VrfZhonghongClimateMode::ZHONG_HONG_CLIMATE_MODE_COOL:
                    target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_COOL);
                    break;
                case VrfZhonghongClimateMode::ZHONG_HONG_CLIMATE_MODE_HEAT:
                    target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_HEAT);
                    break;
                case VrfZhonghongClimateMode::ZHONG_HONG_CLIMATE_MODE_FAN:
                    target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_FAN_ONLY);
                    break;
                case VrfZhonghongClimateMode::ZHONG_HONG_CLIMATE_MODE_DRY:
                    target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_DRY);
                    break;
                default:
                    break;
                }
            }

            switch (VrfZhonghongClimateFanSpeed(fan_mode))
            {
            case VrfZhonghongClimateFanSpeed::ZHONG_HONG_CLIMATE_FAN_SPEED_HIGH:
                target_climate->set_fan_mode(VrfClimateFanMode::CLIMATE_FAN_MODE_HIGH);
                break;
            case VrfZhonghongClimateFanSpeed::ZHONG_HONG_CLIMATE_FAN_SPEED_MEDIUM:
                target_climate->set_fan_mode(VrfClimateFanMode::CLIMATE_FAN_MODE_MEDIUM);
                break;
            case VrfZhonghongClimateFanSpeed::ZHONG_HONG_CLIMATE_FAN_SPEED_LOW:
                target_climate->set_fan_mode(VrfClimateFanMode::CLIMATE_FAN_MODE_LOW);
                break;
            default:
                break;
            }

            if (current_temperature != 0) {
                target_climate->set_current_temperature(current_temperature);
            } else {
                ESP_LOGW(TAG, "consume data of current_temperature is zero");
            }
            target_climate->set_target_temperature(target_temperature);
            target_climate->fire_data_updated();
        }
    }


    void VrfZhonghongGateway::consume_data(uint8_t data) {
        this->last_data_time_ = esphome::millis();
        this->data_.push_back(data);

        while (this->data_.size() >= 6) {

            size_t length = frame_length_at(this->data_, 0, this->slave_addr_);
            if (length == 0) {
                this->data_.erase(this->data_.begin());
                continue;
            }

            if (this->data_.size() < length) {
                bool resynchronized = false;
                for (size_t offset = 1; offset + 6 <= this->data_.size(); offset++) {
                    size_t candidate_length = frame_length_at(
                        this->data_, offset, this->slave_addr_
                    );
                    if (
                        candidate_length == 0 ||
                        this->data_.size() - offset < candidate_length
                    ) {
                        continue;
                    }
                    uint8_t candidate_sum = checksum(
                        std::vector<uint8_t>(
                            this->data_.begin() + offset,
                            this->data_.begin() + offset + candidate_length - 1
                        )
                    );
                    if (candidate_sum != this->data_[offset + candidate_length - 1]) {
                        continue;
                    }
                    this->data_.erase(
                        this->data_.begin(),
                        this->data_.begin() + offset
                    );
                    resynchronized = true;
                    break;
                }
                if (resynchronized) {
                    continue;
                }
                break;
            }

            uint8_t func = this->data_[1];

            uint8_t sum = checksum(std::vector<uint8_t>(this->data_.begin(), this->data_.begin() + length - 1));

            if (sum != this->data_[length - 1]) {
                // checksum failed
                this->data_.erase(this->data_.begin(), this->data_.begin() + 1);
                continue;
            }

            if (func == uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_QUERY)) {
                uint8_t func_value = this->data_[2];
                uint8_t num = this->data_[3]; // 空调数量

                if (func_value == uint8_t(VrfZhonghongFuncValue::ZHONG_HONG_FUNC_VALUE_ONLINE)) {
                    this->consume_data_handle_found_climates();
                } else {
                    this->consume_data_handle_query_climate();
                }
            }

            ESP_LOGD(TAG, "consume succ, data=%s", esphome::format_hex_pretty(this->data_.data(), length).c_str());
            this->data_.erase(this->data_.begin(), this->data_.begin() + length);
        }
    }

    void VrfZhonghongGateway::on_uart_idle(uint32_t now) {
        if (!this->data_.empty() && now - this->last_data_time_ >= FRAME_GAP_TIMEOUT_MS) {
            ESP_LOGW(TAG, "Discarding incomplete frame after UART gap");
            this->data_.clear();
        }
    }

    VrfCmd VrfZhonghongGateway::cmd_find_climates() {
        std::vector<uint8_t> cmd = {
            this->slave_addr_,
            uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_QUERY),
            0x02,
            0xFF,
            0xFF,
            0xFF};
        uint8_t sum = checksum(cmd);
        cmd.push_back(sum);
        return VrfCmd(cmd);
    }

    VrfZhonghongClimate* VrfZhonghongGateway::find_or_create_climate(uint8_t outdoor_addr, uint8_t indoor_addr) {
        VrfZhonghongClimate* target_climate = nullptr;
        for(auto &climate : this->climates_) {
            VrfZhonghongClimate* climate_cast = reinterpret_cast<VrfZhonghongClimate*>(climate);
            if (climate_cast->get_outdoor_addr() == outdoor_addr
                && climate_cast->get_indoor_addr() == indoor_addr) {
                target_climate = climate_cast;
                break;
            }
        }

        if (target_climate == nullptr) {
            target_climate = new VrfZhonghongClimate(this->slave_addr_, outdoor_addr, indoor_addr);
            this->climates_.push_back(target_climate);

            for(auto &callback : this->climate_create_callbacks_) {
                callback(target_climate);
            }
        }

        return target_climate;
    }

    VrfCmd VrfZhonghongClimate::cmd_query() {
        unsigned long now = esphome::millis();
        if (now - last_time_ctrl < esphome::uart_vrf::timing::ZHONGHONG_POST_CONTROL_DELAY_MS) {
            // Skip queries until the post-control delay has elapsed.
            return VrfCmd();
        }

        std::vector<uint8_t> cmd = {
            this->slave_addr_,
            uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_QUERY),
            0x01,
            0x01,
            this->outdoor_addr_,
            this->indoor_addr_};
        uint8_t sum = checksum(cmd);
        cmd.push_back(sum);
        return VrfCmd(cmd);
    }

    VrfCmd VrfZhonghongClimate::cmd_control_mode(VrfClimateMode mode) {
        this->need_fire_data_updated = true;

        std::vector<uint8_t> cmd_on_off = {
            this->slave_addr_,
            0, // 功能码
            0, // 控制值
            0x01, // 空调数量
            this->outdoor_addr_,
            this->indoor_addr_,
        };

        std::vector<uint8_t> cmd_mode = {
            this->slave_addr_,
            0, // 功能码
            0, // 控制值
            0x01, // 空调数量
            this->outdoor_addr_,
            this->indoor_addr_,
        };

        switch (mode)
        {
        case VrfClimateMode::CLIMATE_MODE_OFF:
            cmd_on_off[1] = uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_SWITCH);
            cmd_on_off[2] = uint8_t(VrfZhonghongClimateSwitch::ZHONG_HONG_CLIMATE_SWITCH_OFF);

            cmd_mode = {};
            break;
        case VrfClimateMode::CLIMATE_MODE_COOL:
            cmd_on_off[1] = uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_SWITCH);
            cmd_on_off[2] = uint8_t(VrfZhonghongClimateSwitch::ZHONG_HONG_CLIMATE_SWITCH_ON);

            cmd_mode[1] = uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_MODE);
            cmd_mode[2] = uint8_t(VrfZhonghongClimateMode::ZHONG_HONG_CLIMATE_MODE_COOL);
            break;
        case VrfClimateMode::CLIMATE_MODE_HEAT:
            cmd_on_off[1] = uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_SWITCH);
            cmd_on_off[2] = uint8_t(VrfZhonghongClimateSwitch::ZHONG_HONG_CLIMATE_SWITCH_ON);

            cmd_mode[1] = uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_MODE);
            cmd_mode[2] = uint8_t(VrfZhonghongClimateMode::ZHONG_HONG_CLIMATE_MODE_HEAT);
            break;
        case VrfClimateMode::CLIMATE_MODE_FAN_ONLY:
            cmd_on_off[1] = uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_SWITCH);
            cmd_on_off[2] = uint8_t(VrfZhonghongClimateSwitch::ZHONG_HONG_CLIMATE_SWITCH_ON);

            cmd_mode[1] = uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_MODE);
            cmd_mode[2] = uint8_t(VrfZhonghongClimateMode::ZHONG_HONG_CLIMATE_MODE_FAN);
            break;
        case VrfClimateMode::CLIMATE_MODE_DRY:
            cmd_on_off[1] = uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_SWITCH);
            cmd_on_off[2] = uint8_t(VrfZhonghongClimateSwitch::ZHONG_HONG_CLIMATE_SWITCH_ON);

            cmd_mode[1] = uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_MODE);
            cmd_mode[2] = uint8_t(VrfZhonghongClimateMode::ZHONG_HONG_CLIMATE_MODE_DRY);
            break;
        default:
            break;
        }

        uint8_t sum_cmd_on_off = checksum(cmd_on_off);
        cmd_on_off.push_back(sum_cmd_on_off);

        uint8_t sum_cmd_mode = checksum(cmd_mode);
        cmd_mode.push_back(sum_cmd_mode);

        VrfCmd cmd;

        std::vector<std::vector<uint8_t>> cmds = {};
        if (mode == VrfClimateMode::CLIMATE_MODE_OFF) {
            cmd = VrfCmd(cmd_on_off);
        } else {
            cmd = VrfCmd({cmd_mode, cmd_on_off});
        }

        last_time_ctrl = esphome::millis();

        return cmd;
    }

    VrfCmd VrfZhonghongClimate::cmd_control_target_temperature(uint8_t target_temperature) {
        this->need_fire_data_updated = true;

        uint8_t temperature = target_temperature;
        if (temperature < 16) {
            temperature = 16;
        }
        if (temperature > 30) {
            temperature = 30;
        }

        std::vector<uint8_t> cmd = {
            this->slave_addr_,
            uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_TEMPERATURE), // 功能码
            temperature, // 控制值
            0x01, // 空调数量
            this->outdoor_addr_,
            this->indoor_addr_,
        };

        uint8_t sum = checksum(cmd);
        cmd.push_back(sum);

        last_time_ctrl = esphome::millis();

        return VrfCmd(cmd);
    }

    VrfCmd VrfZhonghongClimate::cmd_control_fan_mode(VrfClimateFanMode mode) {
        this->need_fire_data_updated = true;

        std::vector<uint8_t> cmd = {
            this->slave_addr_,
            uint8_t(VrfZhonghongFunc::ZHONG_HONG_FUNC_CTRL_FAN_MODE), // 功能码
            0, // 控制值
            0x01, // 空调数量
            this->outdoor_addr_,
            this->indoor_addr_,
        };

        switch (mode)
        {
        case VrfClimateFanMode::CLIMATE_FAN_MODE_AUTO:
            cmd[2] = uint8_t(VrfZhonghongClimateFanSpeed::ZHONG_HONG_CLIMATE_FAN_SPEED_LOW); // 强制低速
            break;
        case VrfClimateFanMode::CLIMATE_FAN_MODE_HIGH:
            cmd[2] = uint8_t(VrfZhonghongClimateFanSpeed::ZHONG_HONG_CLIMATE_FAN_SPEED_HIGH);
            break;
        case VrfClimateFanMode::CLIMATE_FAN_MODE_MEDIUM:
            cmd[2] = uint8_t(VrfZhonghongClimateFanSpeed::ZHONG_HONG_CLIMATE_FAN_SPEED_MEDIUM);
            break;
        case VrfClimateFanMode::CLIMATE_FAN_MODE_LOW:
            cmd[2] = uint8_t(VrfZhonghongClimateFanSpeed::ZHONG_HONG_CLIMATE_FAN_SPEED_LOW);
            break;
        default:
            break;
        }
        uint8_t sum = checksum(cmd);
        cmd.push_back(sum);

        last_time_ctrl = esphome::millis();

        return VrfCmd(cmd);
    }
}
