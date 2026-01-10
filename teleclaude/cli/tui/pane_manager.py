"""Tmux pane manager for TUI session viewing."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from teleclaude.config import config


@dataclass
class PaneState:
    """Tracks the state of managed tmux panes."""

    # Pane IDs we've created (for cleanup)
    parent_pane_id: str | None = None
    child_pane_id: str | None = None
    # Session info for what's displayed
    parent_session: str | None = None
    child_session: str | None = None


class TmuxPaneManager:
    """Manages tmux panes for displaying session output alongside TUI.

    Layout when session selected:
    ┌─────────────┬────────────────────┐
    │             │   Parent Session   │
    │    TUI      ├────────────────────┤
    │ (telec)     │   Worker Session   │
    │             │   (if exists)      │
    └─────────────┴────────────────────┘
    """

    def __init__(self) -> None:
        """Initialize pane manager."""
        self.state = PaneState()
        self._in_tmux = bool(os.environ.get("TMUX"))
        # Store our own pane ID for reference
        self._tui_pane_id: str | None = None
        if self._in_tmux:
            self._tui_pane_id = self._get_current_pane_id()

    @property
    def is_available(self) -> bool:
        """Check if tmux pane management is available."""
        return self._in_tmux

    def _run_tmux(self, *args: str) -> str:
        """Run a tmux command and return output.

        Args:
            *args: tmux command arguments

        Returns:
            Command output (stdout)
        """
        try:
            result = subprocess.run(
                [config.computer.tmux_binary, *args],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return ""

    def _get_current_pane_id(self) -> str | None:
        """Get the current pane ID."""
        output = self._run_tmux("display-message", "-p", "#{pane_id}")
        return output if output else None

    def _get_pane_exists(self, pane_id: str) -> bool:
        """Check if a pane still exists."""
        output = self._run_tmux("list-panes", "-F", "#{pane_id}")
        return pane_id in output.split("\n")

    def show_session(
        self,
        tmux_session_name: str,
        child_tmux_session_name: str | None = None,
    ) -> None:
        """Show a session (and optionally its child) in the right panes.

        Args:
            tmux_session_name: The parent session's tmux session name
            child_tmux_session_name: Optional child/worker session name
        """
        if not self._in_tmux:
            return

        # Check if we're already showing this exact configuration
        if self.state.parent_session == tmux_session_name and self.state.child_session == child_tmux_session_name:
            return

        # Clean up existing panes if showing different sessions
        self._cleanup_panes()

        # Create parent pane on the right (60% width, TUI keeps 40%)
        # Use TERM=tmux-256color for proper rendering, -u for UTF-8
        # Hide nested status bar with "set status off"
        tmux = config.computer.tmux_binary
        attach_cmd = (
            f"env -u TMUX TERM=tmux-256color {tmux} -u attach-session -t {tmux_session_name} \\; set status off"
        )
        parent_pane_id = self._run_tmux(
            "split-window",
            "-h",  # Horizontal split (creates pane to the right)
            "-p",
            "60",  # 60% for session pane, 40% for TUI
            "-P",  # Print pane info
            "-F",
            "#{pane_id}",
            attach_cmd,
        )
        if parent_pane_id:
            self.state.parent_pane_id = parent_pane_id
            self.state.parent_session = tmux_session_name

        # If there's a child session, split the right pane vertically
        if child_tmux_session_name and parent_pane_id:
            child_attach_cmd = f"env -u TMUX TERM=tmux-256color {tmux} -u attach-session -t {child_tmux_session_name} \\; set status off"
            child_pane_id = self._run_tmux(
                "split-window",
                "-t",
                parent_pane_id,
                "-v",  # Vertical split (creates pane below)
                "-P",
                "-F",
                "#{pane_id}",
                child_attach_cmd,
            )
            if child_pane_id:
                self.state.child_pane_id = child_pane_id
                self.state.child_session = child_tmux_session_name

        # Focus stays on the new session pane (don't return to TUI)

    def hide_sessions(self) -> None:
        """Hide all session panes (return to TUI-only view)."""
        self._cleanup_panes()

    def toggle_session(
        self,
        tmux_session_name: str,
        child_tmux_session_name: str | None = None,
    ) -> bool:
        """Toggle session pane visibility.

        If already showing this session, hide it.
        If showing different session or none, show this one.

        Args:
            tmux_session_name: The session's tmux session name
            child_tmux_session_name: Optional child/worker session name

        Returns:
            True if now showing, False if now hidden
        """
        if not self._in_tmux:
            return False

        # If already showing this session, hide it
        if self.state.parent_session == tmux_session_name:
            self.hide_sessions()
            return False

        # Otherwise show it
        self.show_session(tmux_session_name, child_tmux_session_name)
        return True

    @property
    def active_session(self) -> str | None:
        """Get the currently displayed session name."""
        return self.state.parent_session

    def _cleanup_panes(self) -> None:
        """Clean up any panes we've created."""
        # Kill child pane first (if it exists)
        if self.state.child_pane_id and self._get_pane_exists(self.state.child_pane_id):
            self._run_tmux("kill-pane", "-t", self.state.child_pane_id)

        # Kill parent pane
        if self.state.parent_pane_id and self._get_pane_exists(self.state.parent_pane_id):
            self._run_tmux("kill-pane", "-t", self.state.parent_pane_id)

        # Reset state
        self.state = PaneState()

    def update_child_session(self, child_tmux_session_name: str | None) -> None:
        """Update just the child session pane.

        Args:
            child_tmux_session_name: New child session name, or None to remove
        """
        if not self._in_tmux or not self.state.parent_pane_id:
            return

        # If same child, nothing to do
        if self.state.child_session == child_tmux_session_name:
            return

        # Kill existing child pane if any
        if self.state.child_pane_id and self._get_pane_exists(self.state.child_pane_id):
            self._run_tmux("kill-pane", "-t", self.state.child_pane_id)
            self.state.child_pane_id = None
            self.state.child_session = None

        # Create new child pane if requested
        if child_tmux_session_name and self.state.parent_pane_id:
            tmux = config.computer.tmux_binary
            child_attach_cmd = f"env -u TMUX TERM=tmux-256color {tmux} -u attach-session -t {child_tmux_session_name} \\; set status off"
            child_pane_id = self._run_tmux(
                "split-window",
                "-t",
                self.state.parent_pane_id,
                "-v",
                "-P",
                "-F",
                "#{pane_id}",
                child_attach_cmd,
            )
            if child_pane_id:
                self.state.child_pane_id = child_pane_id
                self.state.child_session = child_tmux_session_name

        # Focus stays on new pane (don't return to TUI)

    def cleanup(self) -> None:
        """Clean up all managed panes. Call this when TUI exits."""
        self._cleanup_panes()
