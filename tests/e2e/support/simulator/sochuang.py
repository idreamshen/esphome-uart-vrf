"""Sochuang VRF protocol simulator."""

from __future__ import annotations

from collections.abc import Iterable

from .base import TraceCallback, VrfSimulator
from .checksum import append_modbus_crc, has_modbus_crc
from .model import ClimateMode, ClimateState, FanMode

FRAME_LENGTH = 12
FUNC_QUERY_COUNT = 0x01
FUNC_QUERY_STATUS = 0x02
FUNC_SWITCH = 0x04
FUNC_MODE = 0x05
FUNC_TEMPERATURE = 0x06
FUNC_FAN = 0x07
_VALID_FUNCTIONS = {
    FUNC_QUERY_COUNT,
    FUNC_QUERY_STATUS,
    FUNC_SWITCH,
    FUNC_MODE,
    FUNC_TEMPERATURE,
    FUNC_FAN,
}

_MODE_TO_WIRE = {
    ClimateMode.COOL: 0x00,
    ClimateMode.HEAT: 0x01,
    ClimateMode.FAN_ONLY: 0x02,
    ClimateMode.DRY: 0x03,
}
_MODE_FROM_WIRE = {value: key for key, value in _MODE_TO_WIRE.items()}
_FAN_TO_WIRE = {
    FanMode.LOW: 0x00,
    FanMode.MEDIUM: 0x01,
    FanMode.HIGH: 0x02,
    FanMode.AUTO: 0x03,
}
_FAN_FROM_WIRE = {value: key for key, value in _FAN_TO_WIRE.items()}


def _u8_temperature(value: float) -> int:
    return max(0, min(0xFF, int(value + 0.5)))


class SochuangSimulator(VrfSimulator):
    """Simulate the fixed 12-byte Sochuang protocol."""

    def __init__(
        self,
        master_fd: int,
        states: ClimateState | Iterable[ClimateState] | None = None,
        *,
        slave_address: int = 1,
        unit_count: int | None = None,
        trace: TraceCallback | None = None,
        echo_controls: bool = False,
    ) -> None:
        super().__init__(master_fd, states, trace=trace)
        self.slave_address = int(slave_address) & 0xFF
        self.unit_count = None if unit_count is None else int(unit_count)
        if self.unit_count is not None and not 0 <= self.unit_count <= 32:
            raise ValueError("Sochuang unit_count must be between 0 and 32")
        self.echo_controls = echo_controls

    @staticmethod
    def with_crc(payload: bytes | bytearray) -> bytes:
        """Append Modbus CRC low byte then high byte to ten payload bytes."""

        if len(payload) != FRAME_LENGTH - 2:
            raise ValueError("Sochuang payload must be exactly 10 bytes")
        return append_modbus_crc(bytes(payload), byteorder="little")

    def extract_frame(self) -> bytes | None:
        while len(self.rx_buffer) >= FRAME_LENGTH:
            if self.rx_buffer[0] != self.slave_address:
                self.discard_noise(1, note="Sochuang slave mismatch")
                continue
            if self.rx_buffer[1:3] != b"\x00\x0c":
                self.discard_noise(1, note="Sochuang length marker mismatch")
                continue
            if self.rx_buffer[3] not in _VALID_FUNCTIONS:
                self.discard_noise(1, note="Sochuang function mismatch")
                continue
            candidate = bytes(self.rx_buffer[:FRAME_LENGTH])
            if not has_modbus_crc(candidate, byteorder="little"):
                self.discard_noise(1, note="Sochuang CRC mismatch")
                continue
            del self.rx_buffer[:FRAME_LENGTH]
            return candidate
        return None

    def handle_frame(self, frame: bytes) -> bytes | None:
        function = frame[3]
        if function == FUNC_QUERY_COUNT:
            return self.encode_discovery_response()
        if function == FUNC_QUERY_STATUS:
            state = self.get_state(frame[4])
            if state is not None and state.online:
                return self.encode_state_response(state)
            return None
        state = self.get_state(frame[4])
        if state is not None and state.online:
            self.apply_control(frame, state)
            return frame if self.echo_controls else None
        return None

    def discovery_count(self) -> int:
        """Return a count that cannot create unintended contiguous units."""

        addresses = sorted(self.states)
        if any(address < 1 or address > 32 for address in addresses):
            raise ValueError("Sochuang indoor addresses must be between 1 and 32")
        if self.unit_count is None:
            expected = list(range(1, len(addresses) + 1))
            if addresses != expected:
                raise ValueError(
                    "Sochuang discovery requires contiguous addresses starting at 1; "
                    "set unit_count explicitly for a partially modeled gateway"
                )
            return len(addresses)
        if any(address > self.unit_count for address in addresses):
            raise ValueError("Sochuang state address exceeds explicit unit_count")
        return self.unit_count

    def encode_discovery_response(self) -> bytes:
        count = self.discovery_count()
        payload = bytes(
            (self.slave_address, 0x00, FRAME_LENGTH, FUNC_QUERY_COUNT, count)
        ) + bytes(5)
        return self.with_crc(payload)

    def encode_state_response(self, state: ClimateState | int | None = None) -> bytes:
        if state is None:
            state = self.state
        elif isinstance(state, int):
            found = self.get_state(state)
            if found is None:
                raise KeyError(f"unknown indoor address {state}")
            state = found
        mode = _MODE_TO_WIRE.get(state.mode, _MODE_TO_WIRE[ClimateMode.COOL])
        fan = _FAN_TO_WIRE.get(state.fan_mode, _FAN_TO_WIRE[FanMode.LOW])
        payload = bytes(
            (
                self.slave_address,
                0x00,
                FRAME_LENGTH,
                FUNC_QUERY_STATUS,
                state.address,
                int(state.power),
                mode,
                _u8_temperature(state.target_temperature),
                fan,
                _u8_temperature(state.current_temperature),
            )
        )
        return self.with_crc(payload)

    def apply_control(
        self, frame: bytes, state: ClimateState | None = None
    ) -> ClimateState:
        if len(frame) != FRAME_LENGTH:
            raise ValueError("Sochuang frame must be 12 bytes")
        state = state or self.get_state(frame[4])
        if state is None:
            raise KeyError(f"unknown indoor address {frame[4]}")
        function, value = frame[3], frame[5]
        changes: dict[str, object] = {}
        if function == FUNC_SWITCH:
            changes["power"] = value == 0x01
        elif function == FUNC_MODE and value in _MODE_FROM_WIRE:
            changes["mode"] = _MODE_FROM_WIRE[value]
        elif function == FUNC_TEMPERATURE:
            changes["target_temperature"] = float(value)
        elif function == FUNC_FAN and value in _FAN_FROM_WIRE:
            changes["fan_mode"] = _FAN_FROM_WIRE[value]
        return state.update(**changes)
