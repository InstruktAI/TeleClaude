"""Tmux pane manager for TUI session viewing."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
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
from teleclaude.cli.tui.artifact_panes import doc_pane_key, parse_doc_pane_command
from teleclaude.cli.tui.pane_layout import PaneLayoutMixin
from teleclaude.cli.tui.pane_theming import PaneThemingMixin
from teleclaude.cli.tui.types import DocPreviewState
from teleclaude.config import config
from teleclaude.core.shell_identity import require_shell_safe_identifier

if TYPE_CHECKING:
    from teleclaude.api_models import SessionDTO

logger = get_logger(__name__)


@dataclass
class _PaneLayoutState:
    """Mutable layout state shared across pane-manager mixins."""

    sticky_specs: list[SessionPaneSpec] = field(default_factory=list)
    active_spec: SessionPaneSpec | None = None
    selected_session_id: str | None = None
    tree_node_has_focus: bool = False
    layout_signature: tuple[object, ...] | None = None
    bg_signature: tuple[object, ...] | None = None
    # Ordered cell assignment from the last applied layout. Diffing the new
    # desired assignment against this drives same-tier in-place swaps.
    cell_specs: list[SessionPaneSpec] | None = None


@dataclass
class _ReloadPaneState:
    """Pane ids discovered during a tmux reload."""

    session_panes: dict[str, str] = field(default_factory=dict)
    command_panes: list[str] = field(default_factory=list)
    doc_panes: dict[str, DocPreviewState] = field(default_factory=dict)


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
        self._layout_state = _PaneLayoutState()
        self._session_catalog: dict[str, SessionDTO] = {}
        self._reload_state = _ReloadPaneState()
        self._adopted_doc_preview: DocPreviewState | None = None
        # Resolves a session's computer name to its ComputerInfo so catalog-based
        # theming can tell remote panes from local ones. Refreshed on every
        # apply_layout / seed_for_reload; defaults to local-only.
        self._computer_info_resolver: Callable[[str], ComputerInfo | None] = lambda _: None
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
    def _sticky_specs(self) -> list[SessionPaneSpec]:
        return self._layout_state.sticky_specs

    @_sticky_specs.setter
    def _sticky_specs(self, value: list[SessionPaneSpec]) -> None:
        self._layout_state.sticky_specs = value

    @property
    def _active_spec(self) -> SessionPaneSpec | None:
        return self._layout_state.active_spec

    @_active_spec.setter
    def _active_spec(self, value: SessionPaneSpec | None) -> None:
        self._layout_state.active_spec = value

    @property
    def _selected_session_id(self) -> str | None:
        return self._layout_state.selected_session_id

    @_selected_session_id.setter
    def _selected_session_id(self, value: str | None) -> None:
        self._layout_state.selected_session_id = value

    @property
    def _tree_node_has_focus(self) -> bool:
        return self._layout_state.tree_node_has_focus

    @_tree_node_has_focus.setter
    def _tree_node_has_focus(self, value: bool) -> None:
        self._layout_state.tree_node_has_focus = value

    @property
    def _layout_signature(self) -> tuple[object, ...] | None:
        return self._layout_state.layout_signature

    @_layout_signature.setter
    def _layout_signature(self, value: tuple[object, ...] | None) -> None:
        self._layout_state.layout_signature = value

    @property
    def _bg_signature(self) -> tuple[object, ...] | None:
        return self._layout_state.bg_signature

    @_bg_signature.setter
    def _bg_signature(self, value: tuple[object, ...] | None) -> None:
        self._layout_state.bg_signature = value

    @property
    def _reload_session_panes(self) -> dict[str, str]:
        return self._reload_state.session_panes

    @property
    def _reload_command_panes(self) -> list[str]:
        return self._reload_state.command_panes

    @property
    def _reload_doc_panes(self) -> dict[str, DocPreviewState]:
        return self._reload_state.doc_panes

    def has_reload_panes(self) -> bool:
        """Return whether reload-discovered panes are waiting to be adopted."""
        return bool(self._reload_session_panes or self._reload_command_panes or self._reload_doc_panes)

    def adopted_doc_preview(self) -> DocPreviewState | None:
        """Return the viewer this reload adopted, so its owner can resume showing it."""
        return self._adopted_doc_preview

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

            # A pane names what it is in the command it was started with: a
            # session pane its attach target, a viewer pane its artifact.
            if len(parts) > 1:
                match = re.search(r"attach-session -t (\S+)", parts[1])
                doc_preview = None if match else parse_doc_pane_command(parts[1])
                if match:
                    tmux_name = match.group(1).rstrip("'\"")
                    self._reload_session_panes[tmux_name] = pane_id
                elif doc_preview is not None:
                    self._reload_doc_panes[pane_id] = doc_preview
                else:
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

    def update_session_catalog(self, sessions: list[SessionDTO]) -> None:
        """Update the session catalog used for layout lookup.

        Sessions referenced by current sticky or active specs are retained when
        absent from the snapshot — eviction happens only via `remove_session`,
        which is driven by an explicit `SessionClosed` event.
        """
        retained_ids: set[str] = {spec.session_id for spec in self._layout_state.sticky_specs}
        active_spec = self._layout_state.active_spec
        if active_spec is not None:
            retained_ids.add(active_spec.session_id)
        new_catalog = {session.session_id: session for session in sessions}
        for session_id in retained_ids:
            if session_id not in new_catalog and session_id in self._session_catalog:
                new_catalog[session_id] = self._session_catalog[session_id]
        self._session_catalog = new_catalog

    def _adopt_reload_doc_pane(self) -> None:
        """Keep the viewer a reload found, and let go of any beyond the first.

        The layout carries one viewer at a time, so the first surviving viewer
        pane is adopted into the pane map under its document id and the rest are
        released to the ordinary command-pane path.
        """
        for pane_id, doc_preview in self._reload_doc_panes.items():
            if not self._get_pane_exists(pane_id):
                continue
            if self._adopted_doc_preview is None:
                self._adopted_doc_preview = doc_preview
                self.state.session_to_pane[doc_pane_key(doc_preview.doc_id)] = pane_id
                logger.debug("seed_for_reload: adopted viewer pane %s for %s", pane_id, doc_preview.doc_id)
                continue
            self._reload_command_panes.append(pane_id)
        self._reload_doc_panes.clear()

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
        self._computer_info_resolver = get_computer_info
        if not self.has_reload_panes():
            return

        self._adopt_reload_doc_pane()

        # A command pane that names nothing placeable is killed: there is no
        # handle to map it back to.
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
        self._layout_state.sticky_specs = sticky_specs

        if active_session_id:
            session = self._session_catalog.get(active_session_id)
            if session and session.tmux_session_name:
                self._layout_state.active_spec = SessionPaneSpec(
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

        # Reap a reload pane only once its tmux session is gone. Failing to map
        # a pane is absence of information — the session row can come back
        # incomplete right after a daemon restart — while the pane itself may be
        # attached to a session the user is working in. The pane's own session
        # is the evidence; an unmapped pane whose session is alive is left for
        # the layout to place.
        mapped_panes = set(self.state.session_to_pane.values())
        live_tmux_sessions = self._live_tmux_session_names()
        for tmux_name, pane_id in reload_map.items():
            if pane_id in mapped_panes:
                continue
            if tmux_name in live_tmux_sessions:
                logger.debug(
                    "seed_for_reload: kept unmapped pane %s — tmux session %s is alive",
                    pane_id,
                    tmux_name,
                )
                continue
            if self._get_pane_exists(pane_id):
                self._run_tmux("kill-pane", "-t", pane_id)
                logger.debug(
                    "seed_for_reload: killed pane %s — tmux session %s is gone",
                    pane_id,
                    tmux_name,
                )

        self._layout_state.layout_signature = self._compute_layout_signature()
        # Seed the cell assignment so the first post-reload apply_layout takes
        # the same-tier in-place path instead of rebuilding (which would kill
        # the panes just adopted from the previous process).
        self._layout_state.cell_specs = self._build_session_specs()
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
        except subprocess.CalledProcessError as exc:
            logger.error(
                "tmux command failed: args=%s returncode=%s stderr=%s",
                list(args),
                exc.returncode,
                (exc.stderr or "").strip(),
            )
            raise

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
                ("TUI pane %s belongs to session '%s', not '%s' — disabling pane management to prevent orphan splits"),
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

    def _live_tmux_session_names(self) -> set[str]:
        """The tmux sessions that exist on this server right now."""
        output = self._run_tmux("list-sessions", "-F", "#{session_name}")
        return {name.strip() for name in output.split("\n") if name.strip()}

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
                check=False,
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
                check=False,
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
        safe_tmux_session_name = require_shell_safe_identifier(tmux_session_name, "tmux_session_name")
        attach_cmd = self._build_tmux_attach_command(safe_tmux_session_name)

        if computer_info and computer_info.is_remote:
            # Remote: SSH to the computer and attach there
            # Use -t for pseudo-terminal allocation (required for tmux)
            # Use -A for SSH agent forwarding
            user = require_shell_safe_identifier(computer_info.user, "peer user")
            host = require_shell_safe_identifier(computer_info.host, "peer host")
            ssh_target = f"{user}@{host}"

            # Get appearance settings from host to pass to remote
            appearance_env = self._get_appearance_env()
            env_str = " ".join(f"{k}={v}" for k, v in appearance_env.items())
            if env_str:
                env_str += " "

            cmd = f"ssh -t -A {ssh_target} '{env_str}TERM=tmux-256color tmux -u {attach_cmd}'"
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
        self._layout_state.active_spec = SessionPaneSpec(
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
        self._layout_state.active_spec = None
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
        sticky_sessions: list[SessionDTO],
        get_computer_info: Callable[[str], ComputerInfo | None],
    ) -> None:
        """Show 1-5 sticky sessions using tmux's fixed layouts.

        Args:
            sticky_sessions: List of SessionDTO objects
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

        self._layout_state.sticky_specs = sticky_specs
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
