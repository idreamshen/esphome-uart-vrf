#include "esphome/core/application.h"
#include "uart_vrf_climate.h"

namespace esphome {
namespace uart_vrf {

void UartVrfClimate::setup() {
    ESP_LOGD(TAG, "UartVrfClimate::setup");
}

void UartVrfClimate::dump_config() {
}

void UartVrfClimate::control(const climate::ClimateCall &call) {
    if (call.get_mode().has_value()) {
        this->mode = *call.get_mode();

        vrf_protocol::VrfCmd cmd;
        switch (this->mode) {
            case climate::ClimateMode::CLIMATE_MODE_OFF:
                cmd = this->core_climate_->cmd_control_mode(vrf_protocol::VrfClimateMode::CLIMATE_MODE_OFF);
                this->get_parent()->send_cmd(cmd);
                break;
            case climate::ClimateMode::CLIMATE_MODE_COOL:
                cmd = this->core_climate_->cmd_control_mode(vrf_protocol::VrfClimateMode::CLIMATE_MODE_COOL);
                this->get_parent()->send_cmd(cmd);
                break;
            case climate::ClimateMode::CLIMATE_MODE_HEAT:
                cmd = this->core_climate_->cmd_control_mode(vrf_protocol::VrfClimateMode::CLIMATE_MODE_HEAT);
                this->get_parent()->send_cmd(cmd);
                break;
            case climate::ClimateMode::CLIMATE_MODE_FAN_ONLY:
                cmd = this->core_climate_->cmd_control_mode(vrf_protocol::VrfClimateMode::CLIMATE_MODE_FAN_ONLY);
                this->get_parent()->send_cmd(cmd);
                break;
            case climate::ClimateMode::CLIMATE_MODE_DRY:
                cmd = this->core_climate_->cmd_control_mode(vrf_protocol::VrfClimateMode::CLIMATE_MODE_DRY);
                this->get_parent()->send_cmd(cmd);
                break;
            default:
                break;
        }
    }

    if (call.get_target_temperature().has_value()) {
        uint8_t temperature = uint8_t(*call.get_target_temperature());
        this->target_temperature = temperature;
        vrf_protocol::VrfCmd cmd = this->core_climate_->cmd_control_target_temperature(this->target_temperature);
        this->get_parent()->send_cmd(cmd);
    }

    if (call.get_fan_mode().has_value()) {
        this->fan_mode = *call.get_fan_mode();
        vrf_protocol::VrfCmd cmd;
        switch (*this->fan_mode) {
            case climate::ClimateFanMode::CLIMATE_FAN_AUTO:
                cmd = this->core_climate_->cmd_control_fan_mode(vrf_protocol::VrfClimateFanMode::CLIMATE_FAN_MODE_AUTO);
                this->get_parent()->send_cmd(cmd);
                break;
            case climate::ClimateFanMode::CLIMATE_FAN_LOW:
                cmd = this->core_climate_->cmd_control_fan_mode(vrf_protocol::VrfClimateFanMode::CLIMATE_FAN_MODE_LOW);
                this->get_parent()->send_cmd(cmd);
                break;
            case climate::ClimateFanMode::CLIMATE_FAN_MEDIUM:
                cmd = this->core_climate_->cmd_control_fan_mode(vrf_protocol::VrfClimateFanMode::CLIMATE_FAN_MODE_MEDIUM);
                this->get_parent()->send_cmd(cmd);
                break;
            case climate::ClimateFanMode::CLIMATE_FAN_HIGH:
                cmd = this->core_climate_->cmd_control_fan_mode(vrf_protocol::VrfClimateFanMode::CLIMATE_FAN_MODE_HIGH);
                this->get_parent()->send_cmd(cmd);
                break;
            default:
                break;
        }
    }

    this->publish_state();
    return;
}

climate::ClimateTraits UartVrfClimate::traits() {
    auto traits = climate::ClimateTraits();
    traits.set_supports_current_temperature(true);
    traits.set_visual_target_temperature_step(1);
    traits.set_visual_temperature_step(1);
    traits.set_visual_min_temperature(16);
    traits.set_visual_max_temperature(30);
    traits.set_supported_fan_modes({
        climate::CLIMATE_FAN_AUTO,
        climate::CLIMATE_FAN_LOW,
        climate::CLIMATE_FAN_MEDIUM,
        climate::CLIMATE_FAN_HIGH
        });
    traits.set_supported_modes({
        climate::CLIMATE_MODE_OFF,
        climate::CLIMATE_MODE_HEAT,
        climate::CLIMATE_MODE_COOL,
        climate::CLIMATE_MODE_FAN_ONLY,
        climate::CLIMATE_MODE_DRY
        });
    return traits;
};

}
}