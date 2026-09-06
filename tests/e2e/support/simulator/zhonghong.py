"""Zhonghong VRF protocol simulator."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .base import TraceCallback, VrfSimulator
from .checksum import additive_checksum
from .model import ClimateMode, ClimateState, FanMode

HOST_FRAME_LENGTH = 7
FUNC_SWITCH = 0x31
FUNC_TEMPERATURE = 0x32
FUNC_MODE = 0x33
FUNC_FAN = 0x34
FUNC_QUERY = 0x50
QUERY_SINGLE = 0x01
QUERY_ONLINE = 0x02
_VALID_FUNCTIONS = {FUNC_SWITCH, FUNC_TEMPERATURE, FUNC_MODE, FUNC_FAN, FUNC_QUERY}

_MODE_TO_WIRE = {
    ClimateMode.COOL: 0x01,
    ClimateMode.DRY: 0x02,
    ClimateMode.FAN_ONLY: 0x04,
    ClimateMode.HEAT: 0x08,
}
_MODE_FROM_WIRE = {value: key for key, value in _MODE_TO_WIRE.items()}
_FAN_TO_WIRE = {
    FanMode.LOW: 0x04,
    FanMode.MEDIUM: 0x02,
    FanMode.HIGH: 0x01,
}
_FAN_FROM_WIRE = {value: key for key, value in _FAN_TO_WIRE.items()}

ZhonghongAddress = tuple[int, int]
ZhonghongStates = (
    ClimateState
    | Iterable[ClimateState]
    | Mapping[ZhonghongAddress, ClimateState]
    | None
)


def _u8_temperature(value: float) -> int:
    return max(0, min(0xFF, int(value + 0.5)))


class ZhonghongSimulator(VrfSimulator):
    """Simulate seven-byte host requests and variable query responses.

    ``states`` may be a normal ClimateState iterable for one outdoor unit, or a
    mapping keyed by ``(outdoor_address, indoor_address)`` when indoor addresses
    overlap across multiple outdoor units.
    """

    def __init__(
        self,
        master_fd: int,
        states: ZhonghongStates = None,
        *,
        slave_address: int = 1,
        outdoor_address: int = 0,
        outdoor_addresses: Mapping[int, int] | None = None,
        trace: TraceCallback | None = None,
    ) -> None:
        # Zhonghong uses a composite identity, so bypass the base class's
        # single-byte state registration and populate the mapping below.
        super().__init__(master_fd, (), trace=trace)
        self.slave_address = int(slave_address) & 0xFF
        self.outdoor_address = int(outdoor_address) & 0xFF
        self.outdoor_addresses = {
            int(indoor) & 0xFF: int(outdoor) & 0xFF
            for indoor, outdoor in (outdoor_addresses or {}).items()
        }
        self.states: dict[ZhonghongAddress, ClimateState] = {}

        if states is None:
            self.add_state(ClimateState(), outdoor_address=self.outdoor_address)
        elif isinstance(states, Mapping):
            for address, state in states.items():
                if not isinstance(address, tuple) or len(address) != 2:
                    raise TypeError(
                        "Zhonghong state mapping keys must be (outdoor, indoor)"
                    )
                self.add_state(
                    state,
                    outdoor_address=address[0],
                    indoor_address=address[1],
                )
        elif isinstance(states, ClimateState):
            self.add_state(states)
        else:
            for state in states:
                self.add_state(state)

    @property
    def state(self) -> ClimateState:
        if not self.states:
            raise LookupError("simulator has no climate states")
        return self.states[min(self.states)]

    def add_state(
        self,
        state: ClimateState,
        *,
        outdoor_address: int | None = None,
        indoor_address: int | None = None,
    ) -> ClimateState:
        """Add or replace one unit under its composite Zhonghong address."""

        if not isinstance(state, ClimateState):
            raise TypeError("state must be a ClimateState")
        indoor = state.address if indoor_address is None else int(indoor_address)
        if state.address != indoor:
            raise ValueError("ClimateState.address must match the indoor address")
        outdoor = (
            self.outdoor_addresses.get(indoor, self.outdoor_address)
            if outdoor_address is None
            else int(outdoor_address)
        )
        if not 0 <= outdoor <= 0xFF or not 0 <= indoor <= 0xFF:
            raise ValueError("Zhonghong addresses must fit in one byte")
        self.states[(outdoor, indoor)] = state
        return state

    def get_state(
        self, address: int | ZhonghongAddress
    ) -> ClimateState | None:
        """Look up a composite address, or an unambiguous indoor address."""

        if isinstance(address, tuple):
            if len(address) != 2:
                raise ValueError("Zhonghong address must contain two bytes")
            return self.states.get((int(address[0]), int(address[1])))
        matches = [
            state for (_outdoor, indoor), state in self.states.items()
            if indoor == int(address)
        ]
        if len(matches) > 1:
            raise LookupError(
                f"indoor address {address} exists under multiple outdoor units"
            )
        return matches[0] if matches else None

    @staticmethod
    def with_checksum(payload: bytes | bytearray) -> bytes:
        data = bytes(payload)
        return data + bytes((additive_checksum(data),))

    def outdoor_for(self, indoor_address: int) -> int:
        """Return the sole outdoor address for an indoor address."""

        matches = [
            outdoor for outdoor, indoor in self.states if indoor == indoor_address
        ]
        if len(matches) > 1:
            raise LookupError(
                f"indoor address {indoor_address} exists under multiple outdoor units"
            )
        if matches:
            return matches[0]
        return self.outdoor_addresses.get(indoor_address, self.outdoor_address)

    def extract_frame(self) -> bytes | None:
        while len(self.rx_buffer) >= HOST_FRAME_LENGTH:
            if self.rx_buffer[0] != self.slave_address:
                self.discard_noise(1, note="Zhonghong slave mismatch")
                continue
            if self.rx_buffer[1] not in _VALID_FUNCTIONS:
                self.discard_noise(1, note="Zhonghong function mismatch")
                continue
            candidate = bytes(self.rx_buffer[:HOST_FRAME_LENGTH])
            if additive_checksum(candidate[:-1]) != candidate[-1]:
                self.discard_noise(1, note="Zhonghong checksum mismatch")
                continue
            del self.rx_buffer[:HOST_FRAME_LENGTH]
            return candidate
        return None

    def handle_frame(self, frame: bytes) -> bytes | None:
        function = frame[1]
        if function == FUNC_QUERY:
            if frame[2] == QUERY_ONLINE:
                return self.encode_discovery_response()
            if frame[2] == QUERY_SINGLE:
                return self.encode_state_response(frame[4], frame[5])
            return None

        state = self.find_state(frame[4], frame[5])
        if state is not None and state.online:
            self.apply_control(frame, state)
        # The C++ receiver expects six-byte control acknowledgements, while the
        # host commands are seven bytes. State is verified by the next query.
        return None

    def find_state(self, outdoor_address: int, indoor_address: int) -> ClimateState | None:
        return self.states.get((int(outdoor_address), int(indoor_address)))

    def encode_discovery_response(self) -> bytes:
        records = bytearray()
        for (outdoor, indoor), state in sorted(self.states.items()):
            if state.online:
                records.extend((outdoor, indoor, 0x01))
        payload = bytes(
            (self.slave_address, FUNC_QUERY, QUERY_ONLINE, len(records) // 3)
        ) + bytes(records)
        return self.with_checksum(payload)

    def encode_state_response(
        self,
        outdoor_address: int | None = None,
        indoor_address: int | None = None,
    ) -> bytes:
        """Encode zero or one ten-byte state records."""

        if indoor_address is None:
            if not self.states:
                raise LookupError("simulator has no climate states")
            (outdoor_address, indoor_address), state = min(self.states.items())
        else:
            outdoor_address = (
                self.outdoor_for(indoor_address)
                if outdoor_address is None
                else int(outdoor_address)
            )
            state = self.find_state(outdoor_address, indoor_address)

        records = bytearray()
        if state is not None and state.online:
            mode = _MODE_TO_WIRE.get(state.mode, _MODE_TO_WIRE[ClimateMode.COOL])
            fan = _FAN_TO_WIRE.get(state.fan_mode, _FAN_TO_WIRE[FanMode.LOW])
            records.extend(
                (
                    outdoor_address,
                    indoor_address,
                    int(state.power),
                    _u8_temperature(state.target_temperature),
                    mode,
                    fan,
                    _u8_temperature(state.current_temperature),
                    0,
                    0,
                    0,
                )
            )
        payload = bytes(
            (self.slave_address, FUNC_QUERY, QUERY_SINGLE, len(records) // 10)
        ) + bytes(records)
        return self.with_checksum(payload)

    def apply_control(
        self, frame: bytes, state: ClimateState | None = None
    ) -> ClimateState:
        if len(frame) != HOST_FRAME_LENGTH:
            raise ValueError("Zhonghong host frame must be 7 bytes")
        state = state or self.find_state(frame[4], frame[5])
        if state is None:
            raise KeyError(f"unknown Zhonghong unit {frame[4]}:{frame[5]}")
        function, value = frame[1], frame[2]
        changes: dict[str, object] = {}
        if function == FUNC_SWITCH:
            changes["power"] = value == 0x01
        elif function == FUNC_TEMPERATURE:
            changes["target_temperature"] = float(value)
        elif function == FUNC_MODE and value in _MODE_FROM_WIRE:
            changes["mode"] = _MODE_FROM_WIRE[value]
        elif function == FUNC_FAN and value in _FAN_FROM_WIRE:
            changes["fan_mode"] = _FAN_FROM_WIRE[value]
        return state.update(**changes)
