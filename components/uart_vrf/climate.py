import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import climate
from esphome.const import CONF_ID
from .. import UartVrfComponent

DEPENDENCIES = ['uart_vrf']

uart_vrf_ns = cg.esphome_ns.namespace('uart_vrf')
uartVrfClimate = uart_vrf_ns.class_('UartVrfClimate', 
    climate.Climate, 
    cg.Component, 
    cg.Parented.template(UartVrfComponent),
)

CONFIG_SCHEMA = climate.CLIMATE_SCHEMA.extend({
    cv.GenerateID(): cv.declare_id(uartVrfClimate),
    cv.GenerateID("uart_vrf_id"): cv.use_id(UartVrfComponent),
    cv.Optional("bind_climate_id"): cv.use_id(climate)
}).extend(cv.COMPONENT_SCHEMA)

def to_code(config):
    paren = yield cg.get_variable(config["uart_vrf_id"])
    var = cg.new_Pvariable(config[CONF_ID])
    yield cg.register_parented(var, paren)
    yield cg.register_component(var, config)
    yield climate.register_climate(var, config)
    
    # cg.add(paren.register_homekit_entities(var))
    # if "bind_climate_id" in config:
    #     bind_climate = yield cg.get_variable(config["bind_climate_id"])
    #     cg.add(var.set_bind_climate(bind_climate))