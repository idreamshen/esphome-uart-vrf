"""Protocol-independent climate state used by the VRF simulators."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any


class ClimateMode(str, Enum):
    """Operating modes shared by all supported VRF protocols."""

    OFF = "off"
    AUTO = "auto"
    COOL = "cool"
    HEAT = "heat"
    DRY = "dry"
    FAN_ONLY = "fan_only"


class FanMode(str, Enum):
    """Fan speeds exposed by the simulator model."""

    AUTO = "auto"
    QUIET = "quiet"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SwingMode(str, Enum):
    """Swing modes exposed by the simulator model."""

    OFF = "off"
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"
    BOTH = "both"


def _coerce_enum(enum_type: type[Enum], value: Any) -> Any:
    if isinstance(value, enum_type):
        return value
    return enum_type(value)


@dataclass(slots=True)
class ClimateState:
    """Mutable, protocol-neutral state for one indoor unit."""

    address: int = 1
    power: bool = False
    mode: ClimateMode = ClimateMode.COOL
    fan_mode: FanMode = FanMode.AUTO
    swing_mode: SwingMode = SwingMode.OFF
    target_temperature: float = 24.0
    current_temperature: float = 25.0
    online: bool = True

    def __post_init__(self) -> None:
        self.address = int(self.address)
        if not 0 <= self.address <= 0xFF:
            raise ValueError("address must fit in one byte")
        self.power = bool(self.power)
        self.mode = _coerce_enum(ClimateMode, self.mode)
        self.fan_mode = _coerce_enum(FanMode, self.fan_mode)
        self.swing_mode = _coerce_enum(SwingMode, self.swing_mode)
        self.target_temperature = float(self.target_temperature)
        self.current_temperature = float(self.current_temperature)
        self.online = bool(self.online)

    @property
    def effective_mode(self) -> ClimateMode:
        """Return OFF when power is disabled, otherwise the stored mode."""

        return self.mode if self.power else ClimateMode.OFF

    def copy(self, **changes: Any) -> ClimateState:
        """Create a normalized copy with selected fields changed."""

        return replace(self, **changes)

    def update(self, **changes: Any) -> ClimateState:
        """Update known fields in place and normalize enum/numeric values."""

        unknown = set(changes).difference(self.__dataclass_fields__)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise TypeError(f"unknown climate state field(s): {names}")
        for name, value in changes.items():
            setattr(self, name, value)
        self.__post_init__()
        return self
