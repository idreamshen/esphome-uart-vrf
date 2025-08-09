#include <bitset>

#include "esphome.h"
#include "vrf_demry.h"

namespace vrf_protocol {

    static const char *const TAG = "vrf_protocol.demry";

    void VrfDemryGateway::consume_data_handle_found_climates() {
        uint8_t tmp[4] = {this->data_[5], this->data_[6], this->data_[7], this->data_[8]};
        for (int i=0; i < 4; i++) {
            std::bitset<8> bits(tmp[i]);
            for (int j=0; j < 8; j++) {
                if (bits.test(j)) {
                    uint8_t id = (3-i) * 8 + j;
                    VrfDemryClimate* target_climate = this->find_or_create_climate(id);
                }
            }
        }
    }

    void VrfDemryGateway::consume_data_handle_query_climate() {
        uint8_t id = this->data_[1];
        uint8_t climate_switch = this->data_[2];
        uint8_t climate_mode = this->data_[3];
        uint8_t climate_target_temperature = this->data_[4];
        uint8_t climate_fan_mode = this->data_[5];
        uint8_t climate_current_temperature = this->data_[6];

        VrfDemryClimate* target_climate = this->find_or_create_climate(id);

        if (climate_switch == false) {
            target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_OFF);
        } else {
            switch (VrfDemryClimateMode(climate_mode))
            {
            case VrfDemryClimateMode::DEMRY_CLIMATE_MODE_COOL:
                target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_COOL);
                break;
            case VrfDemryClimateMode::DEMRY_CLIMATE_MODE_HEAT:
                target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_HEAT);
                break;
            case VrfDemryClimateMode::DEMRY_CLIMATE_MODE_FAN:
                target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_FAN_ONLY);
                break;
            case VrfDemryClimateMode::DEMRY_CLIMATE_MODE_DRY:
                target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_DRY);
                break;
            default:
                break;
            }
        }

        target_climate->set_target_temperature(climate_target_temperature);
        target_climate->set_current_temperature(climate_current_temperature);

        switch (VrfDemryClimateFanSpeed(climate_fan_mode))
        {
        case VrfDemryClimateFanSpeed::DEMRY_CLIMATE_FAN_SPEED_AUTO:
            target_climate->set_fan_mode(VrfClimateFanMode::CLIMATE_FAN_MODE_AUTO);
            break;
        case VrfDemryClimateFanSpeed::DEMRY_CLIMATE_FAN_SPEED_HIGH:
            target_climate->set_fan_mode(VrfClimateFanMode::CLIMATE_FAN_MODE_HIGH);
            break;
        case VrfDemryClimateFanSpeed::DEMRY_CLIMATE_FAN_SPEED_MEDIUM:
            target_climate->set_fan_mode(VrfClimateFanMode::CLIMATE_FAN_MODE_MEDIUM);
            break;
        case VrfDemryClimateFanSpeed::DEMRY_CLIMATE_FAN_SPEED_LOW:
            target_climate->set_fan_mode(VrfClimateFanMode::CLIMATE_FAN_MODE_LOW);
            break;
        default:
            break;
        }
        target_climate->fire_data_updated();
    }

    void VrfDemryGateway::consume_data(uint8_t data) {
        this->data_.push_back(data);

        while (this->data_.size() > 0) {

            if (this->data_.size() < 10) {
                return;
            }

            uint8_t sum = checksum(std::vector<uint8_t>(this->data_.begin(), this->data_.begin() + 9));
            if (sum != this->data_[9]) {
                // checksum failed
                this->data_.erase(this->data_.begin(), this->data_.begin() + 1);
                continue;
            }

            if (this->data_[0] != this->slave_addr_) {
                // not my data
                this->data_.clear();
                return;
            }

            if (this->data_[1] == 0xAA) {
                this->consume_data_handle_found_climates();
            } else {
                this->consume_data_handle_query_climate();
            }

            // erase 10 bytes
            esphome::ESP_LOGD(TAG, "consume succ, data=%s", esphome::format_hex_pretty(this->data_.data(), 10).c_str());
            this->data_.erase(this->data_.begin(), this->data_.begin() + 10);
        }
    }

    VrfCmd VrfDemryGateway::cmd_find_climates() {
        std::vector<uint8_t> cmd = {
            this->slave_addr_, 0xAA, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF,
            0xFF };
        uint8_t sum = checksum(cmd);
        cmd.push_back(sum);
        return VrfCmd(cmd);
    }

    VrfDemryClimate* VrfDemryGateway::find_or_create_climate(uint8_t id) {
        VrfDemryClimate* target_climate = nullptr;
        for(auto &climate : this->climates_) {
            VrfDemryClimate* climate_cast = reinterpret_cast<VrfDemryClimate*>(climate);
            if (climate_cast->get_id() == id) {
                target_climate = climate_cast;
                break;
            }
        }

        if (target_climate == nullptr) {
            target_climate = new VrfDemryClimate(this->slave_addr_, id);
            this->climates_.push_back(target_climate);

            for(auto &callback : this->climate_create_callbacks_) {
                callback(target_climate);
            }
        }

        return target_climate;
    }

    VrfCmd VrfDemryClimate::cmd_query() {
        std::vector<uint8_t> cmd = {
            this->slave_addr_, this->id_, 0xFF, 0xFF,
            0xFF, 0xFF, 0xFF, 0xFF,
            0xFF};
        uint8_t sum = checksum(cmd);
        cmd.push_back(sum);
        return VrfCmd(cmd);
    }

    static VrfDemryClimateSwitch convert_vrf_mode_to_demry_switch(VrfClimateMode mode) {
        if (mode == VrfClimateMode::CLIMATE_MODE_OFF) {
            return VrfDemryClimateSwitch::DEMRY_CLIAMTE_SWITCH_DISABLE;
        }
        return VrfDemryClimateSwitch::DEMRY_CLIAMTE_SWITCH_ENABLE;
    }

    static VrfDemryClimateMode convert_vrf_mode_to_demry_mode(VrfClimateMode mode) {
        if (mode == VrfClimateMode::CLIMATE_MODE_OFF) {
            return VrfDemryClimateMode::DEMRY_CLIMATE_MODE_HOLD;
        } else if (mode == VrfClimateMode::CLIMATE_MODE_COOL) {
            return VrfDemryClimateMode::DEMRY_CLIMATE_MODE_COOL;
        } else if (mode == VrfClimateMode::CLIMATE_MODE_HEAT) {
            return VrfDemryClimateMode::DEMRY_CLIMATE_MODE_HEAT;
        } else if (mode == VrfClimateMode::CLIMATE_MODE_FAN_ONLY) {
            return VrfDemryClimateMode::DEMRY_CLIMATE_MODE_FAN;
        } else if (mode == VrfClimateMode::CLIMATE_MODE_DRY) {
            return VrfDemryClimateMode::DEMRY_CLIMATE_MODE_DRY;
        }

        return VrfDemryClimateMode::DEMRY_CLIMATE_MODE_HOLD;
    }

    static VrfDemryClimateFanSpeed convert_vrf_fan_mode_to_demry_fan_speed(VrfClimateFanMode fan_mode) {
        if (fan_mode == VrfClimateFanMode::CLIMATE_FAN_MODE_AUTO) {
            return VrfDemryClimateFanSpeed::DEMRY_CLIMATE_FAN_SPEED_AUTO;
        } else if (fan_mode == VrfClimateFanMode::CLIMATE_FAN_MODE_HIGH) {
            return VrfDemryClimateFanSpeed::DEMRY_CLIMATE_FAN_SPEED_HIGH;
        } else if (fan_mode == VrfClimateFanMode::CLIMATE_FAN_MODE_MEDIUM) {
            return VrfDemryClimateFanSpeed::DEMRY_CLIMATE_FAN_SPEED_MEDIUM;
        } else if (fan_mode == VrfClimateFanMode::CLIMATE_FAN_MODE_LOW) {
            return VrfDemryClimateFanSpeed::DEMRY_CLIMATE_FAN_SPEED_LOW;
        }

        return VrfDemryClimateFanSpeed::DEMRY_CLIMATE_FAN_SPEED_HOLD;
    }

    VrfCmd VrfDemryClimate::cmd_control_mode(VrfClimateMode mode) {
        this->need_fire_data_updated = true;

        std::vector<uint8_t> cmd = {
            this->slave_addr_,
            this->id_,
            uint8_t(convert_vrf_mode_to_demry_switch(mode)), // 开关
            uint8_t(convert_vrf_mode_to_demry_mode(mode)), // 模式
            this->target_temperature_, // 目标温度
            uint8_t(convert_vrf_fan_mode_to_demry_fan_speed(this->fan_mode_)), // 风速
            0xFF,
            0xFF,
            0xFF};
        uint8_t sum = checksum(cmd);
        cmd.push_back(sum);
        return VrfCmd({cmd});
    }

    VrfCmd VrfDemryClimate::cmd_control_target_temperature(uint8_t target_temperature) {
        this->need_fire_data_updated = true;

        std::vector<uint8_t> cmd = {
            this->slave_addr_,
            this->id_,
            uint8_t(convert_vrf_mode_to_demry_switch(this->mode_)), // 开关
            uint8_t(convert_vrf_mode_to_demry_mode(this->mode_)), // 模式
            target_temperature, // 目标温度
            uint8_t(convert_vrf_fan_mode_to_demry_fan_speed(this->fan_mode_)), // 风速
            0xFF,
            0xFF,
            0xFF};
        uint8_t sum = checksum(cmd);
        cmd.push_back(sum);
        return VrfCmd(cmd);
    }

    VrfCmd VrfDemryClimate::cmd_control_fan_mode(VrfClimateFanMode mode) {
        this->need_fire_data_updated = true;

        std::vector<uint8_t> cmd = {
            this->slave_addr_,
            this->id_,
            uint8_t(convert_vrf_mode_to_demry_switch(this->mode_)), // 开关
            uint8_t(convert_vrf_mode_to_demry_mode(this->mode_)), // 模式
            this->target_temperature_, // 目标温度
            uint8_t(convert_vrf_fan_mode_to_demry_fan_speed(mode)), // 风速
            0xFF,
            0xFF,
            0xFF};
        uint8_t sum = checksum(cmd);
        cmd.push_back(sum);
        return VrfCmd(cmd);
    }
}
