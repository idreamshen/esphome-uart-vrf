#pragma once

#include <vector>
#include "esphome/core/helpers.h"
#include "vrf.h"
#include "vrf_demry_const.h"

namespace vrf_protocol {

    class VrfDemryClimate : public VrfClimate {
        public:
        VrfDemryClimate(uint8_t slave_addr, uint8_t id) {
            this->slave_addr_ = slave_addr;
            this->outer_idx_ = id;
            this->id_ = id;
            this->unique_id_ = esphome::str_sprintf("%d_%d", this->slave_addr_, this->id_);
            this->name_ = esphome::str_sprintf("vrf_climate_%s", this->unique_id_.c_str());
        };

        uint8_t get_id() { return this->id_; };
        VrfCmd cmd_query() override;
        VrfCmd cmd_control_mode(vrf_protocol::VrfClimateMode mode) override;
        VrfCmd cmd_control_target_temperature(uint8_t target_temperature) override;
        VrfCmd cmd_control_fan_mode(vrf_protocol::VrfClimateFanMode mode) override;

        protected:
        uint8_t id_;
    };

    class VrfDemryGateway : public VrfGateway {
        public:
        VrfDemryGateway(uint8_t slave_addr): VrfGateway(slave_addr) {};
        void consume_data(uint8_t data) override;
        VrfCmd cmd_find_climates() override;

        VrfDemryClimate* find_or_create_climate(uint8_t id);

        protected:
        std::vector<uint8_t> data_;

        private:
        void consume_data_handle_found_climates();
        void consume_data_handle_query_climate();
    };

}
