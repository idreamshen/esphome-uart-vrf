import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID
from esphome.components import uart, binary_sensor


DEPENDENCIES = ['uart']
AUTO_LOAD = ['climate']

VRF_ID = 'uart_vrf_id'

CONF_ALLOW_HEAT_MODE='allow_heat_mode'
CONF_ALLOW_HEAT_MODE_SENSOR='allow_heat_mode_sensor'

uart_vrf_ns = cg.esphome_ns.namespace('uart_vrf')
UartVrfComponent = uart_vrf_ns.class_('UartVrfComponent', cg.Component, uart.UARTDevice)

CONFIG_SCHEMA = cv.Schema({
    cv.GenerateID(): cv.declare_id(UartVrfComponent),
    cv.Optional(CONF_ALLOW_HEAT_MODE_SENSOR): cv.use_id(binary_sensor.BinarySensor),
}).extend(cv.COMPONENT_SCHEMA).extend(uart.UART_DEVICE_SCHEMA)

def to_code(config):
    u = yield cg.get_variable(config["uart_id"])
    var = cg.new_Pvariable(config[CONF_ID], u)

    # Add allow heat mode configuration
    if CONF_ALLOW_HEAT_MODE_SENSOR in config:
        allow_heat_sensor = yield cg.get_variable(config[CONF_ALLOW_HEAT_MODE_SENSOR])
        cg.add(var.set_allow_heat_mode_sensor(allow_heat_sensor))

    yield cg.register_component(var, config)
    yield uart.register_uart_device(var, config)
