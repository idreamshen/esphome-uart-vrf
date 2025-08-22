#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <functional>

#include "vrf_const.h"

namespace vrf_protocol {

uint8_t checksum(std::vector<uint8_t> cmd);
uint16_t crc16(std::vector<uint8_t> cmd);

class VrfCmd {
    public:
    VrfCmd() {}
    VrfCmd(std::vector<uint8_t> cmd) { this->cmds_.push_back(cmd); }
    VrfCmd(std::vector<std::vector<uint8_t>> cmds) { this->cmds_ = cmds; }

    bool has_next_cmd_val() {
        if (this->cmds_.size() == 0) {
            return false;
        }

        if (idx_ >= this->cmds_.size()) {
            return false;
        }

        return true;
    }

    std::vector<uint8_t> next_cmd_val() {
        if (!has_next_cmd_val()) {
            return {};
        }

        std::vector<uint8_t> next_val =  this->cmds_[idx_];
        idx_ = idx_ + 1;
        return next_val;
    }

    protected:
    uint8_t idx_{0};
    std::vector<std::vector<uint8_t>> cmds_;
};

class VrfClimate {
    public:

    VrfClimateMode get_mode() { return this->mode_; };
    uint8_t get_current_temperature() { return this->current_temperature_; };
    uint8_t get_target_temperature() { return this->target_temperature_; };
    VrfClimateFanMode get_fan_mode() { return this->fan_mode_; };
    void set_mode(VrfClimateMode mode);
    void set_fan_mode(VrfClimateFanMode fan_mode);
    void set_current_temperature(uint8_t temperature);
    void set_target_temperature(uint8_t temperature);
    void fire_data_updated();
    void add_on_state_callback(std::function<void(VrfClimate *)> &&callback) { this->on_state_callbacks_.push_back(callback); };
    std::string& get_unique_id() { return this->unique_id_; };
    std::string& get_name() { return this->name_; };
    uint8_t get_outer_idx() { return this->outer_idx_; };

    virtual VrfCmd cmd_query() = 0;
    virtual VrfCmd cmd_control_mode(VrfClimateMode mode) = 0;
    virtual VrfCmd cmd_control_target_temperature(uint8_t target_temperature) = 0;
    virtual VrfCmd cmd_control_fan_mode(VrfClimateFanMode mode) = 0;

    protected:
    uint8_t slave_addr_;
    uint8_t outer_idx_;
    std::string unique_id_;
    std::string name_;
    VrfClimateMode mode_{VrfClimateMode::CLIMATE_MODE_OFF};
    uint8_t current_temperature_{21};
    uint8_t target_temperature_;
    VrfClimateFanMode fan_mode_{VrfClimateFanMode::CLIMATE_FAN_MODE_LOW};
    bool need_fire_data_updated{false};
    std::vector<std::function<void(VrfClimate *)>> on_state_callbacks_;
};

class VrfGateway {
    public:
    VrfGateway(uint8_t slave_addr) { this->slave_addr_=slave_addr;};
    virtual void consume_data(uint8_t data) = 0;
    virtual VrfCmd cmd_find_climates() = 0;
    VrfCmd cmd_query_next_climate();

    // 当 climate 被创建时触发
    void add_on_climate_create_callback(std::function<void(VrfClimate *)> &&callback);

    std::vector<VrfClimate *> get_climates();

    protected:
    uint8_t slave_addr_;
    uint8_t next_query_climate_idx_{0};
    std::vector<VrfClimate *> climates_;
    std::vector<std::function<void(VrfClimate *)>> climate_create_callbacks_;
};

}
