"""Small aioesphomeapi adapter used by host E2E tests."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable
from typing import Any

from .trace import JsonlTrace
from .wait import WaitTimeoutError, wait_until


class NativeApiAdapter:
    """Own an APIClient and isolate aioesphomeapi details from tests."""

    _MIN_CLEANUP_TIMEOUT = 0.1

    def __init__(
        self,
        host: str,
        port: int,
        *,
        noise_psk: str | None = None,
        client_info: str = "uart-vrf-e2e",
        trace: JsonlTrace | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.noise_psk = noise_psk
        self.client_info = client_info
        self.trace = trace
        self.client: Any | None = None
        self.latest_states: dict[int, Any] = {}
        self._state_callbacks: set[Callable[[Any], None]] = set()

    async def connect(self, timeout: float = 10.0) -> NativeApiAdapter:
        if self.client is not None:
            return self

        last_error: Exception | None = None

        deadline = time.monotonic() + timeout

        async def try_connect() -> bool:
            nonlocal last_error
            client = self._make_client()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                async with asyncio.timeout(remaining):
                    await client.connect(login=True)
            except Exception as error:
                last_error = error
                await self._disconnect_client(
                    client,
                    timeout=self._cleanup_timeout(deadline),
                )
                return False
            except BaseException:
                await self._disconnect_client(
                    client,
                    timeout=self._cleanup_timeout(deadline),
                )
                raise
            self.client = client
            client.subscribe_states(self._dispatch_state)
            return True

        try:
            await wait_until(
                try_connect,
                timeout=timeout,
                interval=0.1,
                description=f"ESPHome API at {self.host}:{self.port}",
            )
        except WaitTimeoutError as error:
            if last_error is not None:
                raise WaitTimeoutError(f"{error}: {last_error}") from last_error
            raise
        self._record("api.connected", host=self.host, port=self.port)
        return self

    def _make_client(self) -> Any:
        try:
            from aioesphomeapi import APIClient
        except ImportError as error:
            raise RuntimeError(
                "aioesphomeapi is unavailable; install tests/requirements-e2e.txt"
            ) from error

        keyword_arguments: dict[str, Any] = {"client_info": self.client_info}
        if self.noise_psk is not None:
            keyword_arguments["noise_psk"] = self.noise_psk
        return APIClient(self.host, self.port, **keyword_arguments)

    async def device_info(self) -> Any:
        return await self._call("device_info")

    async def list_entities_services(self) -> Any:
        return await self._call("list_entities_services")

    async def climate_entities(self) -> list[Any]:
        """Return discovered climate entities without exposing API model imports."""
        entities, _services = await self.list_entities_services()
        return [
            entity
            for entity in entities
            if entity.__class__.__name__ == "ClimateInfo"
            or hasattr(entity, "supported_modes")
        ]

    async def wait_for_climate_entities(
        self,
        *,
        timeout: float = 10.0,
        interval: float = 0.05,
        expected_count: int | None = None,
    ) -> list[Any]:
        """Reconnect until a non-empty or exact-size climate snapshot is available."""
        if expected_count is not None and (
            isinstance(expected_count, bool)
            or not isinstance(expected_count, int)
            or expected_count <= 0
        ):
            raise ValueError("expected_count must be a positive integer or None")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if interval <= 0:
            raise ValueError("interval must be positive")

        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                detail = f": {last_error}" if last_error is not None else ""
                raise WaitTimeoutError(
                    f"Timed out after {timeout:.3f}s waiting for climate entities"
                    f"{detail}"
                )

            try:
                async with asyncio.timeout(remaining):
                    await self.connect(timeout=remaining)
                    entities = await self.climate_entities()
                if entities and (
                    expected_count is None or len(entities) == expected_count
                ):
                    return entities
            except Exception as error:
                last_error = error
                self._record(
                    "api.entity_snapshot_error",
                    error=repr(error),
                )

            client, self.client = self.client, None
            self.latest_states.clear()
            if client is not None:
                await self._disconnect_client(
                    client,
                    timeout=self._cleanup_timeout(deadline),
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                continue
            await asyncio.sleep(min(interval, remaining))

    async def climate_command(self, key: int, **command: Any) -> Any:
        self._record("api.climate_command", key=key, command=command)
        return await self._call("climate_command", key=key, **command)

    def subscribe_states(self, callback: Callable[[Any], None]) -> Callable[[], None]:
        self._require_client()
        self._state_callbacks.add(callback)

        def cancel() -> None:
            self._state_callbacks.discard(callback)

        return cancel

    async def wait_for_state(
        self,
        predicate: Callable[[Any], bool],
        *,
        timeout: float = 10.0,
        description: str = "native API state",
    ) -> Any:
        """Return the first current or future state matching *predicate*."""
        for state in self.latest_states.values():
            if predicate(state):
                return state

        queue: asyncio.Queue[Any] = asyncio.Queue()
        cancel = self.subscribe_states(queue.put_nowait)
        deadline = time.monotonic() + timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WaitTimeoutError(
                        f"Timed out after {timeout:.3f}s waiting for {description}"
                    )
                try:
                    state = await asyncio.wait_for(queue.get(), timeout=remaining)
                except asyncio.TimeoutError as error:
                    raise WaitTimeoutError(
                        f"Timed out after {timeout:.3f}s waiting for {description}"
                    ) from error
                if predicate(state):
                    return state
        finally:
            cancel()

    async def reconnect(self, timeout: float = 10.0) -> NativeApiAdapter:
        """Reconnect after a host restart using the same endpoint."""
        await self.disconnect()
        return await self.connect(timeout=timeout)

    async def disconnect(self, timeout: float = 2.0) -> None:
        self._state_callbacks.clear()
        self.latest_states.clear()
        client, self.client = self.client, None
        if client is None:
            return
        await self._disconnect_client(client, timeout=timeout, suppress_errors=False)
        self._record("api.disconnected")

    async def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        client = self._require_client()
        result = getattr(client, method_name)(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _cleanup_timeout(self, deadline: float) -> float:
        remaining = max(0.0, deadline - time.monotonic())
        return max(self._MIN_CLEANUP_TIMEOUT, min(1.0, remaining))

    async def _disconnect_client(
        self,
        client: Any,
        *,
        timeout: float = 2.0,
        suppress_errors: bool = True,
    ) -> None:
        try:
            try:
                result = client.disconnect(force=True)
            except TypeError:
                result = client.disconnect()
            if inspect.isawaitable(result):
                async with asyncio.timeout(timeout):
                    await result
        except Exception as error:
            self._record("api.disconnect_error", error=repr(error))
            if not suppress_errors:
                raise

    def _dispatch_state(self, state: Any) -> None:
        key = getattr(state, "key", None)
        if isinstance(key, int):
            self.latest_states[key] = state
        self._record(
            "api.state",
            state_type=state.__class__.__name__,
            key=key,
            mode=getattr(state, "mode", None),
            fan_mode=getattr(state, "fan_mode", None),
            target_temperature=getattr(state, "target_temperature", None),
            current_temperature=getattr(state, "current_temperature", None),
        )
        for callback in self._state_callbacks.copy():
            callback(state)

    def _require_client(self) -> Any:
        if self.client is None:
            raise RuntimeError("Native API client is not connected")
        return self.client

    def _record(self, event: str, **fields: object) -> None:
        if self.trace is not None:
            self.trace.record(event, **fields)

    async def __aenter__(self) -> NativeApiAdapter:
        return await self.connect()

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.disconnect()
