#include <bitset>

#include "vrf_zhonghong.h"
#include "vrf_demry.h"
#include "uart_vrf_component.h"
#include "uart_vrf_climate.h"

namespace esphome {
namespace uart_vrf {

static const char *const TAG = "uart_vrf"; 

void VrfGatewayWrapper::add_gateway(vrf_protocol::VrfGateway* gateway) { 
    this->gateways_.push_back(gateway); 
}

void VrfGatewayWrapper::consume_data(uint8_t data) {
    if (this->vrf_gateway_ != nullptr) {
      this->vrf_gateway_->consume_data(data);
      return;
    }

    for (auto& gateway : this->gateways_) {
      if (gateway->get_climates().size() > 0) {
        this->vrf_gateway_ = gateway;
        this->vrf_gateway_->consume_data(data);
        return;
      }
    }

    for (auto& gateway : this->gateways_) {
      gateway->consume_data(data);
    }
}

uint8_t VrfGatewayWrapper::get_next_idx() {
    if (this->next_idx_ >= this->gateways_.size()) {
        this->next_idx_ = 0;
    }

    return this->next_idx_;
}

void VrfGatewayWrapper::incr_next_idx() {
    this->next_idx_ = this->next_idx_ + 1;

    if (this->next_idx_ >= this->gateways_.size()) {
        this->next_idx_ = 0;
    }
}

vrf_protocol::VrfCmd VrfGatewayWrapper::cmd_find_climates() {
    if (this->vrf_gateway_ != nullptr) {
        return this->vrf_gateway_->cmd_find_climates();
    }

    if (this->gateways_.size() == 0) {
        return {};
    }

    vrf_protocol::VrfCmd cmd = this->gateways_[this->get_next_idx()]->cmd_find_climates();
    this->incr_next_idx();
    return cmd;
}

vrf_protocol::VrfCmd VrfGatewayWrapper::cmd_query_next_climate() {
    if (this->vrf_gateway_ == nullptr) {
        return {};
    }

    return this->vrf_gateway_->cmd_query_next_climate();
}

std::vector<vrf_protocol::VrfClimate *> VrfGatewayWrapper::get_climates() {
    if (this->vrf_gateway_ == nullptr) {
        return {};
    }

    return this->vrf_gateway_->get_climates();
}

void UartVrfComponent::setup() {
 //   ESP_LOGD(TAG, "setup");

    vrf_protocol::VrfGateway* demryGateway = new vrf_protocol::VrfDemryGateway(1);
    vrf_protocol::VrfGateway* zhonghongGateway = new vrf_protocol::VrfZhonghongGateway(1);

    demryGateway->add_on_climate_create_callback([this](vrf_protocol::VrfClimate* climate) {
        this->on_climate_create_callback(climate);
    });

    zhonghongGateway->add_on_climate_create_callback([this](vrf_protocol::VrfClimate* climate) {
        this->on_climate_create_callback(climate);
    });

    this->vrf_gateway_wrapper_ = new VrfGatewayWrapper();
    this->vrf_gateway_wrapper_->add_gateway(demryGateway);
    this->vrf_gateway_wrapper_->add_gateway(zhonghongGateway);

    this->set_interval("fire_cmd", 300, [this] { this->fire_cmd(); });
    this->set_interval("find_climates", 5000, [this] { this->find_climates(); });
    this->set_interval("query_next_climate", 1000, [this] { this->query_next_climate(); });
}

void UartVrfComponent::on_climate_create_callback(vrf_protocol::VrfClimate* climate) {
    climate->add_on_state_callback([this](vrf_protocol::VrfClimate* climate) {
        this->on_climate_state_callback(climate);
    });

    auto *uart_climate = new UartVrfClimate(climate);
    uart_climate->set_parent(this);
    uart_climate->set_name(climate->get_name().c_str());
    uart_climate->set_object_id(climate->get_name().c_str());
    App.register_component(uart_climate);
    App.register_climate(uart_climate);
    this->climates_.push_back(uart_climate);
}

void UartVrfComponent::on_climate_state_callback(vrf_protocol::VrfClimate* vrf_climate) {
    UartVrfClimate* target_climate = nullptr;
    for (auto& climate : this->climates_) {
        if (climate->get_core_climate() == vrf_climate) {
            target_climate = climate;
        }
    }

    if (target_climate == nullptr) {
        return;
    }

    target_climate->current_temperature = vrf_climate->get_current_temperature();
    target_climate->target_temperature = vrf_climate->get_target_temperature();

    switch (vrf_climate->get_mode()) {
        case vrf_protocol::VrfClimateMode::CLIMATE_MODE_OFF:
            target_climate->mode = climate::ClimateMode::CLIMATE_MODE_OFF;
            break;
        case vrf_protocol::VrfClimateMode::CLIMATE_MODE_COOL:
            target_climate->mode = climate::ClimateMode::CLIMATE_MODE_COOL;
            break;
        case vrf_protocol::VrfClimateMode::CLIMATE_MODE_HEAT:
            target_climate->mode = climate::ClimateMode::CLIMATE_MODE_HEAT;
            break;
        case vrf_protocol::VrfClimateMode::CLIMATE_MODE_FAN_ONLY:
            target_climate->mode = climate::ClimateMode::CLIMATE_MODE_FAN_ONLY;
            break;
        case vrf_protocol::VrfClimateMode::CLIMATE_MODE_DRY:
            target_climate->mode = climate::ClimateMode::CLIMATE_MODE_DRY;
            break;
        default:
            break;
    }

    switch (vrf_climate->get_fan_mode()) {
        case vrf_protocol::VrfClimateFanMode::CLIMATE_FAN_MODE_AUTO:
            target_climate->fan_mode = climate::ClimateFanMode::CLIMATE_FAN_AUTO;
            break;
        case vrf_protocol::VrfClimateFanMode::CLIMATE_FAN_MODE_LOW:
            target_climate->fan_mode = climate::ClimateFanMode::CLIMATE_FAN_LOW;
            break;
        case vrf_protocol::VrfClimateFanMode::CLIMATE_FAN_MODE_MEDIUM:
            target_climate->fan_mode = climate::ClimateFanMode::CLIMATE_FAN_MEDIUM;
            break;
        case vrf_protocol::VrfClimateFanMode::CLIMATE_FAN_MODE_HIGH:
            target_climate->fan_mode = climate::ClimateFanMode::CLIMATE_FAN_HIGH;
            break;
        default:
            break;
    }

    target_climate->publish_state();
}

void UartVrfComponent::loop() {
    if (this->vrf_gateway_wrapper_ == nullptr) {
        return;
    }

    while(available() > 0) {
        uint8_t c = read();
        this->vrf_gateway_wrapper_->consume_data(c);
    }
}

void UartVrfComponent::send_cmd(vrf_protocol::VrfCmd cmd) {
    while (cmd.has_next_cmd_val()) {
        std::vector<uint8_t> cmd_val = cmd.next_cmd_val();
        if (cmd_val.size() == 0) {
            continue;
        }

        this->pending_cmds_.push_back(cmd_val);
    }

    this->fire_cmd();
}

void UartVrfComponent::find_climates() {
    if (this->vrf_gateway_wrapper_ == nullptr) {
        return;
    }

    if (this->vrf_gateway_wrapper_->get_climates().size() == 0) {
        vrf_protocol::VrfCmd cmd = this->vrf_gateway_wrapper_->cmd_find_climates();
        this->send_cmd(cmd);
    }
}

void UartVrfComponent::fire_cmd() {
    unsigned long now = millis();
    if (now - last_time_fire_cmd < 100) {
        return;
    }

    if (this->pending_cmds_.size() <= 0) {
        return;
    }

    last_time_fire_cmd = now;

    std::vector<uint8_t> cmd_val = this->pending_cmds_[0];
    this->pending_cmds_.erase(this->pending_cmds_.begin(), this->pending_cmds_.begin() + 1);
  //  ESP_LOGD(TAG, "uart send %s", format_hex_pretty(cmd_val).c_str());
    write_array(cmd_val.data(), cmd_val.size());
}

void UartVrfComponent::query_next_climate() {
    if (this->pending_cmds_.size() <= 2) {
        vrf_protocol::VrfCmd cmd = this->vrf_gateway_wrapper_->cmd_query_next_climate();
        this->send_cmd(cmd);
    }
}

  
} // namespace uart_vrf
} // namespace esphome
