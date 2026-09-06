"""Focused tests for E2E orchestration failure handling."""

from __future__ import annotations

import asyncio
import os
import pty
import time
import tty
from typing import Any

import pytest

from support.host_process import HostProcess
from support.native_api import NativeApiAdapter
from support.simulator import ClimateState, SochuangSimulator, ZhonghongSimulator
from support.wait import WaitTimeoutError


class _SlowApiClient:
    def __init__(self) -> None:
        self.disconnect_calls = 0
        self.disconnect_finished = False

    async def connect(self, *, login: bool) -> None:
        assert login is True
        await asyncio.sleep(60)

    async def disconnect(self, *, force: bool = False) -> None:
        assert force is True
        self.disconnect_calls += 1
        await asyncio.sleep(0)
        self.disconnect_finished = True


class _EntitySnapshotClient:
    def __init__(self, result: object) -> None:
        self.result = result
        self.disconnect_calls = 0

    async def connect(self, *, login: bool) -> None:
        assert login is True

    def subscribe_states(self, callback: object) -> None:
        assert callable(callback)

    async def list_entities_services(self) -> object:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def disconnect(self, *, force: bool = False) -> None:
        assert force is True
        self.disconnect_calls += 1


def test_zhonghong_encodes_64_unit_discovery_response() -> None:
    states = {
        (1, address): ClimateState(address=address)
        for address in range(1, 65)
    }
    simulator = ZhonghongSimulator(-1, states)

    response = simulator.encode_discovery_response()

    assert response[3] == 64
    assert len(response) == 197


@pytest.mark.asyncio
async def test_simulator_pauses_reader_on_pty_eio() -> None:
    master_fd, slave_fd = pty.openpty()
    tty.setraw(master_fd)
    tty.setraw(slave_fd)
    slave_name = os.ttyname(slave_fd)
    simulator = SochuangSimulator(master_fd)
    try:
        simulator.start()
        assert simulator._reader_registered

        os.close(slave_fd)
        slave_fd = -1
        await asyncio.sleep(0.01)
        assert not simulator._reader_registered

        reopened_slave_fd = os.open(slave_name, os.O_RDWR | os.O_NOCTTY)
        try:
            simulator.resume_reader()
            assert simulator._reader_registered
        finally:
            os.close(reopened_slave_fd)
    finally:
        await simulator.stop()
        if slave_fd >= 0:
            os.close(slave_fd)
        os.close(master_fd)


def test_host_socket_lookup_matches_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tcp = "\n".join(
        (
            "sl local_address rem_address st tx_queue tr tm->when retrnsmt uid timeout inode",
            "0: 0200007F:17A5 00000000:0000 0A 0 0 0 0 0 111",
            "1: 0100007F:17A5 00000000:0000 0A 0 0 0 0 0 222",
        )
    )

    def read_text(path: object, *, encoding: str) -> str:
        assert encoding == "ascii"
        return tcp if str(path) == "/proc/net/tcp" else "sl\n"

    monkeypatch.setattr("pathlib.Path.read_text", read_text)

    assert HostProcess._listening_socket_inode("127.0.0.1", 6053) == "222"


@pytest.mark.asyncio
async def test_native_api_connect_honors_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _SlowApiClient()
    adapter = NativeApiAdapter("127.0.0.1", 6053)
    monkeypatch.setattr(adapter, "_make_client", lambda: client)

    started = time.monotonic()
    with pytest.raises(WaitTimeoutError):
        await adapter.connect(timeout=0.05)

    assert time.monotonic() - started < 0.5
    assert client.disconnect_calls == 1
    assert client.disconnect_finished is True
    assert adapter.client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("expected_count", [None, 1])
async def test_native_api_entity_snapshot_reconnects_after_error(
    monkeypatch: pytest.MonkeyPatch,
    expected_count: int | None,
) -> None:
    climate = type("ClimateInfo", (), {"supported_modes": ()})()
    first = _EntitySnapshotClient(RuntimeError("connection closed"))
    second = _EntitySnapshotClient(([climate], []))
    clients = iter((first, second))
    adapter = NativeApiAdapter("127.0.0.1", 6053)
    monkeypatch.setattr(adapter, "_make_client", lambda: next(clients))

    entities = await adapter.wait_for_climate_entities(
        timeout=0.5,
        interval=0.001,
        expected_count=expected_count,
    )

    assert entities == [climate]
    assert first.disconnect_calls == 1
    assert adapter.client is second
    await adapter.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_count", [0, 1, 3])
async def test_native_api_entity_snapshot_requires_exact_count(
    monkeypatch: pytest.MonkeyPatch,
    initial_count: int,
) -> None:
    climates = [type("ClimateInfo", (), {})() for _ in range(3)]
    first = _EntitySnapshotClient((climates[:initial_count], []))
    second = _EntitySnapshotClient((climates[:2], []))
    clients = iter((first, second))
    adapter = NativeApiAdapter("127.0.0.1", 6053)
    adapter.latest_states[123] = object()

    def callback(state: object) -> None:
        pass

    adapter._state_callbacks.add(callback)
    monkeypatch.setattr(adapter, "_make_client", lambda: next(clients))

    entities = await adapter.wait_for_climate_entities(
        timeout=0.5,
        interval=0.001,
        expected_count=2,
    )

    assert entities == climates[:2]
    assert first.disconnect_calls == 1
    assert second.disconnect_calls == 0
    assert adapter.client is second
    assert not adapter.latest_states
    assert callback in adapter._state_callbacks
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_native_api_entity_snapshot_shares_connect_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    climate = type("ClimateInfo", (), {})()

    class SlowSnapshotClient(_EntitySnapshotClient):
        async def connect(self, *, login: bool) -> None:
            await super().connect(login=login)
            await asyncio.sleep(0.06)

        async def list_entities_services(self) -> object:
            await asyncio.sleep(0.06)
            return await super().list_entities_services()

    client = SlowSnapshotClient(([climate], []))
    adapter = NativeApiAdapter("127.0.0.1", 6053)
    monkeypatch.setattr(adapter, "_make_client", lambda: client)

    with pytest.raises(WaitTimeoutError, match="waiting for climate entities"):
        await adapter.wait_for_climate_entities(timeout=0.1)

    assert client.disconnect_calls == 1
    assert adapter.client is None


@pytest.mark.asyncio
async def test_native_api_entity_snapshot_times_out_stuck_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled = asyncio.Event()

    class StuckSnapshotClient(_EntitySnapshotClient):
        async def list_entities_services(self) -> object:
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

    client = StuckSnapshotClient(([], []))
    adapter = NativeApiAdapter("127.0.0.1", 6053)
    adapter.latest_states[123] = object()
    monkeypatch.setattr(adapter, "_make_client", lambda: client)

    async with asyncio.timeout(0.5):
        with pytest.raises(WaitTimeoutError, match="waiting for climate entities"):
            await adapter.wait_for_climate_entities(timeout=0.02)

    assert cancelled.is_set()
    assert client.disconnect_calls == 1
    assert adapter.client is None
    assert not adapter.latest_states


@pytest.mark.asyncio
@pytest.mark.parametrize("expected_count", [0, -1, True, False, 1.5, "2"])
async def test_native_api_entity_snapshot_rejects_invalid_counts(
    monkeypatch: pytest.MonkeyPatch,
    expected_count: Any,
) -> None:
    adapter = NativeApiAdapter("127.0.0.1", 6053)

    def unexpected_client() -> None:
        pytest.fail("Invalid counts must be rejected before connecting")

    monkeypatch.setattr(adapter, "_make_client", unexpected_client)

    with pytest.raises(ValueError, match="expected_count must be a positive integer"):
        await adapter.wait_for_climate_entities(expected_count=expected_count)


@pytest.mark.asyncio
async def test_simulator_discards_completed_write_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simulator = SochuangSimulator(-1)

    async def write_all(_data: bytes) -> None:
        return None

    monkeypatch.setattr(simulator, "_write_all", write_all)
    task = simulator.schedule_write(b"response")
    await task
    await asyncio.sleep(0)

    assert not simulator._write_tasks


@pytest.mark.asyncio
async def test_simulator_surfaces_background_task_failure() -> None:
    simulator = SochuangSimulator(-1)

    async def fail() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("scheduled response failed")

    task: asyncio.Task[Any] = asyncio.create_task(fail())
    simulator._write_tasks.add(task)

    with pytest.raises(RuntimeError, match="scheduled response failed"):
        await simulator.drain_pending_writes()

    assert not simulator._write_tasks


@pytest.mark.asyncio
async def test_simulator_cancels_background_task_at_deadline() -> None:
    simulator = SochuangSimulator(-1)
    cancelled = asyncio.Event()

    async def hang() -> None:
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    task: asyncio.Task[Any] = asyncio.create_task(hang())
    simulator._write_tasks.add(task)

    with pytest.raises(TimeoutError):
        await simulator.drain_pending_writes(timeout=0.01)

    assert task.cancelled()
    assert cancelled.is_set()
    assert not simulator._write_tasks
