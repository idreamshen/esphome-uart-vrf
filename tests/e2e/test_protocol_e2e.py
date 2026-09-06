"""ESPHome host lifecycle tests against each supported VRF simulator."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from support import HostProcess, JsonlTrace, NativeApiAdapter, PtyUart
from support.simulator import (
    ClimateMode,
    ClimateState,
    DemrySimulator,
    FanMode,
    SochuangSimulator,
    TraceEvent,
    VrfSimulator,
    ZhonghongSimulator,
)

pytestmark = [
    pytest.mark.host_e2e,
    pytest.mark.slow,
    pytest.mark.timeout(180),
]


@dataclass(frozen=True)
class ProtocolCase:
    name: str
    create_simulator: Callable[[int, ClimateState, Callable[[TraceEvent], None]], VrfSimulator]
    is_discovery_request: Callable[[bytes], bool]
    is_state_query: Callable[[bytes], bool]
    is_heat_control: Callable[[bytes], bool]
    is_power_on_control: Callable[[bytes], bool] | None
    is_temperature_control: Callable[[bytes], bool]
    is_high_fan_control: Callable[[bytes], bool]
    is_off_control: Callable[[bytes], bool]


CASES = (
    ProtocolCase(
        name="demry",
        create_simulator=lambda fd, state, trace: DemrySimulator(
            fd, state, trace=trace
        ),
        is_discovery_request=lambda frame: frame
        == bytes.fromhex("01 aa ff ff ff ff ff ff ff a4"),
        is_state_query=lambda frame: len(frame) == 10
        and frame[1] == 1
        and frame[2:9] == b"\xff" * 7,
        is_heat_control=lambda frame: len(frame) == 10
        and frame[1] == 1
        and frame[2:4] == b"\x01\x01",
        is_power_on_control=None,
        is_temperature_control=lambda frame: len(frame) == 10
        and frame[1] == 1
        and frame[4] == 23
        and frame[2:4] != b"\xff\xff",
        is_high_fan_control=lambda frame: len(frame) == 10
        and frame[1] == 1
        and frame[5] == 3,
        is_off_control=lambda frame: len(frame) == 10
        and frame[1] == 1
        and frame[2] == 0,
    ),
    ProtocolCase(
        name="sochuang",
        create_simulator=lambda fd, state, trace: SochuangSimulator(
            fd, state, trace=trace
        ),
        is_discovery_request=lambda frame: frame
        == bytes.fromhex("01 00 0c 01 00 00 00 00 00 00 31 57"),
        is_state_query=lambda frame: len(frame) == 12
        and frame[3] == 0x02
        and frame[4] == 1,
        is_heat_control=lambda frame: len(frame) == 12
        and frame[3] == 0x05
        and frame[4:6] == b"\x01\x01",
        is_power_on_control=lambda frame: len(frame) == 12
        and frame[3] == 0x04
        and frame[4:6] == b"\x01\x01",
        is_temperature_control=lambda frame: len(frame) == 12
        and frame[3] == 0x06
        and frame[4] == 1
        and frame[5] == 23,
        is_high_fan_control=lambda frame: len(frame) == 12
        and frame[3] == 0x07
        and frame[4:6] == b"\x01\x02",
        is_off_control=lambda frame: len(frame) == 12
        and frame[3] == 0x04
        and frame[4:6] == b"\x01\x00",
    ),
    ProtocolCase(
        name="zhonghong",
        create_simulator=lambda fd, state, trace: ZhonghongSimulator(
            fd,
            state,
            outdoor_address=2,
            trace=trace,
        ),
        is_discovery_request=lambda frame: frame
        == bytes.fromhex("01 50 02 ff ff ff 50"),
        is_state_query=lambda frame: len(frame) == 7
        and frame[1:4] == b"\x50\x01\x01"
        and frame[4:6] == b"\x02\x01",
        is_heat_control=lambda frame: len(frame) == 7
        and frame[1:3] == b"\x33\x08"
        and frame[4:6] == b"\x02\x01",
        is_power_on_control=lambda frame: len(frame) == 7
        and frame[1:3] == b"\x31\x01"
        and frame[4:6] == b"\x02\x01",
        is_temperature_control=lambda frame: len(frame) == 7
        and frame[1] == 0x32
        and frame[2] == 23
        and frame[4:6] == b"\x02\x01",
        is_high_fan_control=lambda frame: len(frame) == 7
        and frame[1:3] == b"\x34\x01"
        and frame[4:6] == b"\x02\x01",
        is_off_control=lambda frame: len(frame) == 7
        and frame[1:3] == b"\x31\x00"
        and frame[4:6] == b"\x02\x01",
    ),
)


def _trace_simulator(trace: JsonlTrace) -> Callable[[TraceEvent], None]:
    def record(event: TraceEvent) -> None:
        trace.record(
            "simulator.event",
            direction=event.direction,
            data=event.data,
            note=event.note,
        )

    return record


def _is_climate_state(state: object, key: int) -> bool:
    return (
        getattr(state, "key", None) == key
        and state.__class__.__name__ == "ClimateState"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("simulator_type", "is_discovery_request", "is_state_query"),
    [
        pytest.param(
            DemrySimulator,
            lambda frame: frame == bytes.fromhex(
                "01 aa ff ff ff ff ff ff ff a4"
            ),
            lambda frame: len(frame) == 10
            and frame[1] == 1
            and frame[2:9] == b"\xff" * 7,
            id="demry",
        ),
        pytest.param(
            SochuangSimulator,
            lambda frame: frame == bytes.fromhex(
                "01 00 0c 01 00 00 00 00 00 00 31 57"
            ),
            lambda frame: len(frame) == 12
            and frame[3] == 0x02
            and frame[4] == 1,
            id="sochuang",
        ),
    ],
)
async def test_fixed_length_parser_recovers_after_bad_frame_overlap(
    simulator_type: type[VrfSimulator],
    is_discovery_request: Callable[[bytes], bool],
    is_state_query: Callable[[bytes], bool],
    pty_uart: PtyUart,
    host_process: HostProcess,
    native_api: NativeApiAdapter,
    trace: JsonlTrace,
) -> None:
    state = ClimateState(
        address=1,
        power=True,
        mode=ClimateMode.COOL,
        fan_mode=FanMode.MEDIUM,
        target_temperature=22,
        current_temperature=25,
    )
    simulator = simulator_type(
        pty_uart.fileno(),
        state,
        trace=_trace_simulator(trace),
    )
    simulator.auto_respond = False
    simulator.start()
    try:
        await simulator.wait_for_frame(is_discovery_request, timeout=10)
        await native_api.connect(timeout=2)
        assert await native_api.climate_entities() == []
        await native_api.disconnect()

        await simulator.write(simulator.encode_discovery_response())  # type: ignore[attr-defined]
        await simulator.wait_for_frame(is_state_query, timeout=2)
        await native_api.connect(timeout=2)
        climates = await native_api.wait_for_climate_entities(timeout=2)
        assert len(climates) == 1
        await simulator.write(simulator.encode_state_response())  # type: ignore[attr-defined]

        state.current_temperature = 31
        response = simulator.encode_state_response()  # type: ignore[attr-defined]
        bad_response = bytearray(response)
        bad_response[0] ^= 0x01
        await simulator.write(bytes(bad_response) + response)
        await native_api.wait_for_state(
            lambda value: _is_climate_state(value, climates[0].key)
            and value.current_temperature == pytest.approx(31),
            timeout=2,
            description="fixed-length recovery after overlapping bad response",
        )
        host_process.assert_running()
    finally:
        await native_api.disconnect()
        await simulator.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed_prefix",
    [
        pytest.param(
            bytes.fromhex("01 50 01 1a 00 00 00 00 6c"),
            id="single-count-overflow",
        ),
        pytest.param(b"\x01", id="invalid-function"),
        pytest.param(
            bytes.fromhex("01 50 02 40"),
            id="truncated-discovery-before-complete-response",
        ),
        pytest.param(
            bytes.fromhex("01 50 02 01 02 01 01 00"),
            id="bad-checksum",
        ),
    ],
)
async def test_zhonghong_parser_recovers_after_malformed_prefix(
    malformed_prefix: bytes,
    pty_uart: PtyUart,
    host_process: HostProcess,
    native_api: NativeApiAdapter,
    trace: JsonlTrace,
) -> None:
    state = ClimateState(
        address=1,
        power=True,
        mode=ClimateMode.COOL,
        fan_mode=FanMode.MEDIUM,
        target_temperature=22,
        current_temperature=25,
    )
    simulator = ZhonghongSimulator(
        pty_uart.fileno(),
        state,
        outdoor_address=2,
        trace=_trace_simulator(trace),
    )
    simulator.auto_respond = False
    simulator.start()
    try:
        discovery_request = bytes.fromhex("01 50 02 ff ff ff 50")
        await simulator.wait_for_frame(
            lambda frame: frame == discovery_request,
            timeout=10,
        )
        await native_api.connect(timeout=2)
        assert await native_api.climate_entities() == []

        await simulator.write(
            malformed_prefix + simulator.encode_discovery_response(),
            fragment_sizes=(1, 2, 3),
            inter_fragment_delay=0.005,
        )
        await simulator.wait_for_frame(
            lambda frame: len(frame) == 7
            and frame[1:4] == b"\x50\x01\x01"
            and frame[4:6] == b"\x02\x01",
            timeout=2,
        )
        host_process.assert_running()

        await native_api.connect(timeout=2)
        climates = await native_api.wait_for_climate_entities(timeout=2)
        assert len(climates) == 1
        assert climates[0].object_id.endswith("1_1")
        host_process.assert_running()
    finally:
        await native_api.disconnect()
        await simulator.stop()


@pytest.mark.asyncio
async def test_demry_discards_complete_foreign_slave_frame(
    pty_uart: PtyUart,
    host_process: HostProcess,
    native_api: NativeApiAdapter,
    trace: JsonlTrace,
) -> None:
    state = ClimateState(address=1, power=True)
    simulator = DemrySimulator(
        pty_uart.fileno(),
        state,
        trace=_trace_simulator(trace),
    )
    simulator.auto_respond = False
    simulator.start()
    try:
        await simulator.wait_for_frame(CASES[0].is_discovery_request, timeout=10)
        foreign_state = bytes.fromhex("02 00 00 01 10 00 1a ff ff 2b")
        await simulator.write(
            foreign_state + simulator.encode_discovery_response()
        )
        await simulator.wait_for_frame(CASES[0].is_state_query, timeout=2)

        climates = await native_api.wait_for_climate_entities(timeout=2)
        assert len(climates) == 1
        assert climates[0].object_id.endswith("1_1")
        host_process.assert_running()
    finally:
        await native_api.disconnect()
        await simulator.stop()


@pytest.mark.asyncio
async def test_zhonghong_accepts_64_unit_discovery_response(
    pty_uart: PtyUart,
    host_process: HostProcess,
    native_api: NativeApiAdapter,
    trace: JsonlTrace,
) -> None:
    states = {
        (2, address): ClimateState(address=address)
        for address in range(1, 65)
    }
    simulator = ZhonghongSimulator(
        pty_uart.fileno(),
        states,
        trace=_trace_simulator(trace),
    )
    simulator.auto_respond = False
    simulator.start()
    try:
        await simulator.wait_for_frame(CASES[2].is_discovery_request, timeout=10)
        discovery_response = simulator.encode_discovery_response()
        assert discovery_response[3] == 64
        await simulator.write(discovery_response)
        await simulator.wait_for_frame(CASES[2].is_state_query, timeout=2)

        climates = await native_api.wait_for_climate_entities(
            expected_count=32, timeout=2
        )

        assert len({climate.key for climate in climates}) == 32
        host_process.assert_running()
    finally:
        await native_api.disconnect()
        await simulator.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [25, 26, 64])
@pytest.mark.parametrize("query_type", [0x0F, 0xFF], ids=["multi", "all"])
async def test_zhonghong_accepts_large_state_response(
    count: int,
    query_type: int,
    pty_uart: PtyUart,
    host_process: HostProcess,
    native_api: NativeApiAdapter,
    trace: JsonlTrace,
) -> None:
    states = {
        (2, address): ClimateState(
            address=address,
            power=True,
            mode=ClimateMode.COOL,
            target_temperature=22,
            current_temperature=31,
        )
        for address in range(1, count + 1)
    }
    simulator = ZhonghongSimulator(
        pty_uart.fileno(), states, trace=_trace_simulator(trace)
    )
    simulator.auto_respond = False
    simulator.start()
    try:
        await simulator.wait_for_frame(CASES[2].is_discovery_request, timeout=10)
        await simulator.write(simulator.encode_discovery_response())
        await simulator.wait_for_frame(CASES[2].is_state_query, timeout=2)
        climates = await native_api.wait_for_climate_entities(
            expected_count=min(count, 32), timeout=2
        )

        records = b"".join(
            simulator.encode_state_response(outdoor, indoor)[4:-1]
            for outdoor, indoor in sorted(states)
        )
        response = simulator.with_checksum(
            bytes((1, 0x50, query_type, count)) + records
        )
        assert len(response) == 5 + count * 10
        await simulator.write(response)
        for climate in climates:
            await native_api.wait_for_state(
                lambda value, key=climate.key: _is_climate_state(value, key)
                and value.current_temperature == pytest.approx(31),
                timeout=2,
                description=f"{count}-record Zhonghong state response",
            )
        simulator.clear_queues()
        await simulator.wait_for_frame(
            lambda frame: len(frame) == 7 and frame[1:4] == b"\x50\x01\x01",
            timeout=2,
        )
        host_process.assert_running()
    finally:
        await native_api.disconnect()
        await simulator.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        bytes.fromhex("01 50 02 03 02 01 01 31 01 01 01 35 01 c4"),
        bytes.fromhex("01 50 02 03 00 02 01 31 00 01 00 33 01 bf"),
    ],
    ids=["power-on-ack", "power-off-ack"],
)
@pytest.mark.parametrize("fragment_sizes", [None, (12, 2)], ids=["whole", "split"])
async def test_zhonghong_preserves_discovery_containing_ack(
    response: bytes,
    fragment_sizes: tuple[int, ...] | None,
    pty_uart: PtyUart,
    host_process: HostProcess,
    native_api: NativeApiAdapter,
    trace: JsonlTrace,
) -> None:
    addresses = [tuple(response[offset:offset + 2]) for offset in range(4, 13, 3)]
    states = {
        (outdoor, indoor): ClimateState(address=indoor)
        for outdoor, indoor in addresses
    }
    simulator = ZhonghongSimulator(
        pty_uart.fileno(), states, trace=_trace_simulator(trace)
    )
    simulator.auto_respond = False
    simulator.start()
    try:
        await simulator.wait_for_frame(CASES[2].is_discovery_request, timeout=10)
        assert response == simulator.with_checksum(response[:-1])
        assert response[6:12] == simulator.with_checksum(response[6:11])
        await simulator.write(
            response,
            fragment_sizes=fragment_sizes,
            inter_fragment_delay=0.02,
        )
        for outdoor, indoor in addresses:
            await simulator.wait_for_frame(
                lambda frame, address=bytes((outdoor, indoor)): len(frame) == 7
                and frame[1:4] == b"\x50\x01\x01"
                and frame[4:6] == address,
                timeout=2,
            )
        indoor_addresses = {indoor for _outdoor, indoor in addresses}
        climates = await native_api.wait_for_climate_entities(
            expected_count=len(indoor_addresses), timeout=2
        )
        assert {climate.object_id for climate in climates} == {
            f"1_{indoor}" for indoor in indoor_addresses
        }
        host_process.assert_running()
    finally:
        await native_api.disconnect()
        await simulator.stop()


@pytest.mark.asyncio
async def test_zhonghong_recovers_incomplete_frame_after_uart_gap(
    pty_uart: PtyUart,
    host_process: HostProcess,
    native_api: NativeApiAdapter,
    trace: JsonlTrace,
) -> None:
    state = ClimateState(address=1, power=True)
    simulator = ZhonghongSimulator(
        pty_uart.fileno(),
        state,
        outdoor_address=2,
        trace=_trace_simulator(trace),
    )
    simulator.auto_respond = False
    simulator.start()
    try:
        await simulator.wait_for_frame(CASES[2].is_discovery_request, timeout=10)
        await simulator.write(bytes.fromhex("01 50 02 20"))
        await asyncio.sleep(0.02)
        os.kill(host_process.pid, signal.SIGSTOP)
        try:
            await asyncio.sleep(0.15)
            await simulator.write(simulator.encode_discovery_response())
        finally:
            os.kill(host_process.pid, signal.SIGCONT)
        await simulator.wait_for_frame(CASES[2].is_state_query, timeout=2)

        climates = await native_api.wait_for_climate_entities(timeout=2)
        assert len(climates) == 1
        assert climates[0].object_id.endswith("1_1")
        host_process.assert_running()
    finally:
        await native_api.disconnect()
        await simulator.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
async def test_protocol_discovery_reboot_api_state_and_control(
    case: ProtocolCase,
    pty_uart: PtyUart,
    host_process: HostProcess,
    native_api: NativeApiAdapter,
    trace: JsonlTrace,
) -> None:
    from aioesphomeapi import ClimateFanMode as ApiClimateFanMode
    from aioesphomeapi import ClimateMode as ApiClimateMode

    state = ClimateState(
        address=1,
        power=False,
        mode=ClimateMode.COOL,
        fan_mode=FanMode.MEDIUM,
        target_temperature=22,
        current_temperature=25,
    )
    simulator = case.create_simulator(
        pty_uart.fileno(),
        state,
        _trace_simulator(trace),
    )
    simulator.auto_respond = False
    simulator.start()
    try:
        first_pid = host_process.pid
        await simulator.wait_for_frame(case.is_discovery_request, timeout=10)

        discovery_response = simulator.encode_discovery_response()  # type: ignore[attr-defined]
        await simulator.inject_noise(b"\x00\xff\x55", fragment_sizes=1)
        await asyncio.sleep(0.1)
        await native_api.connect(timeout=2)
        assert await native_api.climate_entities() == []
        await native_api.disconnect()

        await simulator.write(
            discovery_response,
            fragment_sizes=(1, 2, 3),
            inter_fragment_delay=0.005,
        )
        initial_response = simulator.encode_state_response()  # type: ignore[attr-defined]
        await simulator.wait_for_frame(case.is_state_query, timeout=2)
        await native_api.connect(timeout=2)
        first_boot_climates = await native_api.wait_for_climate_entities(timeout=2)
        await simulator.write(
            initial_response,
            fragment_sizes=(1, 2, 3),
            inter_fragment_delay=0.005,
        )
        assert len(first_boot_climates) == 1
        first_boot_climate = first_boot_climates[0]
        assert first_boot_climate.object_id.endswith("1_1")
        await native_api.wait_for_state(
            lambda value: _is_climate_state(value, first_boot_climate.key)
            and value.current_temperature == pytest.approx(25),
            timeout=2,
            description=f"{case.name} first-boot climate state",
        )

        state.current_temperature = 31
        updated_response = simulator.encode_state_response()  # type: ignore[attr-defined]
        simulator.clear_queues()
        await simulator.inject_bad_frame(updated_response, index=-1)
        await simulator.wait_for_frame_sequence(
            [case.is_state_query, case.is_state_query],
            timeout=2,
        )
        assert all(
            getattr(value, "current_temperature", None) != pytest.approx(31)
            for value in native_api.latest_states.values()
        )
        await simulator.write(
            updated_response,
            fragment_sizes=(1, 2, 3),
            inter_fragment_delay=0.005,
        )
        await native_api.wait_for_state(
            lambda value: _is_climate_state(value, first_boot_climate.key)
            and value.current_temperature == pytest.approx(31),
            timeout=2,
            description=f"{case.name} recovery after invalid response",
        )
        state.current_temperature = 25
        assert await host_process.wait_for_exit(timeout=10) == 0
        await native_api.disconnect()

        await simulator.reset_transport()
        pty_uart.drain()
        simulator.auto_respond = True
        host_process.restart()
        simulator.resume_reader()
        assert host_process.pid != first_pid
        await simulator.wait_for_frame(case.is_discovery_request, timeout=10)
        await simulator.wait_for_frame(case.is_state_query, timeout=2)

        await native_api.connect(timeout=10)
        climates = await native_api.climate_entities()
        assert len(climates) == 1
        climate = climates[0]
        assert climate.key
        assert climate.object_id.endswith("1_1")
        assert ApiClimateMode.COOL in climate.supported_modes
        assert ApiClimateMode.HEAT in climate.supported_modes

        initial_state = await native_api.wait_for_state(
            lambda value: _is_climate_state(value, climate.key)
            and value.mode == ApiClimateMode.OFF
            and value.target_temperature == pytest.approx(22)
            and value.current_temperature == pytest.approx(25),
            timeout=10,
            description=f"{case.name} initial climate state",
        )
        assert initial_state.key == climate.key

        heat_sequence = [case.is_heat_control]
        if case.is_power_on_control is not None:
            heat_sequence.append(case.is_power_on_control)
        controls = (
            (
                {"mode": ApiClimateMode.HEAT},
                heat_sequence,
                {"mode": ApiClimateMode.HEAT},
            ),
            (
                {"target_temperature": 23.0},
                [case.is_temperature_control],
                {"target_temperature": pytest.approx(23)},
            ),
            (
                {"fan_mode": ApiClimateFanMode.HIGH},
                [case.is_high_fan_control],
                {"fan_mode": ApiClimateFanMode.HIGH},
            ),
            (
                {"mode": ApiClimateMode.OFF},
                [case.is_off_control],
                {"mode": ApiClimateMode.OFF},
            ),
        )
        for index, (command, frame_predicates, expected) in enumerate(controls):
            await native_api.climate_command(climate.key, **command)
            await simulator.wait_for_frame_sequence(
                frame_predicates,
                timeout=10,
            )

            expected_current_temperature = 26 + index
            state.current_temperature = expected_current_temperature
            controlled_state = await native_api.wait_for_state(
                lambda value, expected=expected, temperature=expected_current_temperature: (
                    _is_climate_state(value, climate.key)
                    and value.current_temperature == pytest.approx(temperature)
                    and all(
                        getattr(value, name) == expected_value
                        for name, expected_value in expected.items()
                    )
                ),
                timeout=10,
                description=f"{case.name} state after {next(iter(command))}",
            )
            assert controlled_state.current_temperature == pytest.approx(
                expected_current_temperature
            )

        assert state.power is False
        assert state.mode == ClimateMode.HEAT
        assert state.target_temperature == 23
        assert state.fan_mode == FanMode.HIGH
        host_process.assert_running()
    finally:
        await native_api.disconnect()
        await simulator.stop()
