"""Lifecycle management for the compiled ESPHome host process."""

from __future__ import annotations

import asyncio
import ipaddress
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import BinaryIO, Mapping

from .trace import JsonlTrace


class HostProcess:
    """Run the host binary in an isolated process group with captured logs."""

    def __init__(
        self,
        binary: Path,
        *,
        log_path: Path,
        preferences_dir: Path,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        api_host: str | None = None,
        api_port: int | None = None,
        trace: JsonlTrace | None = None,
    ) -> None:
        self.binary = Path(binary)
        self.log_path = Path(log_path)
        self.preferences_dir = Path(preferences_dir)
        self.cwd = Path(cwd) if cwd is not None else self.binary.parent
        self.extra_env = dict(env or {})
        self.api_host = api_host
        self.api_port = api_port
        if (api_host is None) != (api_port is None):
            raise ValueError("api_host and api_port must be provided together")
        self.trace = trace
        self.process: subprocess.Popen[bytes] | None = None
        self._log_stream: BinaryIO | None = None

    def start(self) -> HostProcess:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("host process is already running")
        self._close_log()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.preferences_dir.mkdir(parents=True, exist_ok=True)
        self._log_stream = self.log_path.open("ab")
        environment = os.environ.copy()
        environment.update(self.extra_env)
        environment["ESPHOME_PREFDIR"] = str(self.preferences_dir)
        try:
            self.process = subprocess.Popen(
                [str(self.binary)],
                cwd=self.cwd,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=self._log_stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except BaseException:
            self._log_stream.close()
            self._log_stream = None
            raise
        self._record("host.start", pid=self.process.pid, binary=self.binary)
        try:
            self._wait_for_owned_api_socket()
        except BaseException:
            self.stop()
            raise
        return self

    @property
    def pid(self) -> int:
        if self.process is None:
            raise RuntimeError("host process has not been started")
        return self.process.pid

    @property
    def returncode(self) -> int | None:
        return None if self.process is None else self.process.poll()

    def assert_running(self) -> None:
        returncode = self.returncode
        if self.process is None:
            raise RuntimeError("host process has not been started")
        if returncode is not None:
            raise RuntimeError(
                f"Host process exited with code {returncode}. Log: {self.log_path}"
            )

    def read_log(self) -> str:
        if self._log_stream is not None:
            self._log_stream.flush()
        if not self.log_path.exists():
            return ""
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def stop(self, timeout: float = 5.0) -> None:
        process = self.process
        if process is None:
            self._close_log()
            return
        try:
            if process.poll() is None:
                self._signal_group(signal.SIGTERM)
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    self._record("host.kill", pid=process.pid)
                    self._signal_group(signal.SIGKILL)
                    process.wait(timeout=timeout)
        finally:
            try:
                self._record(
                    "host.stop", pid=process.pid, returncode=process.returncode
                )
            finally:
                self._close_log()

    async def wait_for_exit(self, timeout: float = 5.0) -> int:
        """Wait for a normal host exit without blocking the simulator loop."""
        process = self.process
        if process is None:
            raise RuntimeError("host process has not been started")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while process.poll() is None:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"Host process did not exit after {timeout:.3f}s. "
                    f"Log: {self.log_path}"
                )
            await asyncio.sleep(min(0.05, remaining))
        return process.returncode

    def restart(self, timeout: float = 5.0) -> HostProcess:
        """Restart the binary while retaining this test's preference directory."""
        self.stop(timeout=timeout)
        return self.start()

    def _wait_for_owned_api_socket(self, timeout: float = 5.0) -> None:
        if self.api_host is None or self.api_port is None:
            return
        process = self.process
        if process is None:
            raise RuntimeError("host process has not been started")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            returncode = process.poll()
            if returncode is not None:
                raise RuntimeError(
                    f"Host process exited with code {returncode} before binding "
                    f"{self.api_host}:{self.api_port}. Log: {self.log_path}"
                )
            inode = self._listening_socket_inode(self.api_host, self.api_port)
            if inode is not None:
                if self._process_owns_socket(process.pid, inode):
                    self._record(
                        "host.api_owned",
                        pid=process.pid,
                        host=self.api_host,
                        port=self.api_port,
                    )
                    return
                raise RuntimeError(
                    f"API port {self.api_host}:{self.api_port} is owned by "
                    "another process"
                )
            time.sleep(0.02)
        raise TimeoutError(
            f"Host process did not bind {self.api_host}:{self.api_port} after "
            f"{timeout:.3f}s. Log: {self.log_path}"
        )

    @staticmethod
    def _listening_socket_inode(host: str, port: int) -> str | None:
        expected_address = ipaddress.ip_address(host)
        encoded_port = f"{port:04X}"
        tables = (
            (Path("/proc/net/tcp"), 4),
            (Path("/proc/net/tcp6"), 6),
        )
        for table, version in tables:
            try:
                lines = table.read_text(encoding="ascii").splitlines()[1:]
            except OSError:
                continue
            for line in lines:
                fields = line.split()
                if len(fields) <= 9 or fields[3] != "0A":
                    continue
                local_address, local_port = fields[1].rsplit(":", 1)
                if local_port != encoded_port:
                    continue
                address = HostProcess._decode_proc_address(local_address, version)
                if address.is_unspecified or address == expected_address:
                    return fields[9]
                if (
                    version == 6
                    and address.ipv4_mapped is not None
                    and address.ipv4_mapped == expected_address
                ):
                    return fields[9]
        return None

    @staticmethod
    def _decode_proc_address(
        encoded: str,
        version: int,
    ) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        raw = bytes.fromhex(encoded)
        if version == 4:
            return ipaddress.IPv4Address(raw[::-1])
        if version == 6:
            raw = b"".join(
                raw[offset : offset + 4][::-1]
                for offset in range(0, len(raw), 4)
            )
            return ipaddress.IPv6Address(raw)
        raise ValueError(f"Unsupported IP version: {version}")

    @staticmethod
    def _process_owns_socket(pid: int, inode: str) -> bool:
        fd_directory = Path("/proc") / str(pid) / "fd"
        try:
            descriptors = tuple(fd_directory.iterdir())
        except OSError:
            return False
        target = f"socket:[{inode}]"
        for descriptor in descriptors:
            try:
                if os.readlink(descriptor) == target:
                    return True
            except OSError:
                continue
        return False

    def _signal_group(self, sig: signal.Signals) -> None:
        process = self.process
        if process is None:
            return
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    def _close_log(self) -> None:
        if self._log_stream is not None:
            self._log_stream.flush()
            self._log_stream.close()
            self._log_stream = None

    def _record(self, event: str, **fields: object) -> None:
        if self.trace is not None:
            self.trace.record(event, **fields)

    def __enter__(self) -> HostProcess:
        return self.start()

    def __exit__(self, *_exc_info: object) -> None:
        self.stop()
