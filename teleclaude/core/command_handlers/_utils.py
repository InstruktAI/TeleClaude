"""Shared utilities, types, and decorators for command handlers."""

import functools
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, TypeVar

from instrukt_ai_logging import get_logger
from typing_extensions import TypedDict

from teleclaude.core.db import db

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# Startup gate: bounded wait for session to exit "initializing" before tmux injection.
STARTUP_GATE_TIMEOUT_S = float(os.getenv("STARTUP_GATE_TIMEOUT_S", "15"))
STARTUP_GATE_POLL_INTERVAL_S = float(os.getenv("STARTUP_GATE_POLL_INTERVAL_S", "0.25"))


# Result from end_session
class EndSessionHandlerResult(TypedDict):
    """Result from end_session."""

    status: str
    message: str


# Session data payload returned by get_session_data
class SessionDataPayload(TypedDict, total=False):
    """Session data payload returned by get_session_data."""

    status: str  # Required - always present
    session_id: str
    transcript: str | None
    last_activity: str | None
    project_path: str | None
    subdir: str | None
    error: str  # Present in error responses
    messages: str  # Sometimes present
    created_at: str | None  # Sometimes present


# Type alias for start_polling function
StartPollingFunc = Callable[[str, str], Awaitable[None]]

# Decorator to inject session from context (removes boilerplate)
R = TypeVar("R")


def with_session(
    func: Callable[..., Awaitable[R]],
) -> Callable[..., Awaitable[R]]:
    """Decorator that extracts and injects session from a command object."""

    @functools.wraps(func)
    async def wrapper(cmd: object, *args: object, **kwargs: object) -> R:
        if not hasattr(cmd, "session_id"):
            raise ValueError(f"Object {type(cmd).__name__} missing session_id")

        session_id = str(getattr(cmd, "session_id"))  # noqa: B009 — cmd is typed as object, getattr is intentional
        session = await db.get_session(session_id)
        if session is None:
            raise RuntimeError(f"Session {session_id} not found - this should not happen")

        return await func(session, cmd, *args, **kwargs)

    return wrapper
