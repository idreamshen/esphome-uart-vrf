# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an ESPHome custom component that enables UART/RS485 communication with VRF (Variable Refrigerant Flow) air conditioning systems. It supports multiple protocols including Demry and Zhonghong brands.

The component automatically detects the VRF protocol and creates Home Assistant climate entities for control.

## Code Architecture

The project follows ESPHome's component architecture with these key elements:

1. **Main Component** (`UartVrfComponent`): 
   - Handles UART communication
   - Manages protocol detection
   - Coordinates command sending/receiving
   - Located in `components/uart_vrf/uart_vrf_component.*`

2. **Climate Entity** (`UartVrfClimate`):
   - Implements ESPHome's climate interface
   - Translates Home Assistant commands to VRF protocol commands
   - Located in `components/uart_vrf/uart_vrf_climate.*`

3. **Protocol Implementations**:
   - `VrfDemryGateway` and `VrfZhonghongGateway` handle protocol-specific communication
   - Each protocol has its own header and implementation files
   - Protocol-agnostic interface defined in `vrf.h`

4. **Gateway Wrapper** (`VrfGatewayWrapper`):
   - Manages multiple protocol implementations
   - Automatically detects which protocol is in use

## Common Development Tasks

### Building and Testing
- The project is built using ESPHome tooling
- Create a YAML configuration file (see examples in `example/` directory)
- Use ESPHome commands to compile and upload firmware

### Adding New Protocols
1. Create new protocol implementation files (e.g., `vrf_newbrand.h` and `vrf_newbrand.cpp`)
2. Implement the `VrfGateway` and `VrfClimate` interfaces
3. Register the new gateway in `UartVrfComponent::setup()`
4. Add any protocol-specific constants to a new const header file

### Modifying Existing Protocols
- Protocol-specific logic is in the respective implementation files
- Command generation and parsing happens in the gateway and climate classes
- Data handling is in the `consume_data()` methods

## Configuration Example

```yaml
external_components:
  - source:
      type: git
      url: https://github.com/idreamshen/esphome-uart-vrf

uart:
  - id: myuart1
    tx_pin: 1
    rx_pin: 3
    baud_rate: 9600

uart_vrf:

climate:
```

## Supported Hardware

The component works with ESP8266 and ESP32 chips. Example configurations are provided for ESP01S and ESP32-WROOM-32D boards.