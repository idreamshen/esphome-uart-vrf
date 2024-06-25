# esphome-uart-vrf

```yaml
esphome:
  name: vrf-8266
  friendly_name: vrf-8266

esp8266:
  board: esp01_1m

external_components:
  - source:
      type: git
      url: https://github.com/idreamshen/esphome-uart-vrf
    refresh: 5min

logger:
  baud_rate: 0

api:

ota:
  password: "d0cd7d439s1a8a0374502b78a2c88fee"

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

  # Enable fallback hotspot (captive portal) in case wifi connection fails
  ap:
    ssid: "Vrf-8266 Fallback Hotspot"
    password: "oOdtYvZHP3xK"

captive_portal:
  
uart:
  - id: myuart1
    tx_pin: 1
    rx_pin: 3
    baud_rate: 9600

uart_vrf:

climate:

web_server:
  port: 80
```