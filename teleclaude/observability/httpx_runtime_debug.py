"""One-shot runtime tracing for httpx AsyncClient lifecycle.

This is intentionally temporary and expensive. It exists to attribute
shutdown-time ``Event loop is closed`` errors to the concrete httpx client
source so the underlying lifecycle bug can be fixed and this tracer removed.
"""

from __future__ import annotations

import asyncio
import traceback
import weakref
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict, cast

import httpx
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class _TraceState(TypedDict):
    enabled: bool
    original_init: object | None
    original_aclose: object | None
    creation: weakref.WeakKeyDictionary[httpx.AsyncClient, dict[str, str]] | None


_STATE: _TraceState = {"enabled": False, "original_init": None, "original_aclose": None, "creation": None}


def enable_httpx_async_client_tracing() -> None:
    """Patch httpx.AsyncClient to attribute close-on-shutdown failures."""
    if _STATE["enabled"]:
        return

    original_init = httpx.AsyncClient.__init__
    original_aclose = httpx.AsyncClient.aclose
    creation: weakref.WeakKeyDictionary[httpx.AsyncClient, dict[str, str]] = weakref.WeakKeyDictionary()

    def traced_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        task = asyncio.current_task()
        task_name = task.get_name() if task is not None else "unknown"
        creation[self] = {
            "task_name": task_name,
            "trace": "".join(traceback.format_stack(limit=12)),
        }

    async def traced_aclose(self: httpx.AsyncClient) -> None:
        try:
            await cast(Callable[[httpx.AsyncClient], Awaitable[None]], original_aclose)(self)
        except RuntimeError as exc:
            if str(exc) != "Event loop is closed":
                raise
            data = creation.get(self, {})
            logger.error(
                "httpx AsyncClient close hit closed loop",
                create_task_name=data.get("task_name", "unknown"),
                create_trace=data.get("trace", "missing"),
                close_task_name=asyncio.current_task().get_name() if asyncio.current_task() is not None else "unknown",
                client_type=f"{type(self).__module__}.{type(self).__qualname__}",
                client_id=id(self),
            )
            raise

    httpx.AsyncClient.__init__ = traced_init  # type: ignore[method-assign]
    httpx.AsyncClient.aclose = traced_aclose  # type: ignore[method-assign]
    _STATE["enabled"] = True
    _STATE["original_init"] = original_init
    _STATE["original_aclose"] = original_aclose
    _STATE["creation"] = creation


enable_httpx_async_client_tracing()
