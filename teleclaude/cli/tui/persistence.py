"""Persistence protocol helpers for TUI widgets."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from textual.widget import Widget


@runtime_checkable
class Persistable(Protocol):
    """Protocol for widgets that can persist and restore local state."""

    def get_persisted_state(self) -> dict[str, object]:  # guard: loose-dict - widget payloads vary by component
        """Return a JSON-serializable state snapshot for this widget."""
        ...

    def load_persisted_state(self, data: dict[str, object]) -> None:  # guard: loose-dict - widget payloads vary
        """Restore widget state from a persisted snapshot."""
        ...


def get_persistence_key(widget: Widget) -> str:
    """Resolve persistence namespace key for a widget."""
    key = getattr(widget, "persistence_key", None)
    if isinstance(key, str) and key:
        return key

    if widget.id:
        return widget.id.replace("-", "_")

    return widget.__class__.__name__.lower()
