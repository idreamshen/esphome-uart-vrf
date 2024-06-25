#pragma once

namespace vrf_protocol {
    
    enum class VrfClimateMode : uint8_t {
        CLIMATE_MODE_OFF = 0,
        CLIMATE_MODE_COOL = 1,
        CLIMATE_MODE_HEAT = 2,
        CLIMATE_MODE_FAN_ONLY = 3,
        CLIMATE_MODE_DRY = 4,
    };

    enum class VrfClimateFanMode : uint8_t {
        CLIMATE_FAN_MODE_AUTO = 0,
        CLIMATE_FAN_MODE_LOW = 1,
        CLIMATE_FAN_MODE_MEDIUM = 2,
        CLIMATE_FAN_MODE_HIGH = 3,
    };
    
}