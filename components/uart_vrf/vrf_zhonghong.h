#pragma once

#include <vector>
#include "esphome/core/helpers.h"
#include "vrf.h"
#include "vrf_zhonghong_const.h"

namespace vrf_protocol {

    class VrfZhonghongClimate : public vrf_protocol::VrfClimate {
        public:
        VrfZhonghongClimate(uint8_t slave_addr, uint8_t outdoor_addr, uint8_t indoor_addr) {
            this->slave_addr_ = slave_addr;
            this->outdoor_addr_ = outdoor_addr;
            this->indoor_addr_ = indoor_addr;
            this->unique_id_ = esphome::str_sprintf("%d_%d_%d", 
            this->slave_addr_, this->outdoor_addr_, this->indoor_addr_);
            this->name_ = esphome::str_sprintf("vrf_climate_%s", this->unique_id_.c_str());
        };

        uint8_t get_outdoor_addr() { return this->outdoor_addr_; };
        uint8_t get_indoor_addr() { return this->indoor_addr_; };

        VrfCmd cmd_query() override;
        VrfCmd cmd_control_mode(vrf_protocol::VrfClimateMode mode) override;
        VrfCmd cmd_control_target_temperature(uint8_t target_temperature) override;
        VrfCmd cmd_control_fan_mode(vrf_protocol::VrfClimateFanMode mode) override;

        protected:
        // 外机地址
        uint8_t outdoor_addr_;
        // 内机地址
        uint8_t indoor_addr_;
        // 上一次控制时间
        unsigned long last_time_ctrl{0};

    };

    class VrfZhonghongGateway : public vrf_protocol::VrfGateway {
        public:
        VrfZhonghongGateway(uint8_t slave_addr) : VrfGateway(slave_addr) {};
        void consume_data(uint8_t data) override;
        VrfCmd cmd_find_climates() override;
        VrfZhonghongClimate* find_or_create_climate(uint8_t outdoor_addr, uint8_t indoor_addr);

        protected:
        std::vector<uint8_t> data_;

        private:
        void consume_data_handle_found_climates();
        void consume_data_handle_query_climate();
    };

}