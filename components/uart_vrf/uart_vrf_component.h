#pragma once

#include "esphome.h"
#include "esphome/core/component.h"
#include "esphome/components/uart/uart.h"

namespace vrf_protocol { // Forward declaration
  class VrfCmd;
  class VrfGateway; 
}
#include "vrf.h"

namespace esphome {
namespace uart_vrf {

class UartVrfClimate; 

static const char *const TAG = "uart_vrf"; 

class VrfGatewayWrapper {

  public:
  void add_gateway(vrf_protocol::VrfGateway* gateway);
  void consume_data(uint8_t data);
  vrf_protocol::VrfCmd cmd_find_climates();
  vrf_protocol::VrfCmd cmd_query_next_climate();
  std::vector<vrf_protocol::VrfClimate *> get_climates();

  private:
  // 目标
  vrf_protocol::VrfGateway* vrf_gateway_{nullptr};
  std::vector<vrf_protocol::VrfGateway*> gateways_;
  uint8_t next_idx_{0};

  uint8_t get_next_idx();
  void incr_next_idx();
};

class UartVrfComponent : public Component, public uart::UARTDevice {
public:
  UartVrfComponent(uart::UARTComponent *uartComponent) : Component(), UARTDevice(uartComponent) {
    this->uart_ = uartComponent;
  };
  void setup() override;
  void loop() override;
  void send_cmd(vrf_protocol::VrfCmd cmd);
  uart::UARTComponent* get_uart() { return this->uart_; };
  void on_climate_create_callback(vrf_protocol::VrfClimate* climate);
  void on_climate_state_callback(vrf_protocol::VrfClimate* climate);

protected:
  uart::UARTComponent* uart_;
  VrfGatewayWrapper* vrf_gateway_wrapper_;
  std::vector<UartVrfClimate*> climates_;
  std::vector<std::vector<uint8_t>> pending_cmds_;
  unsigned long last_time_heartbeat_cmds_{0};
  unsigned long last_time_fire_cmd{0};

  void fire_cmd();
  void find_climates();
  void query_next_climate();
  
};

}
}
