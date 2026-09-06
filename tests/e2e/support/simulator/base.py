"""Async PTY transport and framing primitives for VRF simulators."""

from __future__ import annotations

import asyncio
import errno
import inspect
import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any, Literal

from .model import ClimateState

TraceDirection = Literal["host_to_vrf", "vrf_to_host", "internal"]


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One observable simulator transport or parser event."""

    direction: TraceDirection
    data: bytes = b""
    note: str = ""
    timestamp: float = 0.0


TraceCallback = Callable[[TraceEvent], Any]
FramePredicate = Callable[[bytes], bool]


class VrfSimulator(ABC):
    """Base class for a nonblocking simulator attached to a PTY master fd.

    Subclasses extract complete host frames from ``self.rx_buffer`` and handle
    them synchronously. Responses are queued through ``write()`` so callers may
    deliberately fragment, delay, corrupt, or prefix them with noise.
    """

    def __init__(
        self,
        master_fd: int,
        states: ClimateState | Iterable[ClimateState] | None = None,
        *,
        trace: TraceCallback | None = None,
        read_size: int = 4096,
    ) -> None:
        self.master_fd = int(master_fd)
        self.read_size = int(read_size)
        if self.read_size <= 0:
            raise ValueError("read_size must be positive")
        self.trace_callback = trace
        self.rx_buffer = bytearray()
        self.frame_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.response_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.states: dict[int, ClimateState] = {}
        self.running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._reader_registered = False
        self._write_lock = asyncio.Lock()
        self._write_tasks: set[asyncio.Future[Any]] = set()
        self.auto_respond = True
        self.response_fragment_sizes: int | Sequence[int] | None = None
        self.response_delay = 0.0
        self.response_inter_fragment_delay = 0.0
        if states is None:
            states = (ClimateState(),)
        elif isinstance(states, ClimateState):
            states = (states,)
        for state in states:
            self.add_state(state)

    @property
    def state(self) -> ClimateState:
        """Return the sole/lowest-address state for compact test setups."""

        if not self.states:
            raise LookupError("simulator has no climate states")
        return self.states[min(self.states)]

    def add_state(self, state: ClimateState) -> ClimateState:
        """Add or replace one indoor-unit state by address."""

        if not isinstance(state, ClimateState):
            raise TypeError("state must be a ClimateState")
        self.states[state.address] = state
        return state

    def get_state(self, address: int) -> ClimateState | None:
        return self.states.get(int(address))

    async def __aenter__(self) -> VrfSimulator:
        self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()

    def start(self) -> None:
        """Start consuming bytes from the PTY master fd."""

        if self.running:
            return
        self._loop = asyncio.get_running_loop()
        os.set_blocking(self.master_fd, False)
        self.running = True
        self.resume_reader()
        self._trace("internal", note="simulator started")

    def resume_reader(self) -> None:
        """Resume PTY reads after a host generation opens the slave."""

        if not self.running or self._loop is None or self._reader_registered:
            return
        self._loop.add_reader(self.master_fd, self._on_readable)
        self._reader_registered = True
        self._trace("internal", note="PTY reader resumed")

    def _pause_reader(self) -> None:
        if self._loop is None or not self._reader_registered:
            return
        self._loop.remove_reader(self.master_fd)
        self._reader_registered = False
        self._trace("internal", note="PTY reader paused")

    async def stop(self, timeout: float = 2.0) -> None:
        """Stop fd callbacks and surface pending response failures."""

        self._pause_reader()
        self.running = False
        self._trace("internal", note="simulator stopped")
        await self._settle_pending_tasks(timeout=timeout)

    def close(self) -> None:
        """Stop reading without closing the caller-owned PTY fd."""

        self._pause_reader()
        self.running = False

    async def reset_transport(self) -> None:
        """Cancel old writes and discard parser state between host generations."""

        tasks = tuple(self._write_tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._write_tasks.difference_update(tasks)
        self.rx_buffer.clear()
        self.clear_queues()
        self._trace("internal", note="transport reset")

    def _trace(
        self, direction: TraceDirection, data: bytes = b"", *, note: str = ""
    ) -> None:
        if self.trace_callback is None:
            return
        event = TraceEvent(direction, bytes(data), note, monotonic())
        result = self.trace_callback(event)
        if inspect.isawaitable(result):
            future = asyncio.ensure_future(result)
            self._track_write_task(future)

    def _on_readable(self) -> None:
        while True:
            try:
                chunk = os.read(self.master_fd, self.read_size)
            except BlockingIOError:
                return
            except OSError as exc:
                if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK}:
                    return
                if exc.errno == errno.EIO:
                    self._pause_reader()
                    return
                raise
            if not chunk:
                return
            self._trace("host_to_vrf", chunk, note="read")
            self.feed_bytes(chunk)
            if len(chunk) < self.read_size:
                return

    def feed_bytes(self, data: bytes | bytearray | memoryview) -> list[bytes]:
        """Feed host bytes directly, useful for deterministic parser tests."""

        if data:
            self.rx_buffer.extend(data)
        extracted: list[bytes] = []
        while True:
            before = len(self.rx_buffer)
            frame = self.extract_frame()
            if frame is None:
                if len(self.rx_buffer) > before:
                    raise RuntimeError("extract_frame grew the receive buffer")
                break
            frame = bytes(frame)
            extracted.append(frame)
            self.frame_queue.put_nowait(frame)
            self._trace("internal", frame, note="frame accepted")
            response = self.handle_frame(frame)
            if response is not None and self.auto_respond:
                if isinstance(response, (bytes, bytearray, memoryview)):
                    payload = bytes(response)
                else:
                    payload = b"".join(bytes(part) for part in response)
                self.response_queue.put_nowait(payload)
                if self.running:
                    self.schedule_write(
                        payload,
                        fragment_sizes=self.response_fragment_sizes,
                        delay=self.response_delay,
                        inter_fragment_delay=self.response_inter_fragment_delay,
                    )
                else:
                    self._trace("internal", payload, note="response queued")
        return extracted

    @abstractmethod
    def extract_frame(self) -> bytes | None:
        """Remove and return one valid frame from ``rx_buffer``.

        Invalid bytes and complete invalid frames should be discarded with an
        optional trace event. Incomplete candidate frames must remain buffered.
        """

    @abstractmethod
    def handle_frame(self, frame: bytes) -> bytes | Iterable[bytes] | None:
        """Update model state and optionally return one or more responses."""

    def discard_noise(self, count: int, *, note: str = "noise discarded") -> bytes:
        """Remove parser noise from the receive buffer and trace it."""

        discarded = bytes(self.rx_buffer[:count])
        del self.rx_buffer[:count]
        if discarded:
            self._trace("internal", discarded, note=note)
        return discarded

    def schedule_write(
        self,
        data: bytes | bytearray | memoryview | Iterable[bytes],
        *,
        fragment_sizes: int | Sequence[int] | None = None,
        delay: float = 0.0,
        inter_fragment_delay: float = 0.0,
    ) -> asyncio.Task[None]:
        """Schedule response bytes with optional initial and fragment delays."""

        if isinstance(data, (bytes, bytearray, memoryview)):
            payload = bytes(data)
        else:
            payload = b"".join(bytes(part) for part in data)
        task = asyncio.create_task(
            self.write(
                payload,
                fragment_sizes=fragment_sizes,
                delay=delay,
                inter_fragment_delay=inter_fragment_delay,
            )
        )
        self._track_write_task(task)
        return task

    def _track_write_task(self, task: asyncio.Future[Any]) -> None:
        self._write_tasks.add(task)
        task.add_done_callback(self._discard_completed_write_task)

    def _discard_completed_write_task(self, task: asyncio.Future[Any]) -> None:
        if task.cancelled() or task.exception() is None:
            self._write_tasks.discard(task)

    async def write(
        self,
        data: bytes | bytearray | memoryview,
        *,
        fragment_sizes: int | Sequence[int] | None = None,
        delay: float = 0.0,
        inter_fragment_delay: float = 0.0,
    ) -> None:
        """Write VRF bytes after an optional delay and in timed fragments."""

        if delay < 0 or inter_fragment_delay < 0:
            raise ValueError("write delays must not be negative")
        payload = bytes(data)
        fragments = self._split_fragments(payload, fragment_sizes)
        if delay > 0:
            await asyncio.sleep(delay)
        async with self._write_lock:
            for index, fragment in enumerate(fragments):
                if index and inter_fragment_delay > 0:
                    await asyncio.sleep(inter_fragment_delay)
                await self._write_all(fragment)
                self._trace("vrf_to_host", fragment, note="write")

    async def drain_pending_writes(self, timeout: float = 2.0) -> None:
        """Wait until all currently scheduled writes and callbacks finish."""

        await self._settle_pending_tasks(timeout=timeout)

    async def _settle_pending_tasks(self, timeout: float) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while self._write_tasks:
                tasks = tuple(self._write_tasks)
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError
                async with asyncio.timeout(remaining):
                    await asyncio.gather(*tasks)
                self._write_tasks.difference_update(tasks)
        except BaseException:
            tasks = tuple(self._write_tasks)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._write_tasks.difference_update(tasks)
            raise

    async def inject_noise(
        self,
        data: bytes | bytearray | memoryview = b"\x00\xff\x55",
        *,
        fragment_sizes: int | Sequence[int] | None = None,
        delay: float = 0.0,
        inter_fragment_delay: float = 0.0,
    ) -> None:
        """Write arbitrary noise toward the host."""

        await self.write(
            data,
            fragment_sizes=fragment_sizes,
            delay=delay,
            inter_fragment_delay=inter_fragment_delay,
        )

    async def inject_bad_frame(
        self,
        frame: bytes | bytearray | memoryview,
        *,
        index: int = -1,
        xor: int = 0x01,
        fragment_sizes: int | Sequence[int] | None = None,
        delay: float = 0.0,
        inter_fragment_delay: float = 0.0,
    ) -> bytes:
        """Corrupt one byte and write the resulting invalid frame."""

        bad = bytearray(frame)
        if not bad:
            raise ValueError("frame must not be empty")
        bad[index] ^= xor & 0xFF
        await self.write(
            bad,
            fragment_sizes=fragment_sizes,
            delay=delay,
            inter_fragment_delay=inter_fragment_delay,
        )
        return bytes(bad)

    def clear_queues(self) -> None:
        """Discard observed frames and generated-response records."""

        while not self.frame_queue.empty():
            self.frame_queue.get_nowait()
        while not self.response_queue.empty():
            self.response_queue.get_nowait()

    async def wait_for_frame_sequence(
        self,
        predicates: Sequence[FramePredicate],
        *,
        timeout: float = 1.0,
    ) -> list[bytes]:
        """Consume matching frames in order while ignoring unrelated traffic."""

        if not predicates:
            return []
        frames: list[bytes] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while len(frames) < len(predicates):
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for VRF frame sequence")
            frame = await asyncio.wait_for(self.frame_queue.get(), remaining)
            expected_index = len(frames)
            if predicates[expected_index](frame):
                frames.append(frame)
                continue
            if any(predicate(frame) for predicate in predicates[expected_index + 1 :]):
                raise AssertionError("VRF frame sequence arrived out of order")
        return frames

    async def wait_for_frame(
        self,
        predicate: FramePredicate | None = None,
        *,
        timeout: float = 1.0,
    ) -> bytes:
        """Wait for and consume the first queued frame matching *predicate*.

        Nonmatching frames are restored in their original order before return
        or timeout, making predicate waits safe for sequential E2E assertions.
        """

        predicate = predicate or (lambda _frame: True)
        skipped: list[bytes] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError("timed out waiting for matching VRF frame")
                frame = await asyncio.wait_for(self.frame_queue.get(), remaining)
                if predicate(frame):
                    return frame
                skipped.append(frame)
        finally:
            queued: list[bytes] = []
            while not self.frame_queue.empty():
                queued.append(self.frame_queue.get_nowait())
            for frame in (*skipped, *queued):
                self.frame_queue.put_nowait(frame)

    async def _write_all(self, data: bytes) -> None:
        if not data:
            return
        loop = asyncio.get_running_loop()
        view = memoryview(data)
        while view:
            try:
                written = os.write(self.master_fd, view)
                view = view[written:]
            except BlockingIOError:
                ready = loop.create_future()
                loop.add_writer(self.master_fd, ready.set_result, None)
                try:
                    await ready
                finally:
                    loop.remove_writer(self.master_fd)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    return
                raise

    @staticmethod
    def _split_fragments(
        payload: bytes, fragment_sizes: int | Sequence[int] | None
    ) -> list[bytes]:
        if fragment_sizes is None:
            return [payload] if payload else []
        if isinstance(fragment_sizes, int):
            if fragment_sizes <= 0:
                raise ValueError("fragment size must be positive")
            return [
                payload[offset : offset + fragment_sizes]
                for offset in range(0, len(payload), fragment_sizes)
            ]
        sizes = list(fragment_sizes)
        if any(size <= 0 for size in sizes):
            raise ValueError("fragment sizes must be positive")
        fragments: list[bytes] = []
        offset = 0
        for size in sizes:
            if offset >= len(payload):
                break
            fragments.append(payload[offset : offset + size])
            offset += size
        if offset < len(payload):
            fragments.append(payload[offset:])
        return fragments
