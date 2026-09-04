"""Python PTY simulators for end-to-end UART VRF tests."""

from __future__ import annotations

from typing import Any

from .base import FramePredicate, TraceCallback, TraceEvent, VrfSimulator
from .checksum import (
    additive_checksum,
    append_modbus_crc,
    has_additive_checksum,
    has_modbus_crc,
    modbus_crc16,
)
from .demry import DemrySimulator
from .model import ClimateMode, ClimateState, FanMode, SwingMode
from .sochuang import SochuangSimulator
from .zhonghong import ZhonghongAddress, ZhonghongSimulator, ZhonghongStates

SimulatorBase = VrfSimulator
SIMULATOR_TYPES: dict[str, type[VrfSimulator]] = {
    "demry": DemrySimulator,
    "zhonghong": ZhonghongSimulator,
    "sochuang": SochuangSimulator,
}


def create_simulator(protocol: str, master_fd: int, **kwargs: Any) -> VrfSimulator:
    """Create a simulator by its case-insensitive protocol name."""

    name = protocol.strip().lower()
    try:
        simulator_type = SIMULATOR_TYPES[name]
    except KeyError as exc:
        supported = ", ".join(sorted(SIMULATOR_TYPES))
        raise ValueError(f"unsupported VRF protocol {protocol!r}; choose {supported}") from exc
    return simulator_type(master_fd, **kwargs)


__all__ = [
    "ClimateMode",
    "ClimateState",
    "DemrySimulator",
    "FanMode",
    "FramePredicate",
    "SIMULATOR_TYPES",
    "SimulatorBase",
    "SochuangSimulator",
    "SwingMode",
    "TraceCallback",
    "TraceEvent",
    "VrfSimulator",
    "ZhonghongAddress",
    "ZhonghongSimulator",
    "ZhonghongStates",
    "additive_checksum",
    "append_modbus_crc",
    "create_simulator",
    "has_additive_checksum",
    "has_modbus_crc",
    "modbus_crc16",
]
