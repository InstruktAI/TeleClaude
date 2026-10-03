"""Config-owned notification for changes to identity declarations."""

from __future__ import annotations

from collections.abc import Callable

_SUBSCRIBERS: set[Callable[[], None]] = set()


def subscribe_declaration_changes(callback: Callable[[], None]) -> None:
    """Register a synchronous consumer for membership or ownership changes."""
    _SUBSCRIBERS.add(callback)


def unsubscribe_declaration_changes(callback: Callable[[], None]) -> None:
    """Remove a consumer that no longer holds live identity state."""
    _SUBSCRIBERS.discard(callback)


def publish_declaration_changes() -> None:
    """Notify consumers after config has refreshed its published answers."""
    for callback in tuple(_SUBSCRIBERS):
        callback()
