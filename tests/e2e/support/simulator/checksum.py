"""Checksum helpers for the supported VRF wire protocols."""

from __future__ import annotations

from collections.abc import Iterable

BytesLike = bytes | bytearray | memoryview


def additive_checksum(data: Iterable[int] | BytesLike, *, initial: int = 0) -> int:
    """Return the low byte of the additive sum of *data*."""

    return (initial + sum(data)) & 0xFF


def has_additive_checksum(frame: BytesLike, *, checksum_index: int = -1) -> bool:
    """Check an additive checksum stored at *checksum_index*.

    The checksum byte itself is omitted from the sum, so this also supports
    protocols whose checksum is not the final byte.
    """

    payload = bytes(frame)
    if not payload:
        return False
    index = checksum_index if checksum_index >= 0 else len(payload) + checksum_index
    if not 0 <= index < len(payload):
        return False
    return additive_checksum(payload[:index] + payload[index + 1 :]) == payload[index]


def modbus_crc16(data: Iterable[int] | BytesLike, *, initial: int = 0xFFFF) -> int:
    """Return Modbus CRC-16 (polynomial 0xA001) as an integer."""

    crc = initial & 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def append_modbus_crc(data: BytesLike, *, byteorder: str = "little") -> bytes:
    """Append a Modbus CRC in the requested wire byte order."""

    if byteorder not in {"little", "big"}:
        raise ValueError("byteorder must be 'little' or 'big'")
    payload = bytes(data)
    return payload + modbus_crc16(payload).to_bytes(2, byteorder)


def has_modbus_crc(frame: BytesLike, *, byteorder: str = "little") -> bool:
    """Validate the trailing two-byte Modbus CRC."""

    if len(frame) < 2 or byteorder not in {"little", "big"}:
        return False
    expected = int.from_bytes(frame[-2:], byteorder)
    return modbus_crc16(frame[:-2]) == expected
