"""Raw pseudo-terminal management for the host UART."""

from __future__ import annotations

import errno
import os
import pty
import select
import termios
import time
import tty
import uuid
from pathlib import Path

from .trace import JsonlTrace


class PtyUart:
    """A per-test raw PTY exposed through a compile-time-stable symlink."""

    def __init__(self, stable_path: Path, trace: JsonlTrace | None = None) -> None:
        self.stable_path = Path(stable_path)
        self.trace = trace
        self.master_fd = -1
        self.slave_fd = -1
        self.slave_path: Path | None = None
        self._closed = True
        try:
            self.master_fd, self.slave_fd = pty.openpty()
            tty.setraw(self.master_fd)
            tty.setraw(self.slave_fd)
            os.set_blocking(self.master_fd, False)
            self.slave_path = Path(os.ttyname(self.slave_fd))
            self._install_symlink()
            os.close(self.slave_fd)
            self.slave_fd = -1
            self._closed = False
            self._record("pty.open", slave_path=self.slave_path)
        except BaseException:
            self._closed = True
            self._remove_symlink()
            self._close_descriptors()
            raise

    def _install_symlink(self) -> None:
        if self.slave_path is None:
            raise RuntimeError("PTY slave path is unavailable")
        self.stable_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.stable_path.with_name(
            f".{self.stable_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temporary_path.symlink_to(self.slave_path)
            os.replace(temporary_path, self.stable_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _record(self, event: str, **fields: object) -> None:
        if self.trace is not None:
            self.trace.record(event, **fields)

    def fileno(self) -> int:
        if self._closed:
            raise RuntimeError("PTY is closed")
        return self.master_fd

    def drain(self) -> int:
        """Discard residual bytes before starting another host generation."""

        if self._closed:
            raise RuntimeError("PTY is closed")
        try:
            termios.tcflush(self.master_fd, termios.TCIOFLUSH)
        except OSError as error:
            if error.errno != errno.EIO:
                raise
        discarded = 0
        while True:
            try:
                discarded += len(os.read(self.master_fd, 4096))
            except BlockingIOError:
                break
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
        self._record("pty.drain", discarded=discarded)
        return discarded

    def read(self, max_bytes: int = 4096) -> bytes:
        if self._closed:
            raise RuntimeError("PTY is closed")
        try:
            data = os.read(self.master_fd, max_bytes)
        except BlockingIOError:
            return b""
        except OSError as error:
            if error.errno == errno.EIO:
                return b""
            raise
        if data:
            self._record("uart.host_to_peer", data=data)
        return data

    def write(self, data: bytes, timeout: float = 1.0) -> int:
        """Write the complete frame, waiting on backpressure up to *timeout*."""
        if self._closed:
            raise RuntimeError("PTY is closed")
        deadline = time.monotonic() + timeout
        view = memoryview(data)
        written = 0
        while written < len(view):
            try:
                written += os.write(self.master_fd, view[written:])
                continue
            except BlockingIOError:
                pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Timed out after {timeout:.3f}s writing to PTY"
                )
            select.select([], [self.master_fd], [], remaining)
        self._record("uart.peer_to_host", data=data)
        return written

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._record("pty.close")
        finally:
            self._remove_symlink()
            self._close_descriptors()

    def _close_descriptors(self) -> None:
        for descriptor in (self.master_fd, self.slave_fd):
            if descriptor < 0:
                continue
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.master_fd = -1
        self.slave_fd = -1

    def _remove_symlink(self) -> None:
        if self.slave_path is None:
            return
        try:
            if self.stable_path.is_symlink() and (
                self.stable_path.resolve(strict=False) == self.slave_path
            ):
                self.stable_path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> PtyUart:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()
