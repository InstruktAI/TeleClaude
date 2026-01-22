"""Tmux pane manager for TUI session viewing."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from instrukt_ai_logging import get_logger

from teleclaude.config import config

if TYPE_CHECKING:
    from teleclaude.cli.models import SessionInfo

logger = get_logger(__name__)


@dataclass
class ComputerInfo:
    """SSH connection info for a computer."""

    name: str
    is_local: bool
    user: str | None = None
    host: str | None = None
    tmux_binary: str | None = None

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
    """Tracks the state of managed tmux panes."""

    # Legacy single-session panes (for backward compatibility)
    parent_pane_id: str | None = None
    child_pane_id: str | None = None
    parent_session: str | None = None
    child_session: str | None = None

    def __post_init__(self) -> None:
        """Initialize mutable fields."""
        # Sticky session panes (new multi-pane layout)
        self.sticky_pane_ids: list[str] = []


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
        attach_cmd = self._build_tmux_attach_command(tmux_session_name)

        if computer_info and computer_info.is_remote:
            # Remote: SSH to the computer and attach there
            # Use -t for pseudo-terminal allocation (required for tmux)
            # Use -A for SSH agent forwarding
            ssh_target = computer_info.ssh_target
            tmux_binary = computer_info.tmux_binary or "tmux"

            # Get appearance settings from host to pass to remote
            appearance_env = self._get_appearance_env()
            env_str = " ".join(f"{k}={v}" for k, v in appearance_env.items())
            if env_str:
                env_str += " "

            cmd = f"ssh -t -A {ssh_target} '{env_str}TERM=tmux-256color {tmux_binary} -u {attach_cmd}'"
            logger.debug("Remote attach cmd for %s via %s: %s", tmux_session_name, ssh_target, cmd)
            return cmd

        # Local: use configured tmux binary
        tmux = config.computer.tmux_binary
        cmd = f"env -u TMUX TERM=tmux-256color {tmux} -u {attach_cmd}"
        logger.debug("Local attach cmd for %s: %s", tmux_session_name, cmd)
        return cmd

    def _build_tmux_attach_command(self, tmux_session_name: str) -> str:
        """Build tmux command with inline appearance tweaks before attach."""
        return (
            f'set-option -t {tmux_session_name} status-right "" \\; '
            f"set-option -t {tmux_session_name} status-right-length 0 \\; "
            f'set-option -t {tmux_session_name} status-style "bg=default" \\; '
            f"attach-session -t {tmux_session_name}"
        )

    def show_session(
        self,
        tmux_session_name: str,
        child_tmux_session_name: str | None = None,
        computer_info: ComputerInfo | None = None,
    ) -> None:
        """Show a session (and optionally its child) in the active/preview pane.

        This shows the "active" session that changes on single-click.
        Coexists with sticky sessions (double-click).

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
            "show_session: %s (child=%s, remote=%s, sticky_count=%d)",
            tmux_session_name,
            child_tmux_session_name,
            computer_info.is_remote if computer_info else False,
            len(self.state.sticky_pane_ids),
        )

        # Clean up existing active panes (preserve sticky panes)
        self._cleanup_panes()

        # Determine where to split from
        # If sticky panes exist, split from the last sticky pane (creates active pane below sticky panes)
        # Otherwise, split from TUI pane (creates active pane to the right of TUI)
        attach_cmd = self._build_attach_cmd(tmux_session_name, computer_info)
        logger.debug("show_session: attach_cmd=%s", attach_cmd)

        if self.state.sticky_pane_ids:
            # Split from last sticky pane (vertical split = below)
            target_pane = self.state.sticky_pane_ids[-1]
            parent_pane_id = self._run_tmux(
                "split-window",
                "-t",
                target_pane,
                "-v",  # Vertical split (creates pane below)
                "-P",  # Print pane info
                "-F",
                "#{pane_id}",
                attach_cmd,
            )
            logger.debug("show_session: created active pane below sticky panes: %s", parent_pane_id or "EMPTY")
        else:
            # No sticky panes - split from TUI (horizontal split = to the right)
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
            logger.debug("show_session: created active pane to right of TUI: %s", parent_pane_id or "EMPTY")

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
        """Hide active/preview session pane (preserve sticky panes)."""
        self._cleanup_panes()
        logger.debug("hide_sessions: cleaned up active pane (sticky panes preserved)")

    def toggle_session(
        self,
        tmux_session_name: str,
        child_tmux_session_name: str | None = None,
        computer_info: ComputerInfo | None = None,
    ) -> bool:
        """Toggle active/preview session pane visibility.

        This manages the "active" preview pane that shows on single-click.
        Coexists with sticky sessions (double-click).

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
            "toggle_session: %s (child=%s, computer=%s, sticky_count=%d)",
            tmux_session_name,
            child_tmux_session_name,
            computer_info.name if computer_info else "local",
            len(self.state.sticky_pane_ids),
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
        """Clean up any panes we've created (legacy single-session panes)."""
        killed_count = 0

        # Kill child pane first (if it exists)
        if self.state.child_pane_id:
            if self._get_pane_exists(self.state.child_pane_id):
                self._run_tmux("kill-pane", "-t", self.state.child_pane_id)
                killed_count += 1
                logger.debug("_cleanup_panes: killed child pane %s", self.state.child_pane_id)
            else:
                logger.debug("_cleanup_panes: child pane %s already gone", self.state.child_pane_id)

        # Kill parent pane
        if self.state.parent_pane_id:
            if self._get_pane_exists(self.state.parent_pane_id):
                self._run_tmux("kill-pane", "-t", self.state.parent_pane_id)
                killed_count += 1
                logger.debug("_cleanup_panes: killed parent pane %s", self.state.parent_pane_id)
            else:
                logger.debug("_cleanup_panes: parent pane %s already gone", self.state.parent_pane_id)

        # Reset legacy state while preserving sticky_pane_ids
        old_state = f"parent={self.state.parent_pane_id}, child={self.state.child_pane_id}"
        sticky_pane_ids = self.state.sticky_pane_ids  # Preserve sticky panes
        self.state = PaneState()
        self.state.sticky_pane_ids = sticky_pane_ids  # Restore sticky panes
        logger.debug(
            "_cleanup_panes: reset legacy state (was: %s, killed %d panes, preserved %d sticky)",
            old_state,
            killed_count,
            len(sticky_pane_ids),
        )

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

    def show_sticky_sessions(
        self,
        sticky_sessions: list[tuple["SessionInfo", bool]],
        all_sessions: list["SessionInfo"],
        get_computer_info: Callable[[str], ComputerInfo | None],
    ) -> None:
        """Show 1-5 sticky sessions using tmux's fixed layouts.

        Layouts (TUI always on left):
        - 1 session: TUI | Session (40/60)
        - 2 sessions: TUI | S1/S2 stacked (40/60, right split horizontal)
        - 3+ sessions: TUI | Grid of sessions (40/60, right uses tiled layout)

        Args:
            sticky_sessions: List of (SessionInfo, show_child) tuples
            all_sessions: All sessions (for finding children)
            get_computer_info: Function to get ComputerInfo for a computer name
        """
        if not self._in_tmux:
            logger.debug("show_sticky_sessions: not in tmux, skipping")
            return

        if not sticky_sessions:
            # No sticky sessions - clean up only sticky panes (preserve active pane)
            self._cleanup_sticky_panes()
            logger.debug("show_sticky_sessions: no sticky sessions, cleaned up sticky panes")
            return

        logger.info("show_sticky_sessions: showing %d sticky sessions", len(sticky_sessions))

        # Clean up existing sticky panes
        self._cleanup_sticky_panes()

        # If active pane is showing a session that's about to become sticky, clean it up
        # (prevents duplicate panes for the same session)
        if self.state.parent_session:
            active_session_tmux = self.state.parent_session
            logger.info(
                "show_sticky_sessions: active_pane=%s, checking against %d sticky sessions",
                active_session_tmux,
                len(sticky_sessions),
            )
            for session_info, _ in sticky_sessions:
                if session_info.tmux_session_name == active_session_tmux:
                    logger.info(
                        "show_sticky_sessions: ACTIVE PANE (%s) matches sticky session, cleaning up active pane",
                        active_session_tmux,
                    )
                    self._cleanup_panes()
                    break
        else:
            logger.info("show_sticky_sessions: no active pane to check")

        # Create all session panes
        num_sessions = len(sticky_sessions)
        session_panes: list[str] = []

        # Build list of all panes to create (with their info)
        panes_to_create: list[tuple[str, ComputerInfo | None]] = []
        for session_info, _ in sticky_sessions:
            computer_info = get_computer_info(session_info.computer or "local")
            tmux_session = session_info.tmux_session_name or ""
            if tmux_session:
                panes_to_create.append((tmux_session, computer_info))

        # Create panes based on count
        if num_sessions <= 2:
            # For 1-2 sessions: simple sequential creation
            for idx, (tmux_session, computer_info) in enumerate(panes_to_create):
                attach_cmd = self._build_attach_cmd(tmux_session, computer_info)
                if idx == 0:
                    pane_id = self._run_tmux("split-window", "-h", "-P", "-F", "#{pane_id}", attach_cmd)
                else:
                    pane_id = self._run_tmux(
                        "split-window", "-t", session_panes[0], "-v", "-P", "-F", "#{pane_id}", attach_cmd
                    )
                if pane_id:
                    session_panes.append(pane_id)
                    self.state.sticky_pane_ids.append(pane_id)

        elif num_sessions == 3:
            # For 3 sessions (4 panes total): create panes then immediately apply tiled to get 2x2 grid
            for idx, (tmux_session, computer_info) in enumerate(panes_to_create):
                attach_cmd = self._build_attach_cmd(tmux_session, computer_info)
                if idx == 0:
                    pane_id = self._run_tmux("split-window", "-h", "-P", "-F", "#{pane_id}", attach_cmd)
                else:
                    pane_id = self._run_tmux(
                        "split-window", "-t", session_panes[0], "-v", "-P", "-F", "#{pane_id}", attach_cmd
                    )
                if pane_id:
                    session_panes.append(pane_id)
                    self.state.sticky_pane_ids.append(pane_id)

            # Apply tiled layout immediately to create 2x2 grid
            self._run_tmux("select-layout", "tiled")
            logger.info("Applied tiled layout for 3 sessions (4 panes total) → 2x2 grid")
            return  # Done, skip layout section below

        else:
            # For 4-5 sessions: force 3x2 grid by creating 3 columns, then splitting vertically
            # Create first row (3 panes horizontally: TUI, S1, S2)
            first_row: list[str] = [self._tui_pane_id or ""]

            # Create S1 (right of TUI)
            if len(panes_to_create) > 0:
                tmux_session, computer_info = panes_to_create[0]
                attach_cmd = self._build_attach_cmd(tmux_session, computer_info)
                pane_id = self._run_tmux("split-window", "-h", "-P", "-F", "#{pane_id}", attach_cmd)
                if pane_id:
                    first_row.append(pane_id)
                    session_panes.append(pane_id)
                    self.state.sticky_pane_ids.append(pane_id)

            # Create S2 (right of S1)
            if len(panes_to_create) > 1:
                tmux_session, computer_info = panes_to_create[1]
                attach_cmd = self._build_attach_cmd(tmux_session, computer_info)
                pane_id = self._run_tmux(
                    "split-window", "-t", first_row[-1], "-h", "-P", "-F", "#{pane_id}", attach_cmd
                )
                if pane_id:
                    first_row.append(pane_id)
                    session_panes.append(pane_id)
                    self.state.sticky_pane_ids.append(pane_id)

            # Now split vertically to create second row
            # Split S1 to create S3 below it
            if len(panes_to_create) > 2 and len(first_row) > 1:
                tmux_session, computer_info = panes_to_create[2]
                attach_cmd = self._build_attach_cmd(tmux_session, computer_info)
                pane_id = self._run_tmux("split-window", "-t", first_row[1], "-v", "-P", "-F", "#{pane_id}", attach_cmd)
                if pane_id:
                    session_panes.append(pane_id)
                    self.state.sticky_pane_ids.append(pane_id)

            # Split S2 to create S4 below it
            if len(panes_to_create) > 3 and len(first_row) > 2:
                tmux_session, computer_info = panes_to_create[3]
                attach_cmd = self._build_attach_cmd(tmux_session, computer_info)
                pane_id = self._run_tmux("split-window", "-t", first_row[2], "-v", "-P", "-F", "#{pane_id}", attach_cmd)
                if pane_id:
                    session_panes.append(pane_id)
                    self.state.sticky_pane_ids.append(pane_id)

            # Split TUI to create S5 below it (if 5 sessions)
            if len(panes_to_create) > 4:
                tmux_session, computer_info = panes_to_create[4]
                attach_cmd = self._build_attach_cmd(tmux_session, computer_info)
                pane_id = self._run_tmux("split-window", "-t", first_row[0], "-v", "-P", "-F", "#{pane_id}", attach_cmd)
                if pane_id:
                    session_panes.append(pane_id)
                    self.state.sticky_pane_ids.append(pane_id)

            # This naturally creates 3x2 grid
            logger.info("Created 3x2 grid manually for %d sessions", num_sessions)
            return  # Skip the layout application below since we manually created the grid

        if not session_panes:
            return

        # Get window dimensions for calculations
        window_width = int(self._run_tmux("display-message", "-p", "#{window_width}") or "0")
        window_height = int(self._run_tmux("display-message", "-p", "#{window_height}") or "0")

        num_sticky = len(session_panes)
        logger.info("Applying layout for %d sticky sessions (window: %dx%d)", num_sticky, window_width, window_height)

        if num_sticky == 1:
            # 1 session: TUI (40%) | Session (60%)
            if window_width > 0:
                tui_width = int(window_width * 0.4)
                self._run_tmux("resize-pane", "-t", self._tui_pane_id or "", "-x", str(tui_width))
            logger.info("Layout: 1 session - TUI 40%%, session 60%%")

        elif num_sticky == 2:
            # 2 sessions: TUI (40%) | Session1 (top) / Session2 (bottom)
            if window_width > 0:
                tui_width = int(window_width * 0.4)
                self._run_tmux("resize-pane", "-t", self._tui_pane_id or "", "-x", str(tui_width))
            logger.info("Layout: 2 sessions - TUI 40%%, right split 50/50")

        else:
            # 3+ sessions: Use tiled layout for grid distribution
            # tmux will create 2x2 for 4 panes, 3x2 or 2x3 for 5-6 panes
            self._run_tmux("select-layout", "tiled")
            logger.info("Layout: %d sessions - tiled grid (%d total panes)", num_sticky, num_sticky + 1)

    def _find_child_session(self, parent_session_id: str, all_sessions: list["SessionInfo"]) -> str | None:
        """Find child session's tmux name for a parent session.

        Args:
            parent_session_id: Parent session ID
            all_sessions: All sessions

        Returns:
            Child tmux session name, or None
        """
        for sess in all_sessions:
            if sess.initiator_session_id == parent_session_id:
                return sess.tmux_session_name
        return None

    def _cleanup_sticky_panes(self) -> None:
        """Clean up all sticky panes."""
        for pane_id in self.state.sticky_pane_ids:
            if self._get_pane_exists(pane_id):
                self._run_tmux("kill-pane", "-t", pane_id)
        self.state.sticky_pane_ids.clear()
        logger.debug("_cleanup_sticky_panes: cleaned up sticky panes")

    def cleanup(self) -> None:
        """Clean up all managed panes. Call this when TUI exits."""
        self._cleanup_panes()
        self._cleanup_sticky_panes()
