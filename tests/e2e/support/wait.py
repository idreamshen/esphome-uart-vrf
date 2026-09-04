"""Deadline-based asynchronous wait helpers."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
Predicate = Callable[[], T | Awaitable[T]]


class WaitTimeoutError(TimeoutError):
    """Raised when an end-to-end condition misses its deadline."""


async def wait_until(
    predicate: Predicate[T],
    *,
    timeout: float,
    interval: float = 0.05,
    description: str = "condition",
) -> T:
    """Poll *predicate* until it returns a truthy value or time expires.

    A monotonic deadline prevents wall-clock adjustments from extending or
    shortening a test. The predicate may be synchronous or asynchronous.
    """
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if interval <= 0:
        raise ValueError("interval must be positive")

    deadline = time.monotonic() + timeout
    last_value: T
    while True:
        value = predicate()
        if inspect.isawaitable(value):
            value = await value
        last_value = value
        if last_value:
            return last_value

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WaitTimeoutError(
                f"Timed out after {timeout:.3f}s waiting for {description}"
            )
        await asyncio.sleep(min(interval, remaining))
