"""Tmux pane manager for TUI session viewing."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Literal

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui import theme
from teleclaude.config import config

if TYPE_CHECKING:
    from teleclaude.cli.models import SessionInfo
    from teleclaude.cli.tui.state import DocPreviewState

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

    parent_pane_id: str | None = None
    parent_session: str | None = None
    parent_spec_id: str | None = None

    def __post_init__(self) -> None:
        """Initialize mutable fields."""
        # Sticky session panes (new multi-pane layout)
        self.sticky_pane_ids: list[str] = []
        # Map session_id → pane_id for sticky sessions
        self.sticky_session_to_pane: dict[str, str] = {}
        # All session panes (active + sticky)
        self.session_pane_ids: list[str] = []
        # Map session_id → pane_id for any session pane
        self.session_to_pane: dict[str, str] = {}


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
    # Total panes include the TUI pane.
    1: LayoutSpec(rows=1, cols=1, grid=[["T"]]),
    2: LayoutSpec(rows=1, cols=2, grid=[["T", 1]]),
    3: LayoutSpec(rows=2, cols=2, grid=[["T", 1], ["T", 2]]),
    4: LayoutSpec(rows=2, cols=2, grid=[["T", 1], [3, 2]]),
    5: LayoutSpec(rows=2, cols=3, grid=[["T", 1, 3], [None, 2, 4]]),
    6: LayoutSpec(rows=2, cols=3, grid=[["T", 1, 3], [5, 2, 4]]),
}


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
        self._sticky_specs: list[SessionPaneSpec] = []
        self._active_spec: SessionPaneSpec | None = None
        self._selected_session_id: str | None = None
        self._tree_node_has_focus: bool = False
        self._layout_signature: tuple[object, ...] | None = None
        self._session_catalog: dict[str, "SessionInfo"] = {}
        # Store our own pane ID for reference
        self._tui_pane_id: str | None = None
        if self._in_tmux:
            self._tui_pane_id = self._get_current_pane_id()

    @property
    def is_available(self) -> bool:
        """Check if tmux pane management is available."""
        return self._in_tmux

    def update_session_catalog(self, sessions: list["SessionInfo"]) -> None:
        """Update the session catalog used for layout lookup."""
        self._session_catalog = {session.session_id: session for session in sessions}

    def apply_layout(
        self,
        *,
        active_session_id: str | None,
        sticky_session_ids: list[str],
        get_computer_info: Callable[[str], ComputerInfo | None],
        active_doc_preview: "DocPreviewState | None" = None,
        sticky_doc_previews: list[object] | None = None,
        selected_session_id: str | None = None,
        tree_node_has_focus: bool = False,
        focus: bool = True,
    ) -> None:
        """Apply a deterministic layout from session ids."""
        if not self._in_tmux:
            return
        self._selected_session_id = selected_session_id
        self._tree_node_has_focus = tree_node_has_focus

        sticky_specs: list[SessionPaneSpec] = []
        for session_id in sticky_session_ids:
            session = self._session_catalog.get(session_id)
            if not session:
                continue
            tmux_session = session.tmux_session_name or ""
            if not tmux_session:
                continue
            sticky_specs.append(
                SessionPaneSpec(
                    session_id=session.session_id,
                    tmux_session_name=tmux_session,
                    computer_info=get_computer_info(session.computer or "local"),
                    is_sticky=True,
                    active_agent=session.active_agent,
                )
            )
        active_spec: SessionPaneSpec | None = None
        if active_session_id:
            session = self._session_catalog.get(active_session_id)
            if session and session.tmux_session_name:
                active_spec = SessionPaneSpec(
                    session_id=session.session_id,
                    tmux_session_name=session.tmux_session_name,
                    computer_info=get_computer_info(session.computer or "local"),
                    is_sticky=False,
                    active_agent=session.active_agent,
                )
        elif active_doc_preview:
            active_spec = SessionPaneSpec(
                session_id=f"doc:{active_doc_preview.doc_id}",
                tmux_session_name=None,
                computer_info=None,
                is_sticky=False,
                active_agent="",
                command=active_doc_preview.command,
            )

        self._sticky_specs = sticky_specs
        self._active_spec = active_spec

        if self._layout_is_unchanged():
            if active_spec and self.state.parent_spec_id != active_spec.session_id:
                self._update_active_pane(active_spec)
            if focus and active_spec:
                self.focus_pane_for_session(active_spec.session_id)
            self._sync_sticky_mappings()
            if not active_spec:
                self._clear_active_state_if_sticky()
            self._refresh_session_pane_backgrounds()
            self._set_tui_pane_background()
            return

        self._render_layout()

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

        if self.state.parent_pane_id and pane_id == self.state.parent_pane_id and self.state.parent_session:
            for session in self._session_catalog.values():
                if session.tmux_session_name == self.state.parent_session:
                    return session.session_id

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
        return f"set-option -t {tmux_session_name} status off \\; attach-session -t {tmux_session_name}"

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
        self._render_layout()
        self.state.parent_pane_id = None
        self.state.parent_session = None
        self.state.parent_spec_id = None
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
            len(self.state.sticky_pane_ids),
        )

        # If already showing this session, hide it
        if self.state.parent_session == tmux_session_name:
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
        """Get the currently displayed session name."""
        return self.state.parent_session

    def _cleanup_panes(self) -> None:
        """Clean up active/preview panes only."""
        if self.state.parent_pane_id and self._get_pane_exists(self.state.parent_pane_id):
            self._run_tmux("kill-pane", "-t", self.state.parent_pane_id)
        self.state.parent_pane_id = None
        self.state.parent_session = None
        self.state.parent_spec_id = None

    def _cleanup_all_session_panes(self) -> None:
        """Clean up all session panes (active + sticky)."""
        pane_ids: list[str] = []
        pane_ids.extend(self.state.session_pane_ids)
        pane_ids.extend(self.state.sticky_pane_ids)
        if self.state.parent_pane_id:
            pane_ids.append(self.state.parent_pane_id)

        seen: set[str] = set()
        for pane_id in pane_ids:
            if not pane_id or pane_id in seen:
                continue
            seen.add(pane_id)
            if self._get_pane_exists(pane_id):
                self._run_tmux("kill-pane", "-t", pane_id)

        self.state.session_pane_ids.clear()
        self.state.session_to_pane.clear()
        self.state.sticky_pane_ids.clear()
        self.state.sticky_session_to_pane.clear()
        self.state.parent_pane_id = None
        self.state.parent_session = None
        self.state.parent_spec_id = None

    def _build_session_specs(self) -> list[SessionPaneSpec]:
        session_specs: list[SessionPaneSpec] = list(self._sticky_specs)
        if self._active_spec and not any(spec.session_id == self._active_spec.session_id for spec in session_specs):
            session_specs.append(self._active_spec)
        if len(session_specs) > 5:
            session_specs = session_specs[:5]
        return session_specs

    def _compute_layout_signature(self) -> tuple[object, ...] | None:
        session_specs = self._build_session_specs()
        total_panes = 1 + len(session_specs)
        layout = LAYOUT_SPECS.get(total_panes)
        if not layout:
            return None
        # Track structural layout only — sticky IDs + whether an active slot
        # exists.  The active session_id is intentionally excluded so that
        # switching the preview between non-sticky sessions takes the
        # lightweight _update_active_pane path (respawn-pane) instead of
        # tearing down and recreating all tmux panes (_render_layout).
        structural_keys = tuple(spec.session_id if spec.is_sticky else "__active__" for spec in session_specs)
        return (
            layout.rows,
            layout.cols,
            tuple(tuple(row) for row in layout.grid),
            structural_keys,
        )

    def _sync_sticky_mappings(self) -> None:
        """Sync sticky pane mappings without rebuilding layout."""
        sticky_panes: list[str] = []
        sticky_map: dict[str, str] = {}
        for spec in self._sticky_specs:
            pane_id = self.state.session_to_pane.get(spec.session_id)
            if pane_id and self._get_pane_exists(pane_id):
                sticky_panes.append(pane_id)
                sticky_map[spec.session_id] = pane_id
        self.state.sticky_pane_ids = sticky_panes
        self.state.sticky_session_to_pane = sticky_map

    def _clear_active_state_if_sticky(self) -> None:
        """Clear active pane metadata when it has been promoted to sticky."""
        if not self.state.parent_spec_id:
            return
        if any(spec.session_id == self.state.parent_spec_id for spec in self._sticky_specs):
            self.state.parent_session = None
            self.state.parent_spec_id = None
            self.state.parent_pane_id = None

    def _refresh_session_pane_backgrounds(self) -> None:
        """Refresh pane backgrounds for all tracked session panes."""
        if not self._in_tmux:
            return

        for session_id, pane_id in self.state.session_to_pane.items():
            if not self._get_pane_exists(pane_id):
                continue
            if session_id.startswith("doc:"):
                self._set_doc_pane_background(pane_id)
                continue

            session = self._session_catalog.get(session_id)
            if not session or not session.tmux_session_name:
                continue

            self._set_pane_background(
                pane_id,
                session.tmux_session_name,
                session.active_agent,
                is_tree_selected=self._is_tree_selected_session(session_id),
            )

    def _update_active_pane(self, active_spec: SessionPaneSpec) -> None:
        """Swap the active pane content without rebuilding layout."""
        if not self._in_tmux:
            return
        if not self.state.parent_pane_id or not self._get_pane_exists(self.state.parent_pane_id):
            self._render_layout()
            return

        attach_cmd = self._build_pane_command(active_spec)
        # Force replace running process; without -k, respawn-pane can no-op.
        self._run_tmux("respawn-pane", "-k", "-t", self.state.parent_pane_id, attach_cmd)

        stale_ids = [sid for sid, pid in self.state.session_to_pane.items() if pid == self.state.parent_pane_id]
        for sid in stale_ids:
            self.state.session_to_pane.pop(sid, None)
        self.state.session_to_pane[active_spec.session_id] = self.state.parent_pane_id
        self.state.parent_session = active_spec.tmux_session_name
        self.state.parent_spec_id = active_spec.session_id

        if active_spec.tmux_session_name:
            self._set_pane_background(
                self.state.parent_pane_id,
                active_spec.tmux_session_name,
                active_spec.active_agent,
                is_tree_selected=self._is_tree_selected_session(active_spec.session_id),
            )
        else:
            self._set_doc_pane_background(self.state.parent_pane_id)

    def _layout_is_unchanged(self) -> bool:
        signature = self._compute_layout_signature()
        if signature is None:
            return False
        if signature == self._layout_signature:
            return True
        self._layout_signature = signature
        return False

    def _render_layout(self) -> None:
        """Render panes deterministically from the layout matrix."""
        if not self._in_tmux:
            return
        if not self._tui_pane_id:
            self._tui_pane_id = self._get_current_pane_id()
        if not self._tui_pane_id:
            logger.warning("_render_layout: missing TUI pane id")
            return

        session_specs = self._build_session_specs()
        if len(session_specs) > 5:
            logger.warning("_render_layout: truncating session panes from %d to 5", len(session_specs))

        total_panes = 1 + len(session_specs)
        layout = LAYOUT_SPECS.get(total_panes)
        if not layout:
            logger.warning("_render_layout: no layout for total=%d", total_panes)
            return

        self._cleanup_all_session_panes()

        def get_spec(index: int) -> SessionPaneSpec | None:
            if index <= 0 or index > len(session_specs):
                return None
            return session_specs[index - 1]

        col_top_panes: list[str | None] = [self._tui_pane_id] + [None] * (layout.cols - 1)

        for col in range(1, layout.cols):
            cell = layout.grid[0][col]
            if not isinstance(cell, int):
                continue
            spec = get_spec(cell)
            if not spec:
                continue
            attach_cmd = self._build_pane_command(spec)
            if col == 1:
                split_args = ["-t", self._tui_pane_id, "-h"]
                if layout.cols == 2 and total_panes <= 3:
                    split_args.extend(["-p", "60"])
                split_args.append("-d")
                pane_id = self._run_tmux(
                    "split-window",
                    *split_args,
                    "-P",
                    "-F",
                    "#{pane_id}",
                    attach_cmd,
                )
            else:
                pane_id = self._run_tmux(
                    "split-window",
                    "-t",
                    col_top_panes[col - 1] or "",
                    "-h",
                    "-d",
                    "-P",
                    "-F",
                    "#{pane_id}",
                    attach_cmd,
                )
            if pane_id:
                col_top_panes[col] = pane_id
                self._track_session_pane(spec, pane_id)

        if layout.cols == 3:
            self._run_tmux("select-layout", "even-horizontal")

        if layout.rows > 1:
            for col in range(layout.cols):
                cell = layout.grid[1][col]
                if not isinstance(cell, int):
                    continue
                spec = get_spec(cell)
                if not spec:
                    continue
                target_pane = col_top_panes[col]
                if not target_pane:
                    continue
                attach_cmd = self._build_pane_command(spec)
                pane_id = self._run_tmux(
                    "split-window",
                    "-t",
                    target_pane,
                    "-v",
                    "-d",
                    "-P",
                    "-F",
                    "#{pane_id}",
                    attach_cmd,
                )
                if pane_id:
                    self._track_session_pane(spec, pane_id)

        if self._active_spec:
            active_pane_id = self.state.session_to_pane.get(self._active_spec.session_id)
            if active_pane_id:
                self.state.parent_pane_id = active_pane_id
                self.state.parent_session = self._active_spec.tmux_session_name
                self.state.parent_spec_id = self._active_spec.session_id

        self._layout_signature = self._compute_layout_signature()
        self._set_tui_pane_background()

    def _track_session_pane(self, spec: SessionPaneSpec, pane_id: str) -> None:
        """Track pane ids for lookup and cleanup."""
        self.state.session_pane_ids.append(pane_id)
        self.state.session_to_pane[spec.session_id] = pane_id
        if spec.is_sticky:
            self.state.sticky_pane_ids.append(pane_id)
            self.state.sticky_session_to_pane[spec.session_id] = pane_id

        # Apply explicit pane styling so panes never inherit stale colors.
        if spec.tmux_session_name:
            self._set_pane_background(
                pane_id,
                spec.tmux_session_name,
                spec.active_agent,
                is_tree_selected=self._is_tree_selected_session(spec.session_id),
            )
        else:
            self._set_doc_pane_background(pane_id)

    def _is_tree_selected_session(self, session_id: str) -> bool:
        """Return True if this session row should get the lighter tree-selected haze."""
        return (
            self._tree_node_has_focus
            and self._selected_session_id is not None
            and session_id == self._selected_session_id
        )

    def _set_pane_background(
        self, pane_id: str, tmux_session_name: str, agent: str, *, is_tree_selected: bool = False
    ) -> None:
        """Set per-pane colors and keep embedded tmux status bar hidden.

        Args:
            pane_id: Tmux pane ID
            tmux_session_name: Tmux session name
            agent: Agent name for color calculation
            is_tree_selected: Use lighter haze when the tree focus selected row matches.
        """
        # Inactive pane should communicate state through background haze only.
        if is_tree_selected:
            bg_color = theme.get_agent_pane_selected_background(agent)
        else:
            bg_color = theme.get_agent_pane_inactive_background(agent)
        pane_fg_color_code = theme.get_agent_normal_color(agent)
        self._run_tmux("set", "-p", "-t", pane_id, "window-style", f"fg=colour{pane_fg_color_code},bg={bg_color}")

        # Use explicit active pane background (no haze) to avoid inheriting window-style haze.
        terminal_bg = theme.get_agent_pane_active_background(agent)
        self._run_tmux(
            "set",
            "-p",
            "-t",
            pane_id,
            "window-active-style",
            f"fg=colour{pane_fg_color_code},bg={terminal_bg}",
        )

        # Embedded session panes should not render tmux status bars.
        self._run_tmux("set", "-t", tmux_session_name, "status", "off")

        # Override color 236 (message box backgrounds) for specific agents
        # if agent == "codex" and theme.get_current_mode():  # dark mode
        #     # Use color 237 (slightly lighter gray) for Codex message boxes
        #     self._run_tmux("set", "-p", "-t", pane_id, "pane-colours[236]", "#3a3a3a")

    def _set_tui_pane_background(self) -> None:
        """Apply subtle inactive haze styling to the TUI pane only."""
        if not self._tui_pane_id or not self._get_pane_exists(self._tui_pane_id):
            return

        inactive_bg = theme.get_tui_inactive_background()
        terminal_bg = theme.get_terminal_background()
        self._run_tmux("set", "-p", "-t", self._tui_pane_id, "window-style", f"fg=default,bg={inactive_bg}")
        self._run_tmux("set", "-p", "-t", self._tui_pane_id, "window-active-style", f"fg=default,bg={terminal_bg}")
        # Keep tc_tui split borders visually neutral; global tmux theme remains untouched.
        self._run_tmux(
            "set",
            "-w",
            "-t",
            self._tui_pane_id,
            "pane-border-style",
            f"fg={inactive_bg},bg={inactive_bg}",
        )
        self._run_tmux(
            "set",
            "-w",
            "-t",
            self._tui_pane_id,
            "pane-active-border-style",
            f"fg={inactive_bg},bg={inactive_bg}",
        )

    def _set_doc_pane_background(self, pane_id: str) -> None:
        """Apply neutral styling for doc preview panes (glow/less)."""
        inactive_bg = theme.get_tui_inactive_background()
        terminal_bg = theme.get_terminal_background()
        self._run_tmux("set", "-p", "-t", pane_id, "window-style", f"fg=default,bg={inactive_bg}")
        self._run_tmux("set", "-p", "-t", pane_id, "window-active-style", f"fg=default,bg={terminal_bg}")

    def reapply_agent_colors(self) -> None:
        """Re-apply agent-colored backgrounds and status bars to all session panes.

        Called when appearance theme changes (SIGUSR1) to restore agent colors
        after global theme reload.
        """
        if not self._in_tmux:
            return

        self._set_tui_pane_background()
        reapplied_panes: set[str] = set()

        # Re-apply colors to sticky session panes
        for spec in self._sticky_specs:
            pane_id = self.state.session_to_pane.get(spec.session_id)
            if not pane_id or not self._get_pane_exists(pane_id):
                continue
            if spec.tmux_session_name:
                self._set_pane_background(
                    pane_id,
                    spec.tmux_session_name,
                    spec.active_agent,
                    is_tree_selected=self._is_tree_selected_session(spec.session_id),
                )
            else:
                self._set_doc_pane_background(pane_id)
            reapplied_panes.add(pane_id)

        # Re-apply colors to active session pane
        if self._active_spec:
            pane_id = self.state.session_to_pane.get(self._active_spec.session_id)
            if pane_id and self._get_pane_exists(pane_id):
                if self._active_spec.tmux_session_name:
                    self._set_pane_background(
                        pane_id,
                        self._active_spec.tmux_session_name,
                        self._active_spec.active_agent,
                        is_tree_selected=self._is_tree_selected_session(self._active_spec.session_id),
                    )
                else:
                    self._set_doc_pane_background(pane_id)
                reapplied_panes.add(pane_id)

        # Fallback: style any remaining tracked panes from session mapping.
        for session_id, pane_id in self.state.session_to_pane.items():
            if pane_id in reapplied_panes or not self._get_pane_exists(pane_id):
                continue
            if session_id.startswith("doc:"):
                self._set_doc_pane_background(pane_id)
                continue
            session = self._session_catalog.get(session_id)
            if session and session.tmux_session_name:
                self._set_pane_background(
                    pane_id,
                    session.tmux_session_name,
                    session.active_agent,
                    is_tree_selected=self._is_tree_selected_session(session_id),
                )

    def _build_pane_command(self, spec: SessionPaneSpec) -> str:
        """Build the command used to populate a pane."""
        if spec.command:
            return spec.command
        return self._build_attach_cmd(spec.tmux_session_name or "", spec.computer_info)

    def show_sticky_sessions(
        self,
        sticky_sessions: list["SessionInfo"],
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
        """Clean up all sticky panes."""
        for pane_id in self.state.sticky_pane_ids:
            if self._get_pane_exists(pane_id):
                self._run_tmux("kill-pane", "-t", pane_id)
        self.state.sticky_pane_ids.clear()
        self.state.sticky_session_to_pane.clear()  # Clear session→pane mapping
        logger.debug("_cleanup_sticky_panes: cleaned up sticky panes and mapping")

    def cleanup(self) -> None:
        """Clean up all managed panes. Call this when TUI exits."""
        self._cleanup_panes()
        self._cleanup_sticky_panes()

    def focus_pane_for_session(self, session_id: str) -> bool:
        """Focus the pane showing a specific session.

        Args:
            session_id: The session ID to focus

        Returns:
            True if pane was found and focused, False otherwise
        """
        if not self._in_tmux:
            return False

        # Check if session is visible in any pane
        pane_id = self.state.session_to_pane.get(session_id)
        if pane_id and self._get_pane_exists(pane_id):
            self._run_tmux("select-pane", "-t", pane_id)
            logger.debug("Focused sticky pane %s for session %s", pane_id, session_id[:8])
            return True

        # Check if session is in active pane (match by session_id would require tracking)
        # For now, just focus active pane if it exists
        if self.state.parent_pane_id and self._get_pane_exists(self.state.parent_pane_id):
            self._run_tmux("select-pane", "-t", self.state.parent_pane_id)
            logger.debug("Focused active pane %s", self.state.parent_pane_id)
            return True

        logger.debug("No pane found for session %s", session_id[:8])
        return False
