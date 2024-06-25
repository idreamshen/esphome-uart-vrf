#pragma once

namespace vrf_protocol {

    enum class VrfZhonghongClimateSwitch : uint8_t {
        ZHONG_HONG_CLIMATE_SWITCH_OFF = 0x00,
        ZHONG_HONG_CLIMATE_SWITCH_ON = 0x01,
    };

    enum class VrfZhonghongClimateMode : uint8_t {
        ZHONG_HONG_CLIMATE_MODE_HEAT = 0x08,
        ZHONG_HONG_CLIMATE_MODE_COOL = 0x01,
        ZHONG_HONG_CLIMATE_MODE_FAN = 0x04,
        ZHONG_HONG_CLIMATE_MODE_DRY = 0x02,

        ZHONG_HONG_CLIMATE_MODE_HOLD = 0xFF,
    };

    enum class VrfZhonghongClimateFanSpeed : uint8_t {
        ZHONG_HONG_CLIMATE_FAN_SPEED_LOW = 0x04,
        ZHONG_HONG_CLIMATE_FAN_SPEED_MEDIUM = 0x02,
        ZHONG_HONG_CLIMATE_FAN_SPEED_HIGH = 0x01,

        ZHONG_HONG_CLIMATE_FAN_SPEED_HOLD = 0xFF,
    };

    enum class VrfZhonghongFuncValue : uint8_t {
        ZHONG_HONG_FUNC_VALUE_SINGLE = 0x01,
        ZHONG_HONG_FUNC_VALUE_MULTI = 0x0F,
        ZHONG_HONG_FUNC_VALUE_ALL = 0xFF,
        ZHONG_HONG_FUNC_VALUE_ONLINE = 0x02,
    };

    enum class VrfZhonghongFunc : uint8_t {
        ZHONG_HONG_FUNC_CTRL_SWITCH = 0x31,
        ZHONG_HONG_FUNC_CTRL_TEMPERATURE = 0x32,
        ZHONG_HONG_FUNC_CTRL_MODE = 0x33,
        ZHONG_HONG_FUNC_CTRL_FAN_MODE = 0x34,

        ZHONG_HONG_FUNC_QUERY = 0x50,
    };

}