#pragma once

namespace vrf_protocol {

    enum class VrfDemryClimateSwitch : uint8_t {
        DEMRY_CLIAMTE_SWITCH_DISABLE = 0x00,
        DEMRY_CLIAMTE_SWITCH_ENABLE = 0x01,
    };

    enum class VrfDemryClimateMode : uint8_t {
        DEMRY_CLIMATE_MODE_HEAT = 0x01,
        DEMRY_CLIMATE_MODE_COOL = 0x02,
        DEMRY_CLIMATE_MODE_FAN = 0x04,
        DEMRY_CLIMATE_MODE_DRY = 0x08,

        DEMRY_CLIMATE_MODE_HOLD = 0xFF,
    };

    enum class VrfDemryClimateFanSpeed : uint8_t {
        DEMRY_CLIMATE_FAN_SPEED_AUTO = 0x00,
        DEMRY_CLIMATE_FAN_SPEED_LOW = 0x01,
        DEMRY_CLIMATE_FAN_SPEED_MEDIUM = 0x02,
        DEMRY_CLIMATE_FAN_SPEED_HIGH = 0x03,

        DEMRY_CLIMATE_FAN_SPEED_HOLD = 0xFF,
    };

}