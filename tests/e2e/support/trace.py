"""Line-oriented trace recording for reproducible E2E failures."""

from __future__ import annotations

import json
import threading
import time
from enum import Enum
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"hex": value.hex(), "length": len(value)}
    if isinstance(value, bytearray):
        return {"hex": bytes(value).hex(), "length": len(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


class JsonlTrace:
    """Write timestamped events as immediately flushed JSON Lines records."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._started_at = time.monotonic()
        self._lock = threading.Lock()
        self._stream: TextIO | None = self.path.open("w", encoding="utf-8")

    def record(self, event: str, **fields: Any) -> None:
        record = {
            "elapsed_s": round(time.monotonic() - self._started_at, 6),
            "event": event,
            **{key: _json_value(value) for key, value in fields.items()},
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with self._lock:
            stream = self._stream
            if stream is None:
                raise RuntimeError("trace is closed")
            stream.write(line)
            stream.write("\n")
            stream.flush()

    emit = record

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.flush()
                self._stream.close()
                self._stream = None

    def __enter__(self) -> JsonlTrace:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()
