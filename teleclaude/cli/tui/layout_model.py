"""Canonical session-pane layout model: one state owner, derivation, and diff.

This module owns the layout invariants for the Sessions-view tmux panes:

- **I1 (no dual-reference):** the preview session is never also a sticky session.
- **`desired()`:** the pure derivation from ``(sticky_ids, preview_id)`` to the
  ordered list of sessions occupying the non-TUI cells, including the
  five-sticky borrow rule.
- **`diff_cells()` / `orphan_panes()`:** the pure diff that lets the renderer
  swap only the cells whose content changed and reap genuine orphans, instead
  of destroying and rebuilding the whole grid.

The renderer and the view both consume these functions so a single model
governs interaction policy, persistence self-heal, and rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

MAX_STICKY = 5


def enforce_i1(sticky_ids: list[str], preview_id: str | None) -> str | None:
    """Return ``preview_id`` unless it is already sticky, in which case ``None``.

    Encodes invariant I1: the preview session is never also a sticky session.
    Applied at every mutation boundary and on persisted-state load so a corrupt
    ``preview in sticky`` snapshot self-heals.
    """
    if preview_id is not None and preview_id in sticky_ids:
        return None
    return preview_id


def desired(sticky_ids: list[str], preview_id: str | None) -> list[str]:
    """Ordered session ids for the non-TUI cells, per the layout rules.

    - ``preview_id`` is ``None`` or already sticky -> just the stickies.
    - fewer than ``MAX_STICKY`` stickies -> ``stickies + [preview]`` (preview is
      an added pane).
    - ``MAX_STICKY`` stickies and a non-sticky preview ->
      ``stickies[:MAX_STICKY - 1] + [preview]``; the last sticky pane is borrowed
      to display the preview and reverts to the last sticky when the preview
      clears (same tier -> in-place swap, never a relayout).
    """
    stickies = list(sticky_ids)
    if preview_id is None or preview_id in stickies:
        return stickies
    if len(stickies) < MAX_STICKY:
        return [*stickies, preview_id]
    return [*stickies[: MAX_STICKY - 1], preview_id]


def tier_for(session_count: int) -> int:
    """Total pane count (TUI + sessions) used to index ``LAYOUT_SPECS``."""
    return 1 + session_count


class CellOp(StrEnum):
    """Per-cell operation the renderer applies for a same-tier transition."""

    KEEP = "keep"
    SWAP = "swap"


@dataclass(frozen=True)
class CellPlan:
    """Planned operation for one non-TUI cell (1-based index into the grid)."""

    index: int
    session_id: str
    op: CellOp


@dataclass(frozen=True)
class LayoutDiff:
    """Result of diffing a previous cell assignment against a desired one.

    ``tier_changed`` selects the renderer path: when ``False`` the renderer
    applies ``cells`` (swapping only ``SWAP`` cells in place); when ``True`` the
    grid must reflow because the pane count changed.
    """

    tier_changed: bool
    cells: list[CellPlan] = field(default_factory=list)


def diff_cells(previous: list[str], desired_sessions: list[str]) -> LayoutDiff:
    """Diff two ordered cell assignments.

    When the tier (pane count) is unchanged, return a per-cell plan marking each
    cell ``KEEP`` (content unchanged) or ``SWAP`` (content changed). When the
    tier changed, return ``tier_changed=True`` with no cell plan — the renderer
    reflows the grid.
    """
    if len(previous) != len(desired_sessions):
        return LayoutDiff(tier_changed=True)
    cells = [
        CellPlan(
            index=index + 1,
            session_id=session_id,
            op=CellOp.KEEP if session_id == previous[index] else CellOp.SWAP,
        )
        for index, session_id in enumerate(desired_sessions)
    ]
    return LayoutDiff(tier_changed=False, cells=cells)


def orphan_panes(live_panes: set[str], tui_pane: str, keep_panes: set[str]) -> list[str]:
    """Live non-TUI panes that no desired cell maps to — genuine orphans to reap.

    The TUI pane and every pane backing a desired session are preserved; any
    other live pane is an orphan (e.g. left by a crashed process or a stale
    reflow) and is returned sorted for deterministic teardown.
    """
    return sorted(pane for pane in live_panes if pane != tui_pane and pane not in keep_panes)
