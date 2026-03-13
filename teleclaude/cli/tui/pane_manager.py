"""Tmux pane manager for TUI session viewing."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui._pane_specs import (
    LAYOUT_SPECS,
    ComputerInfo,
    LayoutCell,
    LayoutSpec,
    PaneState,
    SessionPaneSpec,
)
from teleclaude.cli.tui.pane_layout import PaneLayoutMixin
from teleclaude.cli.tui.pane_theming import PaneThemingMixin
from teleclaude.config import config

if TYPE_CHECKING:
    from teleclaude.cli.models import SessionInfo

logger = get_logger(__name__)

__all__ = [
    "LAYOUT_SPECS",
    "ComputerInfo",
    "LayoutCell",
    "LayoutSpec",
    "PaneState",
    "SessionPaneSpec",
    "TmuxPaneManager",
]


class TmuxPaneManager(PaneLayoutMixin, PaneThemingMixin):
    """Manages tmux panes for displaying session output alongside TUI.

    Layout when session selected:
    ┌─────────────┬────────────────────┐
    │             │   Parent Session   │
    │    TUI      ├────────────────────┤
    │ (telec)     │   Worker Session   │
    │             │   (if exists)      │
    └─────────────┴────────────────────┘
    """

    TUI_SESSION_PREFIX = "tc_tui"

    def __init__(self, *, is_reload: bool = False) -> None:
        """Initialize pane manager.

        Args:
            is_reload: True on SIGUSR2 reload — preserve existing panes
                       instead of killing orphans.
        """
        self.state = PaneState()
        self._in_tmux = bool(os.environ.get("TMUX"))
        self._sticky_specs: list[SessionPaneSpec] = []
        self._active_spec: SessionPaneSpec | None = None
        self._selected_session_id: str | None = None
        self._tree_node_has_focus: bool = False
        self._layout_signature: tuple[object, ...] | None = None
        self._bg_signature: tuple[object, ...] | None = None
        self._session_catalog: dict[str, SessionInfo] = {}
        # tmux_session_name → pane_id mapping discovered during reload
        self._reload_session_panes: dict[str, str] = {}
        # Non-session panes (doc preview commands) discovered during reload
        self._reload_command_panes: list[str] = []
        # Store our own pane ID for reference
        self._tui_pane_id: str | None = None
        if self._in_tmux:
            self._tui_pane_id = self._get_current_pane_id()
            self._validate_tui_pane()
            self._init_panes(is_reload)
            # Ensure the tmux server knows tmux-256color clients support
            # truecolor.  Without this, RGB escape sequences from CLIs are
            # stripped when rendered through nested tmux attach.
            self._run_tmux("set", "-sa", "terminal-overrides", ",tmux-256color:Tc")
            self._run_tmux("set", "-sa", "terminal-features", "tmux-256color:RGB")
            # Enable focus event forwarding so embedded apps (editor) receive
            # AppBlur/AppFocus for autosave-on-focus-loss.
            self._run_tmux("set", "-g", "focus-events", "on")

    @property
    def is_available(self) -> bool:
        """Check if tmux pane management is available."""
        return self._in_tmux

    @property
    def _active_pane_id(self) -> str | None:
        """Get the active (non-sticky) pane ID from session_to_pane."""
        if self.state.active_session_id:
            return self.state.session_to_pane.get(self.state.active_session_id)
        return None

    @property
    def _active_tmux_session(self) -> str | None:
        """Get the active session's tmux session name from the catalog."""
        if self.state.active_session_id:
            session = self._session_catalog.get(self.state.active_session_id)
            if session:
                return session.tmux_session_name
        return None

    def _init_panes(self, is_reload: bool) -> None:
        """Initialize pane state on startup.

        Cold start: kill orphaned panes left by a crashed process.
        Reload: discover existing panes and preserve them for reuse.
        """
        if not self._tui_pane_id:
            return
        if is_reload:
            self._adopt_for_reload()
        else:
            self._kill_orphaned_panes()

    def _kill_orphaned_panes(self) -> None:
        """Kill orphaned non-TUI panes from a previous process (cold start)."""
        output = self._run_tmux("list-panes", "-F", "#{pane_id}")
        killed = 0
        for pane_id in output.split("\n"):
            pane_id = pane_id.strip()
            if pane_id and pane_id != self._tui_pane_id:
                self._run_tmux("kill-pane", "-t", pane_id)
                killed += 1
        if killed:
            logger.debug("Cold start: killed %d orphaned panes", killed)

    def _adopt_for_reload(self) -> None:
        """Discover existing non-TUI panes and identify their tmux sessions.

        On SIGUSR2 reload, panes from the previous process survive in tmux.
        This method discovers them and extracts which tmux session each pane
        is attached to (from pane_start_command).  The resulting mapping is
        stored in _reload_session_panes for seed_for_reload() to use.
        """
        output = self._run_tmux("list-panes", "-F", "#{pane_id}\t#{pane_start_command}")
        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            pane_id = parts[0].strip()
            if pane_id == self._tui_pane_id:
                continue

            # Extract tmux session name from the pane's attach command
            if len(parts) > 1:
                match = re.search(r"attach-session -t (\S+)", parts[1])
                if match:
                    tmux_name = match.group(1).rstrip("'\"")
                    self._reload_session_panes[tmux_name] = pane_id
                else:
                    # Non-session pane (doc preview / editor command)
                    self._reload_command_panes.append(pane_id)
            else:
                self._reload_command_panes.append(pane_id)

        logger.debug(
            "Reload: mapped %d session panes, %d command panes: %s",
            len(self._reload_session_panes),
            len(self._reload_command_panes),
            dict(self._reload_session_panes),
        )

    def _reconcile(self) -> None:
        """Prune state entries referencing dead tmux panes.

        Queries tmux once for all live pane IDs, then removes stale
        entries from session_to_pane and clears active_session_id if
        its pane is dead.
        Called at the top of apply_layout() before signature checks.
        """
        if not self._tui_pane_id:
            return

        output = self._run_tmux("list-panes", "-F", "#{pane_id}")
        live_panes = {p.strip() for p in output.split("\n") if p.strip()}

        dead_sessions = [sid for sid, pid in self.state.session_to_pane.items() if pid not in live_panes]
        for sid in dead_sessions:
            del self.state.session_to_pane[sid]

        if self.state.active_session_id and self.state.active_session_id in dead_sessions:
            self.state.active_session_id = None

        if dead_sessions:
            logger.debug(
                "_reconcile: pruned %d dead entries: %s",
                len(dead_sessions),
                dead_sessions,
            )

    def update_session_catalog(self, sessions: list[SessionInfo]) -> None:
        """Update the session catalog used for layout lookup."""
        self._session_catalog = {session.session_id: session for session in sessions}

    def seed_for_reload(
        self,
        *,
        active_session_id: str | None,
        sticky_session_ids: list[str],
        get_computer_info: Callable[[str], ComputerInfo | None],
    ) -> None:
        """Map discovered reload panes to session state and set layout signature.

        Called once after the first data refresh on SIGUSR2 reload.  Maps the
        tmux_session_name → pane_id entries from _adopt_for_reload() to
        session_to_pane via the session catalog, builds active/sticky specs,
        and pre-sets the layout signature so the first user-driven
        apply_layout() takes the lightweight _update_active_pane path.
        """
        if not self._reload_session_panes and not self._reload_command_panes:
            return

        # Kill orphaned command panes (doc previews) — their state isn't
        # persisted, so there's nothing to map them back to.
        for pane_id in self._reload_command_panes:
            if self._get_pane_exists(pane_id):
                self._run_tmux("kill-pane", "-t", pane_id)
                logger.debug("seed_for_reload: killed orphan command pane %s", pane_id)
        self._reload_command_panes.clear()

        if not self._reload_session_panes:
            return

        reload_map = self._reload_session_panes

        sticky_specs = []
        for session_id in sticky_session_ids:
            session = self._session_catalog.get(session_id)
            if not session or not session.tmux_session_name:
                continue
            sticky_specs.append(
                SessionPaneSpec(
                    session_id=session.session_id,
                    tmux_session_name=session.tmux_session_name,
                    computer_info=get_computer_info(session.computer or "local"),
                    is_sticky=True,
                    active_agent=session.active_agent or "",
                )
            )
            pane_id = reload_map.get(session.tmux_session_name)
            if pane_id:
                self.state.session_to_pane[session_id] = pane_id
        self._sticky_specs = sticky_specs

        if active_session_id:
            session = self._session_catalog.get(active_session_id)
            if session and session.tmux_session_name:
                self._active_spec = SessionPaneSpec(
                    session_id=session.session_id,
                    tmux_session_name=session.tmux_session_name,
                    computer_info=get_computer_info(session.computer or "local"),
                    is_sticky=False,
                    active_agent=session.active_agent or "",
                )
                self.state.active_session_id = session.session_id
                pane_id = reload_map.get(session.tmux_session_name)
                if pane_id:
                    self.state.session_to_pane[session.session_id] = pane_id

        # Kill any reload panes that couldn't be mapped to live sessions.
        # This prevents orphan panes when session data changed between reloads.
        mapped_panes = set(self.state.session_to_pane.values())
        for tmux_name, pane_id in reload_map.items():
            if pane_id not in mapped_panes and self._get_pane_exists(pane_id):
                self._run_tmux("kill-pane", "-t", pane_id)
                logger.debug("seed_for_reload: killed unmapped session pane %s (tmux=%s)", pane_id, tmux_name)

        self._layout_signature = self._compute_layout_signature()
        self._reload_session_panes.clear()

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
        """Get the pane ID where this TUI process is running.

        Prefers TMUX_PANE (set per-pane by tmux, stable across os.execvp
        reloads) over display-message (which returns the currently FOCUSED
        pane — wrong if the user clicked a session pane before reload).
        """
        pane_id = os.environ.get("TMUX_PANE")
        if pane_id:
            return pane_id
        output = self._run_tmux("display-message", "-p", "#{pane_id}")
        return output if output else None

    def _validate_tui_pane(self) -> None:
        """Verify _tui_pane_id belongs to the TUI tmux session.

        If telec is started from inside an agent pane (e.g., tc_38ace093),
        TMUX_PANE points at the agent pane, not the TUI pane. split-window
        would then create panes inside the agent's tmux window — a hard-to-
        diagnose orphan pane bug.  Disable pane management when detected.
        """
        if not self._tui_pane_id:
            return
        session_name = self._run_tmux(
            "display-message",
            "-t",
            self._tui_pane_id,
            "-p",
            "#{session_name}",
        )
        if session_name and not session_name.startswith(self.TUI_SESSION_PREFIX):
            logger.error(
                "TUI pane %s belongs to session '%s', not '%s' — disabling pane management to prevent orphan splits",
                self._tui_pane_id,
                session_name,
                self.TUI_SESSION_PREFIX,
            )
            self._tui_pane_id = None
            self._in_tmux = False

    def get_active_pane_id(self) -> str | None:
        """Return the active pane id for the current tmux client."""
        if not self._in_tmux:
            return None
        return self._get_current_pane_id()

    def get_session_id_for_pane(self, pane_id: str) -> str | None:
        """Return session_id mapped to a pane id, if known."""
        if not pane_id:
            return None
        for session_id, mapped_pane in self.state.session_to_pane.items():
            if mapped_pane == pane_id:
                return session_id
        return None

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

        # Local: use configured tmux binary with nested attach
        tmux = config.computer.tmux_binary
        cmd = f"env -u TMUX TERM=tmux-256color {tmux} -u {attach_cmd}"
        logger.debug("Local attach cmd for %s: %s", tmux_session_name, cmd)
        return cmd

    def _build_tmux_attach_command(self, tmux_session_name: str) -> str:
        """Build tmux command with inline appearance tweaks before attach."""
        # Enable truecolor passthrough for nested tmux clients.  The server
        # typically has Tc overrides for xterm-256color but NOT tmux-256color,
        # which is what TERM is set to in _build_attach_cmd.  Without this,
        # RGB color sequences emitted by CLIs (Gemini, Claude, Codex) are
        # stripped and the output appears black-and-white.
        return (
            f"set -sa terminal-overrides ',tmux-256color:Tc' \\; "
            f"set -sa terminal-features 'tmux-256color:RGB' \\; "
            f"set-option -t {tmux_session_name} status off \\; "
            f"attach-session -t {tmux_session_name}"
        )

    def show_session(
        self,
        tmux_session_name: str,
        active_agent: str,
        computer_info: ComputerInfo | None = None,
        session_id: str | None = None,
    ) -> None:
        """Show a session in the active/preview pane.

        This shows the "active" session that changes on single-click.
        Coexists with sticky sessions (double-click).

        Args:
            tmux_session_name: The session's tmux session name
            active_agent: Agent name for color styling
            computer_info: Computer info for SSH (None = local)
        """
        if not self._in_tmux:
            logger.debug("show_session: not in tmux, skipping")
            return

        logger.debug(
            "show_session: %s (agent=%s, remote=%s, sticky_count=%d)",
            tmux_session_name,
            active_agent,
            computer_info.is_remote if computer_info else False,
            len(self._sticky_specs),
        )

        spec_session_id = session_id or tmux_session_name
        self._active_spec = SessionPaneSpec(
            session_id=spec_session_id,
            tmux_session_name=tmux_session_name,
            computer_info=computer_info,
            is_sticky=False,
            active_agent=active_agent,
        )
        if self._layout_is_unchanged():
            self.focus_pane_for_session(spec_session_id)
            return
        self._render_layout()

    def hide_sessions(self) -> None:
        """Hide active/preview session pane (preserve sticky panes)."""
        self._active_spec = None
        self.state.active_session_id = None
        self._render_layout()
        logger.debug("hide_sessions: cleared active pane")

    def toggle_session(
        self,
        tmux_session_name: str,
        active_agent: str,
        computer_info: ComputerInfo | None = None,
        session_id: str | None = None,
    ) -> bool:
        """Toggle active/preview session pane visibility.

        If already showing this session, hide it.
        If showing different session or none, show this one.

        Args:
            tmux_session_name: The session's tmux session name
            active_agent: Agent name for color styling
            computer_info: Computer info for SSH (None = local)

        Returns:
            True if now showing, False if now hidden
        """
        if not self._in_tmux:
            logger.debug("toggle_session: not in tmux, returning False")
            return False

        logger.debug(
            "toggle_session: %s (agent=%s, computer=%s, sticky_count=%d)",
            tmux_session_name,
            active_agent,
            computer_info.name if computer_info else "local",
            len(self._sticky_specs),
        )

        # If already showing this session, hide it
        if self._active_tmux_session == tmux_session_name:
            logger.debug("toggle_session: hiding (already showing)")
            self.hide_sessions()
            return False

        # Otherwise show it
        logger.debug("toggle_session: showing session")
        self.show_session(
            tmux_session_name,
            active_agent,
            computer_info,
            session_id=session_id,
        )
        return True

    @property
    def active_session(self) -> str | None:
        """Get the currently displayed session's tmux session name."""
        return self._active_tmux_session

    def _cleanup_panes(self) -> None:
        """Clean up active/preview pane only."""
        active_pane = self._active_pane_id
        if active_pane and self._get_pane_exists(active_pane):
            self._run_tmux("kill-pane", "-t", active_pane)
        if self.state.active_session_id:
            self.state.session_to_pane.pop(self.state.active_session_id, None)
            self.state.active_session_id = None

    def _cleanup_all_session_panes(self) -> None:
        """Clean up all session panes (active + sticky)."""
        for pane_id in set(self.state.session_to_pane.values()):
            if pane_id and self._get_pane_exists(pane_id):
                self._run_tmux("kill-pane", "-t", pane_id)

        self.state.session_to_pane.clear()
        self.state.active_session_id = None

    def show_sticky_sessions(
        self,
        sticky_sessions: list[SessionInfo],
        get_computer_info: Callable[[str], ComputerInfo | None],
    ) -> None:
        """Show 1-5 sticky sessions using tmux's fixed layouts.

        Args:
            sticky_sessions: List of SessionInfo objects
            get_computer_info: Function to get ComputerInfo for a computer name
        """
        if not self._in_tmux:
            logger.debug("show_sticky_sessions: not in tmux, skipping")
            return

        logger.info("show_sticky_sessions: showing %d sticky sessions", len(sticky_sessions))

        sticky_specs: list[SessionPaneSpec] = []
        for session_info in sticky_sessions:
            tmux_session = session_info.tmux_session_name or ""
            if not tmux_session:
                continue
            sticky_specs.append(
                SessionPaneSpec(
                    session_id=session_info.session_id,
                    tmux_session_name=tmux_session,
                    computer_info=get_computer_info(session_info.computer or "local"),
                    is_sticky=True,
                    active_agent=session_info.active_agent,
                )
            )

        self._sticky_specs = sticky_specs
        if self._layout_is_unchanged():
            return
        self._render_layout()

    def _cleanup_sticky_panes(self) -> None:
        """Clean up all sticky panes (those tracked via _sticky_specs)."""
        sticky_ids = {spec.session_id for spec in self._sticky_specs}
        killed = 0
        for session_id in list(self.state.session_to_pane):
            if session_id in sticky_ids:
                pane_id = self.state.session_to_pane.pop(session_id)
                if self._get_pane_exists(pane_id):
                    self._run_tmux("kill-pane", "-t", pane_id)
                    killed += 1
        if killed:
            logger.debug("_cleanup_sticky_panes: killed %d sticky panes", killed)

    def cleanup(self) -> None:
        """Clean up all managed panes. Call this when TUI exits."""
        self._cleanup_all_session_panes()

    def focus_pane_for_session(self, session_id: str) -> bool:
        """Focus the pane showing a specific session.

        Uses direct select-pane without existence checks to avoid
        spawning extra tmux subprocesses on the hot path.

        Args:
            session_id: The session ID to focus

        Returns:
            True if pane was found and focused, False otherwise
        """
        if not self._in_tmux:
            return False

        pane_id = self.state.session_to_pane.get(session_id)
        if pane_id:
            self._run_tmux("select-pane", "-t", pane_id)
            logger.debug("Focused pane %s for session %s", pane_id, session_id)
            return True

        logger.debug("No pane found for session %s", session_id)
        return False
