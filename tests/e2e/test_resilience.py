"""Parser resilience tests for fragmented, noisy, and corrupt VRF traffic."""

from __future__ import annotations

import os
from collections.abc import Callable

import pytest

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

SimulatorFactory = Callable[[ClimateState, Callable[[TraceEvent], None]], VrfSimulator]


@pytest.mark.parametrize(
    ("simulator_factory", "valid_frame"),
    [
        pytest.param(
            lambda state, trace: DemrySimulator(-1, state, trace=trace),
            bytes.fromhex("01 aa ff ff ff ff ff ff ff a4"),
            id="demry",
        ),
        pytest.param(
            lambda state, trace: SochuangSimulator(-1, state, trace=trace),
            bytes.fromhex("01 00 0c 01 00 00 00 00 00 00 31 57"),
            id="sochuang",
        ),
        pytest.param(
            lambda state, trace: ZhonghongSimulator(
                -1, state, outdoor_address=2, trace=trace
            ),
            bytes.fromhex("01 50 02 ff ff ff 50"),
            id="zhonghong",
        ),
    ],
)
def test_parser_recovers_from_noise_bad_frame_and_fragmentation(
    simulator_factory: SimulatorFactory,
    valid_frame: bytes,
) -> None:
    events: list[TraceEvent] = []
    state = ClimateState(
        address=1,
        power=True,
        mode=ClimateMode.COOL,
        fan_mode=FanMode.MEDIUM,
        target_temperature=24,
        current_temperature=25,
    )
    simulator = simulator_factory(state, events.append)
    bad_frame = bytearray(valid_frame)
    bad_frame[-1] ^= 0x01

    assert simulator.feed_bytes(b"\x99\x00" + bad_frame) == []
    assert simulator.frame_queue.empty()
    assert simulator.response_queue.empty()

    split_points = (1, len(valid_frame) // 2, len(valid_frame) - 1)
    offset = 0
    for split_point in split_points:
        assert simulator.feed_bytes(valid_frame[offset:split_point]) == []
        offset = split_point
    assert simulator.feed_bytes(valid_frame[offset:]) == [valid_frame]

    assert simulator.frame_queue.get_nowait() == valid_frame
    assert not simulator.response_queue.empty()
    assert simulator.rx_buffer == bytearray()
    assert any("mismatch" in event.note for event in events)
    assert any(event.note == "frame accepted" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "simulator_type",
    [
        pytest.param(DemrySimulator, id="demry"),
        pytest.param(SochuangSimulator, id="sochuang"),
        pytest.param(ZhonghongSimulator, id="zhonghong"),
    ],
)
async def test_response_fault_injection_preserves_requested_bytes(
    simulator_type: type[VrfSimulator],
) -> None:
    read_fd, write_fd = os.pipe()
    simulator = simulator_type(write_fd)
    try:
        response = simulator.encode_state_response()  # type: ignore[attr-defined]
        bad = await simulator.inject_bad_frame(
            response,
            index=-1,
            xor=0x80,
            fragment_sizes=(1, 2, 3),
        )
        assert os.read(read_fd, len(bad)) == bad
        assert bad[:-1] == response[:-1]
        assert bad[-1] == response[-1] ^ 0x80

        await simulator.inject_noise(b"\x00\xff\x55", fragment_sizes=1)
        assert os.read(read_fd, 3) == b"\x00\xff\x55"
    finally:
        os.close(read_fd)
        os.close(write_fd)
