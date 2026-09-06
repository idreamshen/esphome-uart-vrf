#pragma once

#include "esphome/components/climate/climate.h"
#include "./uart_vrf_component.h"

namespace esphome {
namespace uart_vrf {

class UartVrfComponent;

class UartVrfClimate : public climate::Climate, public Parented<UartVrfComponent> {
    public:
    UartVrfClimate(vrf_protocol::VrfClimate* core_climate, uint8_t outer_idx) {
        this->core_climate_ = core_climate;
        this->outer_idx_ = outer_idx;
    }
    void control(const climate::ClimateCall &call) override;
    climate::ClimateTraits traits() override;
    void apply_restored_state();
    vrf_protocol::VrfClimate* get_core_climate() { return this->core_climate_; };
    uint8_t get_outer_idx() const { return this->outer_idx_; }
    vrf_protocol::VrfClimate* core_climate_;

    private:
    uint8_t outer_idx_{0};

};

} // namespace uart_vrf
} // namespace esphome
