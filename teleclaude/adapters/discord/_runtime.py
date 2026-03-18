"""Shared runtime helpers for Discord adapter mixins."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from teleclaude.adapters.base_adapter import AdapterError

AsyncDiscordCallable = Callable[..., Awaitable[object]]


def cast_async_callable(
    require_async_callable: Callable[..., AsyncDiscordCallable],
    fn: object,
    *,
    label: str,
) -> AsyncDiscordCallable:
    """Validate and cast a dynamically resolved Discord coroutine method."""
    return cast(AsyncDiscordCallable, require_async_callable(fn, label=label))


def recoverable_operation_errors(discord_module: object) -> tuple[type[Exception], ...]:
    """Return recoverable exception types for best-effort Discord operations."""
    errors: list[type[Exception]] = [
        AdapterError,
        AttributeError,
        OSError,
        RuntimeError,
        TimeoutError,
        TypeError,
        ValueError,
    ]
    discord_exception = getattr(discord_module, "DiscordException", None)
    if isinstance(discord_exception, type) and issubclass(discord_exception, Exception):
        errors.append(discord_exception)
    return tuple(errors)
