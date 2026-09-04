"""Pytest fixtures for ESPHome host end-to-end tests."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from support import HostBuild, HostProcess, JsonlTrace, NativeApiAdapter, PtyUart
from support.build import prepare_host_build

REPO_ROOT = Path(__file__).resolve().parents[2]
HOST_TEMPLATE = Path(__file__).with_name("host.yaml.j2")


def _test_slug(node_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", node_id).strip("-") or "test"


@pytest.fixture(scope="session")
def host_build(tmp_path_factory: pytest.TempPathFactory) -> Iterator[HostBuild]:
    """Compile the ESPHome 2026.7.4 host binary once per test session."""
    work_dir = tmp_path_factory.mktemp("uart-vrf-host-build")
    build = prepare_host_build(
        repo_root=REPO_ROOT,
        work_dir=work_dir,
        template_path=HOST_TEMPLATE,
    )
    try:
        yield build
    finally:
        build.release_api_port()


@pytest.fixture
def trace(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[JsonlTrace]:
    recorder = JsonlTrace(tmp_path / f"{_test_slug(request.node.nodeid)}.jsonl")
    recorder.record("test.start", node_id=request.node.nodeid)
    try:
        yield recorder
    finally:
        recorder.record("test.stop", node_id=request.node.nodeid)
        recorder.close()


@pytest.fixture
def esphome_prefdir(tmp_path: Path) -> Path:
    """Return one preference directory retained across restarts in this test."""
    path = tmp_path / "preferences"
    path.mkdir()
    return path


@pytest.fixture
def pty_uart(host_build: HostBuild, trace: JsonlTrace) -> Iterator[PtyUart]:
    uart = PtyUart(host_build.uart_path, trace=trace)
    try:
        yield uart
    finally:
        uart.close()


@pytest.fixture
def host_process(
    host_build: HostBuild,
    pty_uart: PtyUart,
    esphome_prefdir: Path,
    tmp_path: Path,
    trace: JsonlTrace,
) -> Iterator[HostProcess]:
    """Start a per-test host process and always reap its process group."""
    del pty_uart  # Ensure the stable UART link exists before process startup.
    process = HostProcess(
        host_build.binary,
        log_path=tmp_path / "host.log",
        preferences_dir=esphome_prefdir,
        cwd=host_build.config.parent,
        api_host=host_build.api_host,
        api_port=host_build.api_port,
        trace=trace,
    )
    host_build.release_api_port()
    process.start()
    try:
        yield process
    finally:
        process.stop()


@pytest.fixture
async def native_api(
    host_build: HostBuild,
    host_process: HostProcess,
    trace: JsonlTrace,
) -> AsyncIterator[NativeApiAdapter]:
    """Return an adapter that tests connect after the initial safe reboot."""
    del host_process  # Keep API cleanup ordered before host process cleanup.
    adapter = NativeApiAdapter(
        host_build.api_host,
        host_build.api_port,
        trace=trace,
    )
    try:
        yield adapter
    finally:
        await adapter.disconnect()
