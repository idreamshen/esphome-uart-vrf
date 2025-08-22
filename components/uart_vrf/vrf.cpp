#include <string>
#include <vector>
#include <functional>

#include "vrf.h"

#include "esphome/core/log.h"

namespace vrf_protocol {

uint8_t checksum(std::vector<uint8_t> cmd) {
    uint8_t sum = 0;
    for (uint8_t i = 0; i < cmd.size(); i++)
    {
        sum = sum + cmd[i];
    }
    return sum;
}

uint16_t crc16(std::vector<uint8_t> cmd) {
    uint16_t crc = 0xFFFF;
    for (uint8_t byte : cmd) {
        crc ^= byte;
        for (int i = 0; i < 8; i++) {
            if (crc & 0x0001) {
                crc >>= 1;
                crc ^= 0xA001; // Modbus CRC16 polynomial
            } else {
                crc >>= 1;
            }
        }
    }
    return crc;
}

void VrfClimate::set_mode(VrfClimateMode mode) { 
    if (this->mode_ != mode) {
        this->need_fire_data_updated=true;
    }
    this->mode_ = mode;
};

void VrfClimate::set_fan_mode(VrfClimateFanMode fan_mode) { 
    if (this->fan_mode_ != fan_mode) {
        this->need_fire_data_updated=true;
    }
    this->fan_mode_ = fan_mode; 
};

void VrfClimate::set_current_temperature(uint8_t temperature) { 
    if (this->current_temperature_ != temperature) {
        this->need_fire_data_updated=true;
    }
    this->current_temperature_ = temperature; 
};

void VrfClimate::set_target_temperature(uint8_t temperature) { 
    if (this->target_temperature_ != temperature) {
        this->need_fire_data_updated=true;
    }
    this->target_temperature_ = temperature; 
};

void VrfClimate::fire_data_updated() {
    if (this->need_fire_data_updated) {
        this->need_fire_data_updated = false;
        for (auto &callback : this-> on_state_callbacks_) {
            callback(this);
        }
    }
}

VrfCmd VrfGateway::cmd_query_next_climate() {
    VrfCmd empty_cmd = VrfCmd();

    if (this->climates_.size() == 0) {
        return empty_cmd;
    }

    if (this->next_query_climate_idx_ >= this->climates_.size()) {
        this->next_query_climate_idx_ = 0;
    }

    VrfCmd cmd = this->climates_[this->next_query_climate_idx_]->cmd_query();
    this->next_query_climate_idx_ = this->next_query_climate_idx_ + 1;
    return cmd;
}

void VrfGateway::add_on_climate_create_callback(std::function<void(VrfClimate *)> &&callback) {
    this->climate_create_callbacks_.push_back(callback); 
};

std::vector<VrfClimate *> VrfGateway::get_climates() { 
    return this->climates_; 
};

}