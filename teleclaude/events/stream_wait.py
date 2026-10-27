"""A blocking stream read that ends as soon as shutdown is requested.

Readers block on Redis for up to their block window so an idle stream costs one request per window; shutdown must
not wait that window out, so the read and the shutdown signal race and the loser is cancelled.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from typing import Final

from teleclaude.constants import REDIS_STREAM_BLOCK_S

#: How long an idle reader blocks on Redis before it asks again; an arriving entry returns the read at once.
STREAM_BLOCK_MS: Final = REDIS_STREAM_BLOCK_S * 1000


async def read_until_shutdown[T](read: Awaitable[T], shutdown_event: asyncio.Event) -> T | None:
    """The read's result, or None when shutdown was requested before it returned; the losing wait is cancelled."""
    read_task = asyncio.ensure_future(read)
    stop_task = asyncio.ensure_future(shutdown_event.wait())
    try:
        done, _pending = await asyncio.wait({read_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        read_task.cancel()
        stop_task.cancel()
        raise
    if read_task in done:
        stop_task.cancel()
        return read_task.result()
    read_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await read_task
    return None
