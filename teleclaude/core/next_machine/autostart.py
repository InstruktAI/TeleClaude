"""Shared workflow autostart readers."""

from __future__ import annotations

from teleclaude.config import WorkflowRunnerMode, config
from teleclaude.core.next_machine.kinds import canonical_kind

__all__ = ["autostart_active_for_kind", "autostart_enabled_for_kind"]


def autostart_enabled_for_kind(kind: str | None) -> bool:
    """Return whether workflow autostart is enabled for a known todo kind."""
    if kind is None:
        return False
    try:
        canonical = canonical_kind(kind)
    except ValueError:
        return False
    return bool(getattr(config.workflow.autostart, canonical, False))


def autostart_active_for_kind(kind: str | None) -> bool:
    """Return whether autostart is *active* for a kind: the runner is in
    autostart mode and the kind's toggle is on.

    The config-reading resolver used only by the server-side projection /
    TUI-server path. ``decide_dispatches`` never calls this — it resolves its own
    ``autostart_active`` from its explicit ``runner_mode`` and ``autostart`` map
    so it stays pure over its inputs.
    """
    return config.workflow.runner is WorkflowRunnerMode.AUTOSTART and autostart_enabled_for_kind(kind)
