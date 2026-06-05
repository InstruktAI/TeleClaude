"""Data classes and layout specifications for TmuxPaneManager."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ComputerInfo:
    """SSH connection info for a computer."""

    name: str
    is_local: bool
    user: str | None = None
    host: str | None = None

    @property
    def is_remote(self) -> bool:
        """Check if this is a remote computer requiring SSH."""
        return not self.is_local

    @property
    def ssh_target(self) -> str | None:
        """Get user@host for SSH, or None if local."""
        if self.is_remote:
            return f"{self.user}@{self.host}"
        return None


@dataclass
class PaneState:
    """Tracks the state of managed tmux panes.

    Two-field source of truth.  All other state (sticky mappings,
    parent pane identity) is derived from session_to_pane filtered
    through the session catalog and _sticky_specs at query time.
    """

    session_to_pane: dict[str, str] = field(default_factory=dict)
    active_session_id: str | None = None


@dataclass
class SessionPaneSpec:
    """Pane description for layout planning."""

    session_id: str
    tmux_session_name: str | None
    computer_info: ComputerInfo | None
    is_sticky: bool
    active_agent: str = ""
    command: str | None = None


LayoutCell = Literal["T"] | int | None


@dataclass(frozen=True)
class LayoutSpec:
    """Declarative layout matrix (rows x cols)."""

    rows: int
    cols: int
    grid: list[list[LayoutCell]]


LAYOUT_SPECS: dict[int, LayoutSpec] = {
    # Total panes include the TUI pane. Session indices run clockwise from the
    # top cell nearest the TUI, so adding/removing a pane keeps existing
    # sessions in their cells (index-preserving across adjacent tiers).
    1: LayoutSpec(rows=1, cols=1, grid=[["T"]]),
    2: LayoutSpec(rows=1, cols=2, grid=[["T", 1]]),
    3: LayoutSpec(rows=2, cols=2, grid=[["T", 1], ["T", 2]]),
    4: LayoutSpec(rows=2, cols=2, grid=[["T", 1], [3, 2]]),
    # tui+4: TUI spans the full left column; sessions 1-4 fill the right 2x2.
    5: LayoutSpec(rows=2, cols=3, grid=[["T", 1, 2], ["T", 4, 3]]),
    # tui+5: session 5 takes the bottom-left cell; 1-4 keep their tui+4 cells.
    6: LayoutSpec(rows=2, cols=3, grid=[["T", 1, 2], [5, 4, 3]]),
}
