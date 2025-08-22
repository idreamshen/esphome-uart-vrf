#pragma once

#include <vector>
#include "esphome/core/helpers.h"
#include "vrf.h"

namespace vrf_protocol {

    enum class VrfSochuangFunc : uint8_t {
        SOCHUANG_FUNC_QUERY_COUNT = 0x01,
        SOCHUANG_FUNC_QUERY_STATUS = 0x02,
        SOCHUANG_FUNC_CTRL_SWITCH = 0x04,
        SOCHUANG_FUNC_CTRL_MODE = 0x05,
        SOCHUANG_FUNC_CTRL_TEMPERATURE = 0x06,
        SOCHUANG_FUNC_CTRL_FAN_MODE = 0x07,
    };

    enum class VrfSochuangClimateSwitch : uint8_t {
        SOCHUANG_CLIMATE_SWITCH_OFF = 0x00,
        SOCHUANG_CLIMATE_SWITCH_ON = 0x01,
    };

    enum class VrfSochuangClimateMode : uint8_t {
        SOCHUANG_CLIMATE_MODE_COOL = 0x00,
        SOCHUANG_CLIMATE_MODE_HEAT = 0x01,
        SOCHUANG_CLIMATE_MODE_FAN = 0x02,
        SOCHUANG_CLIMATE_MODE_DRY = 0x03,
    };

    enum class VrfSochuangClimateFanSpeed : uint8_t {
        SOCHUANG_CLIMATE_FAN_SPEED_LOW = 0x00,
        SOCHUANG_CLIMATE_FAN_SPEED_MEDIUM = 0x01,
        SOCHUANG_CLIMATE_FAN_SPEED_HIGH = 0x02,
        SOCHUANG_CLIMATE_FAN_SPEED_AUTO = 0x03,
    };

    class VrfSochuangClimate : public vrf_protocol::VrfClimate {
        public:
        VrfSochuangClimate(uint8_t slave_addr, uint8_t indoor_addr) {
            this->slave_addr_ = slave_addr;
            this->outer_idx_ = indoor_addr;
            this->indoor_addr_ = indoor_addr;
            this->unique_id_ = esphome::str_sprintf("%d_%d",
            this->slave_addr_, this->indoor_addr_);
            this->name_ = esphome::str_sprintf("vrf_climate_%s", this->unique_id_.c_str());
        };

        uint8_t get_indoor_addr() { return this->indoor_addr_; };

        VrfCmd cmd_query() override;
        VrfCmd cmd_control_mode(vrf_protocol::VrfClimateMode mode) override;
        VrfCmd cmd_control_target_temperature(uint8_t target_temperature) override;
        VrfCmd cmd_control_fan_mode(vrf_protocol::VrfClimateFanMode mode) override;

        protected:
        // 内机地址
        uint8_t indoor_addr_;
        // 上一次控制时间
        unsigned long last_time_ctrl{0};

    };

    class VrfSochuangGateway : public vrf_protocol::VrfGateway {
        public:
        VrfSochuangGateway(uint8_t slave_addr) : VrfGateway(slave_addr) {};
        void consume_data(uint8_t data) override;
        VrfCmd cmd_find_climates() override;
        VrfSochuangClimate* find_or_create_climate(uint8_t indoor_addr);

        protected:
        std::vector<uint8_t> data_;

        private:
        void consume_data_handle_found_climates();
        void consume_data_handle_query_climate();
    };

}