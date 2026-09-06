"""Golden-vector tests for the supported VRF protocol simulators."""

from __future__ import annotations

import pytest

from support.simulator import (
    ClimateMode,
    ClimateState,
    DemrySimulator,
    FanMode,
    SochuangSimulator,
    ZhonghongSimulator,
)


@pytest.fixture
def climate_state() -> ClimateState:
    return ClimateState(
        address=1,
        power=True,
        mode=ClimateMode.HEAT,
        fan_mode=FanMode.HIGH,
        target_temperature=22,
        current_temperature=27,
    )


def test_demry_golden_vectors(climate_state: ClimateState) -> None:
    simulator = DemrySimulator(-1, climate_state)
    discovery_request = bytes.fromhex("01 aa ff ff ff ff ff ff ff a4")
    temperature_control = bytes.fromhex("01 01 01 01 17 03 ff ff ff 1b")

    assert simulator.encode_discovery_response() == bytes.fromhex(
        "01 aa ff ff ff 00 00 00 02 aa"
    )
    assert simulator.encode_state_response() == bytes.fromhex(
        "01 01 01 01 16 03 1b ff ff 36"
    )
    assert simulator.feed_bytes(discovery_request) == [discovery_request]
    assert simulator.response_queue.get_nowait() == simulator.encode_discovery_response()

    assert simulator.feed_bytes(temperature_control) == [temperature_control]
    assert climate_state.target_temperature == 23
    assert simulator.response_queue.get_nowait() == bytes.fromhex(
        "01 01 01 01 17 03 1b ff ff 37"
    )


def test_sochuang_golden_vectors(climate_state: ClimateState) -> None:
    simulator = SochuangSimulator(-1, climate_state)
    discovery_request = bytes.fromhex("01 00 0c 01 00 00 00 00 00 00 31 57")
    temperature_control = bytes.fromhex("01 00 0c 06 01 17 00 00 00 00 32 45")

    assert simulator.encode_discovery_response() == bytes.fromhex(
        "01 00 0c 01 01 00 00 00 00 00 30 86"
    )
    assert simulator.encode_state_response() == bytes.fromhex(
        "01 00 0c 02 01 01 01 16 02 1b 9f 15"
    )
    assert simulator.feed_bytes(discovery_request) == [discovery_request]
    assert simulator.response_queue.get_nowait() == simulator.encode_discovery_response()

    assert simulator.feed_bytes(temperature_control) == [temperature_control]
    assert climate_state.target_temperature == 23
    assert simulator.response_queue.empty()


def test_zhonghong_golden_vectors(climate_state: ClimateState) -> None:
    simulator = ZhonghongSimulator(
        -1,
        climate_state,
        outdoor_address=2,
    )
    discovery_request = bytes.fromhex("01 50 02 ff ff ff 50")
    temperature_control = bytes.fromhex("01 32 17 01 02 01 4e")

    assert simulator.encode_discovery_response() == bytes.fromhex(
        "01 50 02 01 02 01 01 58"
    )
    assert simulator.encode_state_response() == bytes.fromhex(
        "01 50 01 01 02 01 01 16 08 01 1b 00 00 00 91"
    )
    assert simulator.feed_bytes(discovery_request) == [discovery_request]
    assert simulator.response_queue.get_nowait() == simulator.encode_discovery_response()

    assert simulator.feed_bytes(temperature_control) == [temperature_control]
    assert climate_state.target_temperature == 23
    assert simulator.response_queue.empty()
