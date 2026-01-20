"""Global CommandService registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.core.command_service import CommandService

_command_service: CommandService | None = None


def init_command_service(command_service: "CommandService", *, force: bool = False) -> "CommandService":
    """Initialize the global CommandService singleton."""
    global _command_service
    if _command_service is not None and not force:
        raise RuntimeError("CommandService already initialized")
    _command_service = command_service
    return _command_service


def get_command_service() -> "CommandService":
    """Return the global CommandService singleton."""
    if _command_service is None:
        raise RuntimeError("CommandService not initialized")
    return _command_service


def reset_command_service() -> None:
    """Reset the global CommandService singleton (tests only)."""
    global _command_service
    _command_service = None
