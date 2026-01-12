"""Tmux pane manager for TUI session viewing."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from instrukt_ai_logging import get_logger

from teleclaude.config import config

logger = get_logger(__name__)


@dataclass
class ComputerInfo:
    """SSH connection info for a computer."""

    name: str
    user: str | None = None
    host: str | None = None

    @property
    def is_remote(self) -> bool:
        """Check if this is a remote computer requiring SSH."""
        return bool(self.host and self.user)

    @property
    def ssh_target(self) -> str | None:
        """Get user@host for SSH, or None if local."""
        if self.is_remote:
            return f"{self.user}@{self.host}"
        return None


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

    def _get_appearance_env(self) -> dict[str, str]:
        """Get current appearance settings from the host.

        Captures APPEARANCE_MODE and TERMINAL_BG from the local machine
        to pass to remote sessions via SSH.

        Returns:
            Dict with appearance env vars, empty if detection fails.
        """
        env_vars: dict[str, str] = {}
        appearance_bin = os.path.expanduser("~/.local/bin/appearance")

        if not os.path.exists(appearance_bin):
            return env_vars

        # Get mode
        try:
            result = subprocess.run(
                [appearance_bin, "get-mode"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                env_vars["APPEARANCE_MODE"] = result.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass

        # Get terminal background
        try:
            result = subprocess.run(
                [appearance_bin, "get-terminal-bg"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                env_vars["TERMINAL_BG"] = result.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass

        return env_vars

    def _build_attach_cmd(
        self,
        tmux_session_name: str,
        computer_info: ComputerInfo | None = None,
    ) -> str:
        """Build the command to attach to a tmux session.

        For local sessions: direct tmux attach
        For remote sessions: SSH with tmux attach (includes appearance env vars)

        Args:
            tmux_session_name: The tmux session name to attach to
            computer_info: Computer info for SSH (None = local)

        Returns:
            Command string to execute
        """
        if computer_info and computer_info.is_remote:
            # Remote: SSH to the computer and attach there
            # Use plain 'tmux' - remote machine has its own tmux binary
            # Use -t for pseudo-terminal allocation (required for tmux)
            # Use -A for SSH agent forwarding
            ssh_target = computer_info.ssh_target

            # Get appearance settings from host to pass to remote
            appearance_env = self._get_appearance_env()
            env_str = " ".join(f"{k}={v}" for k, v in appearance_env.items())
            if env_str:
                env_str += " "

            cmd = f"ssh -t -A {ssh_target} '{env_str}TERM=tmux-256color tmux -u attach-session -t {tmux_session_name}'"
            logger.debug("Remote attach cmd for %s via %s: %s", tmux_session_name, ssh_target, cmd)
            return cmd

        # Local: use configured tmux binary
        tmux = config.computer.tmux_binary
        cmd = f"env -u TMUX TERM=tmux-256color {tmux} -u attach-session -t {tmux_session_name}"
        logger.debug("Local attach cmd for %s: %s", tmux_session_name, cmd)
        return cmd

    def show_session(
        self,
        tmux_session_name: str,
        child_tmux_session_name: str | None = None,
        computer_info: ComputerInfo | None = None,
    ) -> None:
        """Show a session (and optionally its child) in the right panes.

        Args:
            tmux_session_name: The parent session's tmux session name
            child_tmux_session_name: Optional child/worker session name
            computer_info: Computer info for SSH (None = local)
        """
        if not self._in_tmux:
            logger.debug("show_session: not in tmux, skipping")
            return

        # Check if we're already showing this exact configuration
        if self.state.parent_session == tmux_session_name and self.state.child_session == child_tmux_session_name:
            logger.debug("show_session: already showing %s, skipping", tmux_session_name)
            return

        logger.debug(
            "show_session: %s (child=%s, remote=%s)",
            tmux_session_name,
            child_tmux_session_name,
            computer_info.is_remote if computer_info else False,
        )

        # Clean up existing panes if showing different sessions
        self._cleanup_panes()

        # Create parent pane on the right (60% width, TUI keeps 40%)
        attach_cmd = self._build_attach_cmd(tmux_session_name, computer_info)
        logger.debug("show_session: attach_cmd=%s", attach_cmd)

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
        logger.debug("show_session: parent_pane_id=%s", parent_pane_id or "EMPTY")

        if parent_pane_id:
            self.state.parent_pane_id = parent_pane_id
            self.state.parent_session = tmux_session_name

        # If there's a child session, split the right pane vertically
        # Note: child sessions are assumed to be on the same computer as parent
        if child_tmux_session_name and parent_pane_id:
            child_attach_cmd = self._build_attach_cmd(child_tmux_session_name, computer_info)
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
        computer_info: ComputerInfo | None = None,
    ) -> bool:
        """Toggle session pane visibility.

        If already showing this session, hide it.
        If showing different session or none, show this one.

        Args:
            tmux_session_name: The session's tmux session name
            child_tmux_session_name: Optional child/worker session name
            computer_info: Computer info for SSH (None = local)

        Returns:
            True if now showing, False if now hidden
        """
        if not self._in_tmux:
            logger.debug("toggle_session: not in tmux, returning False")
            return False

        logger.debug(
            "toggle_session: %s (child=%s, computer=%s)",
            tmux_session_name,
            child_tmux_session_name,
            computer_info.name if computer_info else "local",
        )

        # If already showing this session, hide it
        if self.state.parent_session == tmux_session_name:
            logger.debug("toggle_session: hiding (already showing)")
            self.hide_sessions()
            return False

        # Otherwise show it
        logger.debug("toggle_session: showing session")
        self.show_session(tmux_session_name, child_tmux_session_name, computer_info)
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

    def update_child_session(
        self,
        child_tmux_session_name: str | None,
        computer_info: ComputerInfo | None = None,
    ) -> None:
        """Update just the child session pane.

        Args:
            child_tmux_session_name: New child session name, or None to remove
            computer_info: Computer info for SSH (None = local)
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
            child_attach_cmd = self._build_attach_cmd(child_tmux_session_name, computer_info)
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
