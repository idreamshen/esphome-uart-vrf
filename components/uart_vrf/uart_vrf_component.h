#pragma once

#include "esphome.h"
#include "esphome/core/component.h"
#include "esphome/core/preferences.h"
#include "esphome/components/uart/uart.h"
#include "esphome/components/binary_sensor/binary_sensor.h"

namespace vrf_protocol { // Forward declaration
  class VrfCmd;
  class VrfGateway;
}
#include "vrf.h"

// Random 32bit value; If this changes existing restore preferences are invalidated
static const uint32_t UART_VRF_CLIMATE_STORE_STATE_VERSION = 0x324BB78EUL;

#define MAX_VRF_CLIMATES 32


namespace esphome {
namespace uart_vrf {

struct UartVrfClimateStoreState {
  bool initialized;
  uint8_t count;
  uint32_t outer_idx_bit;
} __attribute__((packed));


class UartVrfClimate;

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
  void save_climate_state();
  bool is_heat_mode_allowed();
  void set_allow_heat_mode_sensor(binary_sensor::BinarySensor *sensor) { this->allow_heat_mode_sensor_ = sensor; }

protected:
  uart::UARTComponent* uart_;
  VrfGatewayWrapper* vrf_gateway_wrapper_;
  std::vector<UartVrfClimate*> climates_;
  std::vector<std::vector<uint8_t>> pending_cmds_;
  unsigned long last_time_heartbeat_cmds_{0};
  unsigned long last_time_fire_cmd{0};
  ESPPreferenceObject rtc_;
  bool climates_saved_{false};
  bool need_reboot_after_climates_saved_{false};
  binary_sensor::BinarySensor *allow_heat_mode_sensor_{nullptr};

  void fire_cmd();
  void find_climates();
  void query_next_climate();
  optional<UartVrfClimateStoreState> restore_climate_state_();
  void initialize_climates_from_restore(const UartVrfClimateStoreState& state);

};

}
}
