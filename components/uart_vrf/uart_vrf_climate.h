#pragma once

#include "esphome/core/component.h"
#include "esphome/components/climate/climate.h"
#include "./uart_vrf_component.h"

namespace esphome {
namespace uart_vrf {

class UartVrfComponent;

class UartVrfClimate : public Component, public climate::Climate, public Parented<UartVrfComponent> {
    public:
    UartVrfClimate(vrf_protocol::VrfClimate* core_climate) {
        this->core_climate_ = core_climate;
    }
    void setup() override;
    void dump_config() override;
    void control(const climate::ClimateCall &call) override;
    climate::ClimateTraits traits() override;
    vrf_protocol::VrfClimate* get_core_climate() { return this->core_climate_; };

    protected:
    vrf_protocol::VrfClimate* core_climate_;

    private:

};

} // namespace uart_vrf
} // namespace esphome