"""Demry VRF protocol simulator."""

from __future__ import annotations

from collections.abc import Iterable

from .base import TraceCallback, VrfSimulator
from .checksum import additive_checksum
from .model import ClimateMode, ClimateState, FanMode

FRAME_LENGTH = 10
DISCOVERY_MARKER = 0xAA
HOLD = 0xFF

_MODE_TO_WIRE = {
    ClimateMode.HEAT: 0x01,
    ClimateMode.COOL: 0x02,
    ClimateMode.FAN_ONLY: 0x04,
    ClimateMode.DRY: 0x08,
}
_MODE_FROM_WIRE = {value: key for key, value in _MODE_TO_WIRE.items()}
_FAN_TO_WIRE = {
    FanMode.AUTO: 0x00,
    FanMode.LOW: 0x01,
    FanMode.MEDIUM: 0x02,
    FanMode.HIGH: 0x03,
}
_FAN_FROM_WIRE = {value: key for key, value in _FAN_TO_WIRE.items()}


def _u8_temperature(value: float) -> int:
    return max(0, min(0xFE, int(value + 0.5)))


class DemrySimulator(VrfSimulator):
    """Simulate the 10-byte Demry gateway protocol."""

    def __init__(
        self,
        master_fd: int,
        states: ClimateState | Iterable[ClimateState] | None = None,
        *,
        slave_address: int = 1,
        trace: TraceCallback | None = None,
        respond_to_controls: bool = True,
    ) -> None:
        super().__init__(master_fd, states, trace=trace)
        self.slave_address = int(slave_address) & 0xFF
        self.respond_to_controls = respond_to_controls

    @staticmethod
    def with_checksum(payload: bytes | bytearray) -> bytes:
        """Append the Demry additive checksum to a nine-byte payload."""

        if len(payload) != FRAME_LENGTH - 1:
            raise ValueError("Demry payload must be exactly 9 bytes")
        data = bytes(payload)
        return data + bytes((additive_checksum(data),))

    def extract_frame(self) -> bytes | None:
        while len(self.rx_buffer) >= FRAME_LENGTH:
            candidate = bytes(self.rx_buffer[:FRAME_LENGTH])
            if additive_checksum(candidate[:-1]) != candidate[-1]:
                self.discard_noise(1, note="Demry checksum mismatch")
                continue
            if candidate[0] != self.slave_address:
                self.discard_noise(
                    FRAME_LENGTH, note="Demry frame for another slave"
                )
                continue
            del self.rx_buffer[:FRAME_LENGTH]
            return candidate
        return None

    def handle_frame(self, frame: bytes) -> bytes | None:
        if frame[1] == DISCOVERY_MARKER:
            return self.encode_discovery_response()

        state = self.get_state(frame[1])
        if state is None or not state.online:
            return None

        if all(value == HOLD for value in frame[2:9]):
            return self.encode_state_response(state)

        self.apply_control(frame, state)
        return self.encode_state_response(state) if self.respond_to_controls else None

    def encode_discovery_response(self) -> bytes:
        """Encode the four-byte indoor-unit bitmap used by Demry."""

        bitmap = [0, 0, 0, 0]
        for address, state in self.states.items():
            if state.online and 0 <= address < 32:
                byte_index = 3 - address // 8
                bitmap[byte_index] |= 1 << (address % 8)
        payload = bytes(
            (self.slave_address, DISCOVERY_MARKER, HOLD, HOLD, HOLD, *bitmap)
        )
        return self.with_checksum(payload)

    def encode_state_response(self, state: ClimateState | int | None = None) -> bytes:
        """Encode one indoor unit's current state."""

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
                state.address,
                int(state.power),
                mode,
                _u8_temperature(state.target_temperature),
                fan,
                _u8_temperature(state.current_temperature),
                HOLD,
                HOLD,
            )
        )
        return self.with_checksum(payload)

    def apply_control(
        self, frame: bytes, state: ClimateState | None = None
    ) -> ClimateState:
        """Apply non-HOLD fields from a Demry control frame."""

        if len(frame) != FRAME_LENGTH:
            raise ValueError("Demry control frame must be 10 bytes")
        state = state or self.get_state(frame[1])
        if state is None:
            raise KeyError(f"unknown indoor address {frame[1]}")
        changes: dict[str, object] = {}
        if frame[2] != HOLD:
            changes["power"] = frame[2] == 0x01
        if frame[3] != HOLD and frame[3] in _MODE_FROM_WIRE:
            changes["mode"] = _MODE_FROM_WIRE[frame[3]]
        if frame[4] != HOLD:
            changes["target_temperature"] = float(frame[4])
        if frame[5] != HOLD and frame[5] in _FAN_FROM_WIRE:
            changes["fan_mode"] = _FAN_FROM_WIRE[frame[5]]
        return state.update(**changes)
