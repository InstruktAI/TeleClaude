"""Remote session target helpers for API routes."""

from teleclaude.core.command_dispatch import is_remote_target

__all__ = ["is_remote_create_target", "is_remote_target"]


def is_remote_create_target(computer: str, local_computer: str) -> bool:
    """Return whether a create request targets a peer computer."""
    return is_remote_target(computer, local_computer)
