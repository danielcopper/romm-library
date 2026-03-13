"""Shared utilities for service modules."""

from __future__ import annotations

from typing import Any


def run_api_sync(coro: Any) -> Any:
    """Execute a SaveApiProtocol coroutine synchronously.

    Current adapters (V46) perform synchronous I/O wrapped in
    ``async def``.  Consuming the coroutine via ``send(None)`` keeps
    the I/O in the calling (executor) thread instead of bouncing it
    to the event-loop thread.

    If a future adapter performs real async I/O (yields), this will
    raise ``RuntimeError`` — at which point the caller must switch
    to ``asyncio.run_coroutine_threadsafe()``.
    """
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise RuntimeError(
        "SaveApi adapter yielded (real async I/O) — sync caller needs asyncio.run_coroutine_threadsafe()"
    )
