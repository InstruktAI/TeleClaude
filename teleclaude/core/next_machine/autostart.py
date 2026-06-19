"""Shared workflow autostart readers."""

from __future__ import annotations

from teleclaude.config import config
from teleclaude.core.next_machine.kinds import canonical_kind

__all__ = ["autostart_enabled_for_kind"]


def autostart_enabled_for_kind(kind: str | None) -> bool:
    """Return whether workflow autostart is enabled for a known todo kind."""
    if kind is None:
        return False
    try:
        canonical = canonical_kind(kind)
    except ValueError:
        return False
    return bool(getattr(config.workflow.autostart, canonical, False))
