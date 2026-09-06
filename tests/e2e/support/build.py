"""Render and compile the ESPHome host test binary."""

from __future__ import annotations

import hashlib
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .pty_uart import PtyUart

HOST_NODE_NAME = "uart-vrf-e2e"


@dataclass(frozen=True)
class HostBuild:
    """Paths and network coordinates shared by one pytest session."""

    binary: Path
    config: Path
    compile_log: Path
    uart_path: Path
    api_host: str
    api_port: int
    _api_reservation: socket.socket | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def release_api_port(self) -> None:
        reservation = self._api_reservation
        if reservation is not None:
            reservation.close()
            object.__setattr__(self, "_api_reservation", None)


def reserve_tcp_port(host: str = "127.0.0.1") -> socket.socket:
    """Bind an ephemeral local TCP port until the host process is launched."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, 0))
    except BaseException:
        sock.close()
        raise
    return sock


def render_host_config(
    template_path: Path,
    destination: Path,
    context: Mapping[str, Any],
) -> None:
    try:
        from jinja2 import Environment, StrictUndefined
    except ImportError as error:
        raise RuntimeError(
            "Jinja2 is unavailable; install tests/requirements-e2e.txt"
        ) from error

    environment = Environment(
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    rendered = environment.from_string(
        Path(template_path).read_text(encoding="utf-8")
    ).render(**context)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")


def compile_host_binary(
    *,
    repo_root: Path,
    config_path: Path,
    compile_log: Path,
    node_name: str = HOST_NODE_NAME,
) -> Path:
    """Validate and compile one host executable."""
    compile_log.parent.mkdir(parents=True, exist_ok=True)
    commands = (
        [sys.executable, "-m", "esphome", "config", str(config_path)],
        [sys.executable, "-m", "esphome", "compile", str(config_path)],
    )
    with compile_log.open("wb") as log_stream:
        for command in commands:
            completed = subprocess.run(
                command,
                cwd=repo_root,
                stdin=subprocess.DEVNULL,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if completed.returncode != 0:
                break
    if completed.returncode != 0:
        lines = compile_log.read_text(encoding="utf-8", errors="replace").splitlines()
        excerpt = "\n".join(lines[-80:])
        stage = command[3]
        raise RuntimeError(
            f"ESPHome host {stage} failed with code {completed.returncode}.\n"
            f"Log: {compile_log}\n{excerpt}"
        )

    build_root = config_path.parent / ".esphome" / "build" / node_name
    candidates = (
        build_root / ".pioenvs" / node_name / "program",
        build_root / "program",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "ESPHome compilation succeeded but the host executable was not found; "
        f"checked: {', '.join(str(path) for path in candidates)}"
    )


def prepare_host_build(
    *,
    repo_root: Path,
    work_dir: Path,
    template_path: Path,
    api_host: str = "127.0.0.1",
) -> HostBuild:
    """Render configuration and compile exactly once for a pytest session."""
    repo_root = Path(repo_root).resolve()
    work_dir = Path(work_dir).resolve()
    # ESPHome 2026.7 validates host UART ports as /<directory>/<device>.
    session_id = hashlib.sha256(str(work_dir).encode()).hexdigest()[:12]
    uart_path = Path("/tmp") / f"uart-vrf-e2e-{session_id}"
    api_reservation = reserve_tcp_port(api_host)
    api_port = int(api_reservation.getsockname()[1])
    config_path = work_dir / "host.yaml"
    compile_log = work_dir / "compile.log"
    try:
        render_host_config(
            template_path,
            config_path,
            {
                "api_host": api_host,
                "api_port": api_port,
                "node_name": HOST_NODE_NAME,
                "components_path": repo_root / "components",
                "uart_path": uart_path,
            },
        )
        with PtyUart(uart_path):
            binary = compile_host_binary(
                repo_root=repo_root,
                config_path=config_path,
                compile_log=compile_log,
            )
    except BaseException:
        api_reservation.close()
        raise
    return HostBuild(
        binary=binary,
        config=config_path,
        compile_log=compile_log,
        uart_path=uart_path,
        api_host=api_host,
        api_port=api_port,
        _api_reservation=api_reservation,
    )
