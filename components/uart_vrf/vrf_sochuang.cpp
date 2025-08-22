#include "esphome.h"
#include "esphome/core/log.h"
#include "vrf_sochuang.h"

#define MAX_SOCHUANG_CLIMATE_NUM 32

namespace vrf_protocol {

    static const char *const TAG = "vrf_protocol.sochuang";

    void VrfSochuangGateway::consume_data_handle_found_climates() {
        // Get the number of indoor units from the response
        uint8_t count = this->data_[4]; // 0x04（数量）

        // Create climate entities for each indoor unit
        for (int i = 0; i < count && i < MAX_SOCHUANG_CLIMATE_NUM; i++) {
            this->find_or_create_climate(i + 1); // indoor addresses start from 1
        }
    }

    void VrfSochuangGateway::consume_data_handle_query_climate() {
        uint8_t indoor_addr = this->data_[4]; // 内机地址
        uint8_t climate_switch = this->data_[5]; // 开关机状态
        uint8_t climate_mode = this->data_[6]; // 模式
        uint8_t climate_target_temperature = this->data_[7]; // 温度
        uint8_t climate_fan_mode = this->data_[8]; // 风速
        uint8_t climate_current_temperature = this->data_[9]; // 室温

        VrfSochuangClimate* target_climate = this->find_or_create_climate(indoor_addr);

        if (climate_switch == uint8_t(VrfSochuangClimateSwitch::SOCHUANG_CLIMATE_SWITCH_OFF)) {
            target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_OFF);
        } else {
            switch (VrfSochuangClimateMode(climate_mode)) {
            case VrfSochuangClimateMode::SOCHUANG_CLIMATE_MODE_COOL:
                target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_COOL);
                break;
            case VrfSochuangClimateMode::SOCHUANG_CLIMATE_MODE_HEAT:
                target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_HEAT);
                break;
            case VrfSochuangClimateMode::SOCHUANG_CLIMATE_MODE_FAN:
                target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_FAN_ONLY);
                break;
            case VrfSochuangClimateMode::SOCHUANG_CLIMATE_MODE_DRY:
                target_climate->set_mode(VrfClimateMode::CLIMATE_MODE_DRY);
                break;
            default:
                break;
            }
        }

        target_climate->set_target_temperature(climate_target_temperature);
        target_climate->set_current_temperature(climate_current_temperature);

        switch (VrfSochuangClimateFanSpeed(climate_fan_mode)) {
        case VrfSochuangClimateFanSpeed::SOCHUANG_CLIMATE_FAN_SPEED_AUTO:
            target_climate->set_fan_mode(VrfClimateFanMode::CLIMATE_FAN_MODE_AUTO);
            break;
        case VrfSochuangClimateFanSpeed::SOCHUANG_CLIMATE_FAN_SPEED_HIGH:
            target_climate->set_fan_mode(VrfClimateFanMode::CLIMATE_FAN_MODE_HIGH);
            break;
        case VrfSochuangClimateFanSpeed::SOCHUANG_CLIMATE_FAN_SPEED_MEDIUM:
            target_climate->set_fan_mode(VrfClimateFanMode::CLIMATE_FAN_MODE_MEDIUM);
            break;
        case VrfSochuangClimateFanSpeed::SOCHUANG_CLIMATE_FAN_SPEED_LOW:
            target_climate->set_fan_mode(VrfClimateFanMode::CLIMATE_FAN_MODE_LOW);
            break;
        default:
            break;
        }
        target_climate->fire_data_updated();
    }

    void VrfSochuangGateway::consume_data(uint8_t data) {
        this->data_.push_back(data);

        while (this->data_.size() > 0) {
            // Each Sochuang packet is 12 bytes (address + data length + command + data + CRC)
            if (this->data_.size() < 12) {
                return;
            }

            // Check data length (0x0C = 12 bytes)
            if (this->data_[1] != 0x00 || this->data_[2] != 0x0C) {
                ESP_LOGD(TAG, "data length not correct");
                // Invalid data length
                this->data_.erase(this->data_.begin(), this->data_.begin() + 1);
                continue;
            }

            // CRC16 validation (Modbus CRC)
            // CRC1: low byte, CRC2: high byte
            std::vector<uint8_t> data_to_check(this->data_.begin(), this->data_.begin() + 10);
            uint16_t received_crc = (uint16_t(this->data_[11]) << 8) | this->data_[10]; // CRC2 << 8 | CRC1
            uint16_t calculated_crc = crc16(data_to_check);

            if (received_crc != calculated_crc) {
                // CRC validation failed
                ESP_LOGD(TAG, "crc check failed");
                this->data_.erase(this->data_.begin(), this->data_.begin() + 1);
                continue;
            }

            if (this->data_[0] != this->slave_addr_) {
                // Not my data
                this->data_.clear();
                return;
            }

            // Handle based on command type
            if (this->data_[3] == uint8_t(VrfSochuangFunc::SOCHUANG_FUNC_QUERY_COUNT)) {
                this->consume_data_handle_found_climates();
            } else if (this->data_[3] == uint8_t(VrfSochuangFunc::SOCHUANG_FUNC_QUERY_STATUS)) {
                this->consume_data_handle_query_climate();
            } else {
                // Unknown command, just log and continue
                ESP_LOGD(TAG, "Unknown command: 0x%02X", this->data_[4]);
            }

            // Erase 12 bytes
            ESP_LOGD(TAG, "consume succ, data=%s", esphome::format_hex_pretty(this->data_.data(), 12).c_str());
            this->data_.erase(this->data_.begin(), this->data_.begin() + 12);
        }
    }

    VrfCmd VrfSochuangGateway::cmd_find_climates() {
        // Query AC count command: 0x34(地址) 00 0c (数据长度) 01（指令） 00（6个字节） CRC1 CRC2
        std::vector<uint8_t> cmd = {
            this->slave_addr_, 0x00, 0x0C, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
        };

        // Calculate CRC16 (Modbus CRC)
        uint16_t crc = crc16(cmd);
        cmd.push_back(crc & 0xFF); // CRC1 (low byte)
        cmd.push_back((crc >> 8) & 0xFF); // CRC2 (high byte)

        return VrfCmd(cmd);
    }

    VrfSochuangClimate* VrfSochuangGateway::find_or_create_climate(uint8_t indoor_addr) {
        VrfSochuangClimate* target_climate = nullptr;
        for(auto &climate : this->climates_) {
            VrfSochuangClimate* climate_cast = reinterpret_cast<VrfSochuangClimate*>(climate);
            if (climate_cast->get_indoor_addr() == indoor_addr) {
                target_climate = climate_cast;
                break;
            }
        }

        if (target_climate == nullptr) {
            target_climate = new VrfSochuangClimate(this->slave_addr_, indoor_addr);
            this->climates_.push_back(target_climate);

            for(auto &callback : this->climate_create_callbacks_) {
                callback(target_climate);
            }
        }

        return target_climate;
    }

    VrfCmd VrfSochuangClimate::cmd_query() {
        // Read single AC parameter command: 0x34(地址) 00 0c (数据长度) 02（指令） 01 00(5个字节) CRC1 CRC2
        std::vector<uint8_t> cmd = {
            this->slave_addr_, 0x00, 0x0C, 0x02, this->indoor_addr_, 0x00, 0x00, 0x00, 0x00, 0x00
        };

        // Calculate CRC16 (Modbus CRC)
        uint16_t crc = crc16(cmd);
        cmd.push_back(crc & 0xFF); // CRC1 (low byte)
        cmd.push_back((crc >> 8) & 0xFF); // CRC2 (high byte)

        return VrfCmd(cmd);
    }

    static VrfSochuangClimateSwitch convert_vrf_mode_to_sochuang_switch(VrfClimateMode mode) {
        if (mode == VrfClimateMode::CLIMATE_MODE_OFF) {
            return VrfSochuangClimateSwitch::SOCHUANG_CLIMATE_SWITCH_OFF;
        }
        return VrfSochuangClimateSwitch::SOCHUANG_CLIMATE_SWITCH_ON;
    }

    static VrfSochuangClimateMode convert_vrf_mode_to_sochuang_mode(VrfClimateMode mode) {
        if (mode == VrfClimateMode::CLIMATE_MODE_OFF) {
            // When turning off, we can keep the previous mode
            return VrfSochuangClimateMode::SOCHUANG_CLIMATE_MODE_COOL;
        } else if (mode == VrfClimateMode::CLIMATE_MODE_COOL) {
            return VrfSochuangClimateMode::SOCHUANG_CLIMATE_MODE_COOL;
        } else if (mode == VrfClimateMode::CLIMATE_MODE_HEAT) {
            return VrfSochuangClimateMode::SOCHUANG_CLIMATE_MODE_HEAT;
        } else if (mode == VrfClimateMode::CLIMATE_MODE_FAN_ONLY) {
            return VrfSochuangClimateMode::SOCHUANG_CLIMATE_MODE_FAN;
        } else if (mode == VrfClimateMode::CLIMATE_MODE_DRY) {
            return VrfSochuangClimateMode::SOCHUANG_CLIMATE_MODE_DRY;
        }

        return VrfSochuangClimateMode::SOCHUANG_CLIMATE_MODE_COOL;
    }

    static VrfSochuangClimateFanSpeed convert_vrf_fan_mode_to_sochuang_fan_speed(VrfClimateFanMode fan_mode) {
        if (fan_mode == VrfClimateFanMode::CLIMATE_FAN_MODE_AUTO) {
            return VrfSochuangClimateFanSpeed::SOCHUANG_CLIMATE_FAN_SPEED_AUTO;
        } else if (fan_mode == VrfClimateFanMode::CLIMATE_FAN_MODE_HIGH) {
            return VrfSochuangClimateFanSpeed::SOCHUANG_CLIMATE_FAN_SPEED_HIGH;
        } else if (fan_mode == VrfClimateFanMode::CLIMATE_FAN_MODE_MEDIUM) {
            return VrfSochuangClimateFanSpeed::SOCHUANG_CLIMATE_FAN_SPEED_MEDIUM;
        } else if (fan_mode == VrfClimateFanMode::CLIMATE_FAN_MODE_LOW) {
            return VrfSochuangClimateFanSpeed::SOCHUANG_CLIMATE_FAN_SPEED_LOW;
        }

        return VrfSochuangClimateFanSpeed::SOCHUANG_CLIMATE_FAN_SPEED_AUTO;
    }

    VrfCmd VrfSochuangClimate::cmd_control_mode(VrfClimateMode mode) {
        this->need_fire_data_updated = true;

        if (mode == VrfClimateMode::CLIMATE_MODE_OFF) {
            // Set AC switch command: 0x34(地址) 00 0c (数据长度) 04（指令） 01（内机地址）AA（开关机）00(4个字节) CRC1 CRC2
            std::vector<uint8_t> cmd = {
                this->slave_addr_, 0x00, 0x0C, 0x04, this->indoor_addr_,
                uint8_t(convert_vrf_mode_to_sochuang_switch(mode)), // 开关机
                0x00, 0x00, 0x00, 0x00
            };

            uint16_t crc = crc16(cmd);
            cmd.push_back(crc & 0xFF); // CRC1 (low byte)
            cmd.push_back((crc >> 8) & 0xFF); // CRC2 (high byte)

            return VrfCmd(cmd);
        } else {
            // For turning on, we need to send both switch and mode
            std::vector<uint8_t> cmd = {
                this->slave_addr_, 0x00, 0x0C, 0x05, this->indoor_addr_,
                uint8_t(convert_vrf_mode_to_sochuang_mode(mode)), // 模式
                0x00, 0x00, 0x00, 0x00
            };

            uint16_t crc = crc16(cmd);
            cmd.push_back(crc & 0xFF); // CRC1 (low byte)
            cmd.push_back((crc >> 8) & 0xFF); // CRC2 (high byte)

            std::vector<uint8_t> cmd_on = {
                this->slave_addr_, 0x00, 0x0C, 0x04, this->indoor_addr_,
                1, // 开
                0x00, 0x00, 0x00, 0x00
            };

            uint16_t crc_on = crc16(cmd_on);
            cmd_on.push_back(crc_on & 0xFF); // CRC1 (low byte)
            cmd_on.push_back((crc_on >> 8) & 0xFF); // CRC2 (high byte)

            return VrfCmd({cmd, cmd_on});
        }
    }

    VrfCmd VrfSochuangClimate::cmd_control_target_temperature(uint8_t target_temperature) {
        this->need_fire_data_updated = true;

        // Set AC temperature command: 0x34(地址) 00 0c (数据长度) 06（指令） 01（内机地址）CC（温度）00(4个字节) CRC1 CRC2
        std::vector<uint8_t> cmd = {
            this->slave_addr_, 0x00, 0x0C, 0x06, this->indoor_addr_,
            target_temperature, // 温度
            0x00, 0x00, 0x00, 0x00
        };

        // Calculate CRC16 (Modbus CRC)
        uint16_t crc = crc16(cmd);
        cmd.push_back(crc & 0xFF); // CRC1 (low byte)
        cmd.push_back((crc >> 8) & 0xFF); // CRC2 (high byte)

        return VrfCmd(cmd);
    }

    VrfCmd VrfSochuangClimate::cmd_control_fan_mode(VrfClimateFanMode mode) {
        this->need_fire_data_updated = true;

        // Set AC fan speed command: 0x34(地址) 00 0c (数据长度) 07（指令） 01（内机地址）DD（风速）00(4个字节) CRC1 CRC2
        std::vector<uint8_t> cmd = {
            this->slave_addr_, 0x00, 0x0C, 0x07, this->indoor_addr_,
            uint8_t(convert_vrf_fan_mode_to_sochuang_fan_speed(mode)), // 风速
            0x00, 0x00, 0x00, 0x00
        };

        // Calculate CRC16 (Modbus CRC)
        uint16_t crc = crc16(cmd);
        cmd.push_back(crc & 0xFF); // CRC1 (low byte)
        cmd.push_back((crc >> 8) & 0xFF); // CRC2 (high byte)

        return VrfCmd(cmd);
    }

}
