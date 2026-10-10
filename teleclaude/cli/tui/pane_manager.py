"""Tmux pane manager for TUI session viewing."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.api_session_attachment import (
    LocalSessionAttachmentDTO,
    SessionAttachmentDestinationDTO,
    SshSessionAttachmentDTO,
)
from teleclaude.cli.tui._pane_specs import (
    LAYOUT_SPECS,
    LayoutCell,
    LayoutSpec,
    ObservedDocumentPane,
    ObservedSessionPane,
    PaneGeometry,
    PaneState,
    SessionPaneSpec,
)
from teleclaude.cli.tui.artifact_panes import doc_pane_key, parse_doc_pane_command
from teleclaude.cli.tui.pane_layout import (
    _PANE_ID_FORMAT,
    PaneLayoutMixin,
    _PaneCommand,
    _PaneFlag,
)
from teleclaude.cli.tui.pane_theming import PaneThemingMixin
from teleclaude.cli.tui.types import DocPreviewState
from teleclaude.config.machine import config
from teleclaude.core.shell_identity import require_shell_safe_identifier

if TYPE_CHECKING:
    from teleclaude.api_models import SessionDTO

logger = get_logger(__name__)
_ATTACHMENT_DESTINATION_UNAVAILABLE_DETAIL = "session attachment destination is unresolved"
_PEER_USER_IDENTIFIER = "peer user"
_PEER_HOST_IDENTIFIER = "peer host"
_TOGGLE_SESSION_LOG = "toggle_session: %s (agent=%s, remote=%s, sticky_count=%d)"
_RELOAD_PANE_FORMAT = "#{pane_id}\t#{pane_start_command}\t#{pane_left}\t#{pane_top}\t#{pane_width}\t#{pane_height}"
_RELOAD_GEOMETRY_FORMAT = "#{pane_id}\t#{pane_left}\t#{pane_top}\t#{pane_width}\t#{pane_height}"
_PANE_FIELD_SEPARATOR = "\t"
_RELOAD_PANE_FIELD_COUNT = 6
_RELOAD_GEOMETRY_FIELD_COUNT = 5
_RELOAD_SESSION_NAME_PATTERN = re.compile(r"attach-session -t (\S+)")
_RELOAD_SSH_TARGET_PATTERN = re.compile(r"^ssh -t -A (\S+)")
_RELOAD_LOCAL_ATTACH_PREFIX = "env -u TMUX TERM=tmux-256color"
_TMUX_SESSION_NAME_IDENTIFIER = "tmux_session_name"
_REMOTE_TARGET_SEPARATOR = "@"
_COMMAND_SURROUNDING_QUOTES = "\"'"
_RELOAD_DOC_ADOPTED_LOG = "seed_for_reload: adopted viewer pane %s for %s"
_RELOAD_DOC_UNWANTED_RELEASE_LOG = "seed_for_reload: released unwanted artifact pane %s"
_RELOAD_COMMAND_PROTECTED_LOG = "seed_for_reload: protected unidentified pane %s"


def _parse_pane_geometry(values: list[str]) -> PaneGeometry | None:
    """Parse tmux pane position and size fields."""
    if len(values) != _RELOAD_GEOMETRY_FIELD_COUNT:
        return None
    try:
        return PaneGeometry(left=int(values[1]), top=int(values[2]), width=int(values[3]), height=int(values[4]))
    except ValueError:
        return None


def _parse_session_pane_identity(command: str) -> tuple[str, SessionAttachmentDestinationDTO | None] | None:
    """Read a TeleClaude session target and any known destination from its start command."""
    session_match = _RELOAD_SESSION_NAME_PATTERN.search(command)
    if session_match is None:
        return None
    raw_session_name = session_match.group(1).rstrip(_COMMAND_SURROUNDING_QUOTES)
    try:
        session_name = require_shell_safe_identifier(raw_session_name, _TMUX_SESSION_NAME_IDENTIFIER)
    except ValueError:
        return None

    remote_match = _RELOAD_SSH_TARGET_PATTERN.match(command)
    if remote_match is not None:
        raw_target = remote_match.group(1)
        user, separator, host = raw_target.partition(_REMOTE_TARGET_SEPARATOR)
        if separator and user and host:
            try:
                safe_user = require_shell_safe_identifier(user, _PEER_USER_IDENTIFIER)
                safe_host = require_shell_safe_identifier(host, _PEER_HOST_IDENTIFIER)
            except ValueError:
                return session_name, None
            return session_name, SshSessionAttachmentDTO(user=safe_user, host=safe_host)
        return session_name, None

    if command.startswith(_RELOAD_LOCAL_ATTACH_PREFIX):
        return session_name, LocalSessionAttachmentDTO()
    return session_name, None


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
    observed_specs: dict[str, SessionPaneSpec] = field(default_factory=dict)
    observed_geometry: dict[str, PaneGeometry] = field(default_factory=dict)
    reload_observation_pending: bool = False
    geometry_dirty: bool = False
    detached_panes: set[str] = field(default_factory=set)
    recovery_focus: str | None = None


@dataclass
class _ReloadPaneState:
    """Pane ids discovered during a tmux reload."""

    session_panes: dict[str, ObservedSessionPane] = field(default_factory=dict)
    command_panes: dict[str, PaneGeometry | None] = field(default_factory=dict)
    doc_panes: dict[str, ObservedDocumentPane] = field(default_factory=dict)


__all__ = [
    "LAYOUT_SPECS",
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
        self._in_tmux = bool(os.environ.get("TMUX"))  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        self._layout_state = _PaneLayoutState()
        self._session_catalog: dict[str, SessionDTO] = {}
        self._reload_state = _ReloadPaneState()
        self._reload_pending = is_reload
        self._adopted_doc_preview: DocPreviewState | None = None
        self._unresolved_panes: dict[str, ObservedSessionPane] = {}
        self._unidentified_panes: set[str] = set()
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
    def _reload_session_panes(self) -> dict[str, ObservedSessionPane]:
        return self._reload_state.session_panes

    @property
    def _reload_command_panes(self) -> dict[str, PaneGeometry | None]:
        return self._reload_state.command_panes

    @property
    def _reload_doc_panes(self) -> dict[str, ObservedDocumentPane]:
        return self._reload_state.doc_panes

    def has_reload_panes(self) -> bool:
        """Return whether reload-discovered panes are waiting to be adopted."""
        return self._reload_pending or bool(
            self._reload_session_panes or self._reload_command_panes or self._reload_doc_panes
        )

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
        if not is_reload:
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
        """Discover pane owners, attachment inputs, and placement from tmux.

        On SIGUSR2 reload, panes from the previous process survive in tmux.
        Start-command identity and pane geometry are captured for the first
        complete session-owner pass to reconcile.
        """
        tui_pane_id = self._tui_pane_id
        if tui_pane_id is None:
            return
        output = self._run_tmux(
            _PaneCommand.LIST,
            _PaneFlag.TARGET,
            tui_pane_id,
            _PaneFlag.FORMAT,
            _RELOAD_PANE_FORMAT,
        )
        for line in output.split("\n"):
            if not line:
                continue
            parts = line.split(_PANE_FIELD_SEPARATOR, _RELOAD_PANE_FIELD_COUNT - 1)
            pane_id = parts[0].strip()
            if len(parts) != _RELOAD_PANE_FIELD_COUNT:
                if pane_id and pane_id != self._tui_pane_id:
                    self._reload_command_panes[pane_id] = None
                continue
            _pane_id, start_command, *geometry_values = parts
            geometry = _parse_pane_geometry([_pane_id, *geometry_values])
            if pane_id == tui_pane_id:
                continue

            # A pane names what it is in the command it was started with: a
            # session pane its attach target, a viewer pane its artifact.
            session_identity = _parse_session_pane_identity(start_command)
            if session_identity is not None:
                tmux_name, destination = session_identity
                self._reload_session_panes[tmux_name] = ObservedSessionPane(
                    pane_id=pane_id,
                    attachment_destination=destination,
                    geometry=geometry,
                )
            else:
                doc_preview = parse_doc_pane_command(start_command)
                if doc_preview is not None:
                    self._reload_doc_panes[pane_id] = ObservedDocumentPane(
                        preview=doc_preview,
                        geometry=geometry,
                    )
                else:
                    self._reload_command_panes[pane_id] = geometry

        logger.debug(
            "Reload: mapped %d session panes, %d command panes: %s",
            len(self._reload_session_panes),
            len(self._reload_command_panes),
            dict(self._reload_session_panes),
        )

    @property
    def _protected_panes(self) -> set[str]:
        """Panes held until their owner is resolved or the pane disappears."""
        return (
            {pane.pane_id for pane in self._unresolved_panes.values()}
            | {pane.pane_id for pane in self._reload_session_panes.values()}
            | set(self._reload_doc_panes)
            | set(self._reload_command_panes)
            | self._unidentified_panes
        )

    def _resolve_unresolved_panes(self) -> None:
        """Bind a protected pane to its session once the catalog can name it.

        Protection covers ignorance, not preference. A session row that comes
        back complete resolves its pane into the tracked map, and the ordinary
        layout rules govern it from there — including reaping it when it turns
        out not to be wanted, which is a decision made on knowledge rather than
        on the absence of it. A pane whose session is gone from tmux is dropped.
        """
        if not self._unresolved_panes:
            return
        by_tmux_name = {
            session.tmux_session_name: session
            for session in self._session_catalog.values()
            if session.tmux_session_name
        }
        resolved_any = False
        for tmux_name, observation in list(self._unresolved_panes.items()):
            if not self._get_pane_exists(observation.pane_id):
                del self._unresolved_panes[tmux_name]
                self._layout_state.observed_geometry.pop(observation.pane_id, None)
                continue
            session = by_tmux_name.get(tmux_name)
            if session is None:
                continue
            self.state.session_to_pane[session.session_id] = observation.pane_id
            self._layout_state.observed_specs[session.session_id] = SessionPaneSpec(
                session_id=session.session_id,
                tmux_session_name=tmux_name,
                attachment_destination=observation.attachment_destination,
                is_sticky=False,
                active_agent=session.active_agent or "",
            )
            if observation.geometry is not None:
                self._layout_state.observed_geometry[observation.pane_id] = observation.geometry
            del self._unresolved_panes[tmux_name]
            self._layout_state.reload_observation_pending = True
            resolved_any = True
            logger.debug("resolved protected pane %s to session %s", observation.pane_id, session.session_id)
        if resolved_any:
            self._layout_state.observed_geometry = self._capture_pane_geometries()

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
        live_panes.update(pane for pane in self._layout_state.detached_panes if self._get_pane_exists(pane))
        self._unidentified_panes.intersection_update(live_panes)

        dead_sessions = [sid for sid, pid in self.state.session_to_pane.items() if pid not in live_panes]
        for sid in dead_sessions:
            pane_id = self.state.session_to_pane.pop(sid)
            self._layout_state.observed_specs.pop(sid, None)
            self._layout_state.observed_geometry.pop(pane_id, None)

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

        Sessions omitted by a scoped snapshot leave the viewer's pane layout;
        the attached tmux session itself remains alive.
        """
        new_catalog = {session.session_id: session for session in sessions}
        self._session_catalog = new_catalog
        visible_ids = set(new_catalog)
        self._layout_state.sticky_specs = [
            spec for spec in self._layout_state.sticky_specs if spec.session_id in visible_ids
        ]
        active_spec = self._layout_state.active_spec
        if active_spec is not None and active_spec.session_id not in visible_ids:
            self._layout_state.active_spec = None
            self.state.active_session_id = None
        self._resolve_unresolved_panes()

    def _adopt_reload_doc_pane(self, desired_doc_id: str | None) -> list[str]:
        """Register the wanted artifact viewer and return resolved unwanted panes."""
        unwanted_panes: list[str] = []
        for pane_id, observation in self._reload_doc_panes.items():
            if not self._get_pane_exists(pane_id):
                continue
            doc_preview = observation.preview
            if desired_doc_id is None or doc_preview.doc_id != desired_doc_id or self._adopted_doc_preview is not None:
                unwanted_panes.append(pane_id)
                continue
            session_id = doc_pane_key(doc_preview.doc_id)
            self.state.session_to_pane[session_id] = pane_id
            self._layout_state.observed_specs[session_id] = SessionPaneSpec(
                session_id=session_id,
                tmux_session_name=None,
                attachment_destination=None,
                is_sticky=False,
                active_agent="",
                command=doc_preview.command,
            )
            if observation.geometry is not None:
                self._layout_state.observed_geometry[pane_id] = observation.geometry
            if self._adopted_doc_preview is None:
                self._adopted_doc_preview = doc_preview
                logger.debug(_RELOAD_DOC_ADOPTED_LOG, pane_id, doc_preview.doc_id)
        self._reload_doc_panes.clear()
        return unwanted_panes

    def seed_for_reload(
        self,
        *,
        active_doc_preview: DocPreviewState | None = None,
        adopt_discovered_artifact: bool = False,
    ) -> None:
        """Resolve discovered panes against the complete owner snapshot.

        Observed targets and pane positions seed the current attachment map.
        Known but unwanted viewers remain available for the ordinary diff to
        release; unresolved owners stay protected.
        """
        if not self.has_reload_panes():
            return
        if not self._tui_pane_id:
            self._reload_pending = False
            return
        if self._reload_pending:
            self._adopt_for_reload()
            self._reload_pending = False

        self._adopted_doc_preview = None
        if adopt_discovered_artifact and active_doc_preview is None and self._reload_doc_panes:
            active_doc_preview = next(iter(self._reload_doc_panes.values())).preview
        desired_doc_id = active_doc_preview.doc_id if active_doc_preview is not None else None
        unwanted_doc_panes = self._adopt_reload_doc_pane(desired_doc_id)
        for pane_id in unwanted_doc_panes:
            self._run_tmux(_PaneCommand.KILL, _PaneFlag.TARGET, pane_id)
            logger.debug(_RELOAD_DOC_UNWANTED_RELEASE_LOG, pane_id)
        self._unidentified_panes.update(self._reload_command_panes)
        for pane_id in self._reload_command_panes:
            logger.debug(_RELOAD_COMMAND_PROTECTED_LOG, pane_id)
        self._reload_command_panes.clear()
        by_tmux_name = {
            session.tmux_session_name: session
            for session in self._session_catalog.values()
            if session.tmux_session_name
        }
        for tmux_name, observation in self._reload_session_panes.items():
            session = by_tmux_name.get(tmux_name)
            if session is None:
                self._unresolved_panes[tmux_name] = observation
                continue
            self.state.session_to_pane[session.session_id] = observation.pane_id
            self._layout_state.observed_specs[session.session_id] = SessionPaneSpec(
                session_id=session.session_id,
                tmux_session_name=tmux_name,
                attachment_destination=observation.attachment_destination,
                is_sticky=False,
                active_agent=session.active_agent or "",
            )
        self._reload_session_panes.clear()

        self._layout_state.observed_geometry = self._capture_pane_geometries()
        self._layout_state.active_spec = None
        self._layout_state.sticky_specs = []
        self._layout_state.cell_specs = []
        self._layout_state.layout_signature = None
        self._layout_state.reload_observation_pending = True

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
        pane_id = os.environ.get("TMUX_PANE")  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
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

    def _get_pane_exists(self, pane_id: str) -> bool:
        """Check if a pane still exists."""
        args: list[str] = [_PaneCommand.LIST, _PaneFlag.FORMAT, _PANE_ID_FORMAT]
        if pane_id in self._layout_state.detached_panes:
            args.append(_PaneFlag.ALL)
        output = self._run_tmux(*args)
        return pane_id in output.split("\n")

    def _capture_pane_geometries(self) -> dict[str, PaneGeometry]:
        """Read current pane positions and dimensions from tmux."""
        tui_pane_id = self._tui_pane_id
        if tui_pane_id is None:
            return {}
        output = self._run_tmux(
            _PaneCommand.LIST,
            _PaneFlag.TARGET,
            tui_pane_id,
            _PaneFlag.FORMAT,
            _RELOAD_GEOMETRY_FORMAT,
        )
        geometries: dict[str, PaneGeometry] = {}
        for line in output.split("\n"):
            parts = line.split(_PANE_FIELD_SEPARATOR, _RELOAD_GEOMETRY_FIELD_COUNT - 1)
            if len(parts) != _RELOAD_GEOMETRY_FIELD_COUNT:
                continue
            pane_id = parts[0].strip()
            geometry = _parse_pane_geometry(parts)
            if pane_id and geometry is not None:
                geometries[pane_id] = geometry
        return geometries

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
        destination: SessionAttachmentDestinationDTO | None,
    ) -> str:
        """Build the command to attach to a tmux session.

        For local sessions: direct tmux attach
        For remote sessions: SSH with tmux attach (includes appearance env vars)

        Args:
            tmux_session_name: The tmux session name to attach to
            destination: Resolved connection inputs published by the daemon

        Returns:
            Command string to execute
        """
        safe_tmux_session_name = require_shell_safe_identifier(tmux_session_name, "tmux_session_name")
        attach_cmd = self._build_tmux_attach_command(safe_tmux_session_name)

        if isinstance(destination, SshSessionAttachmentDTO):
            # Remote: SSH to the computer and attach there
            # Use -t for pseudo-terminal allocation (required for tmux)
            # Use -A for SSH agent forwarding
            user = require_shell_safe_identifier(destination.user, _PEER_USER_IDENTIFIER)
            host = require_shell_safe_identifier(destination.host, _PEER_HOST_IDENTIFIER)
            ssh_target = f"{user}@{host}"

            # Get appearance settings from host to pass to remote
            appearance_env = self._get_appearance_env()
            env_str = " ".join(f"{k}={v}" for k, v in appearance_env.items())
            if env_str:
                env_str += " "

            cmd = f"ssh -t -A {ssh_target} '{env_str}TERM=tmux-256color tmux -u {attach_cmd}'"
            logger.debug("Remote attach cmd for %s via %s: %s", tmux_session_name, ssh_target, cmd)
            return cmd

        if not isinstance(destination, LocalSessionAttachmentDTO):
            raise ValueError(_ATTACHMENT_DESTINATION_UNAVAILABLE_DETAIL)

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
        attachment_destination: SessionAttachmentDestinationDTO | None,
        session_id: str | None = None,
    ) -> None:
        """Show a session in the active/preview pane.

        This shows the "active" session that changes on single-click.
        Coexists with sticky sessions (double-click).

        Args:
            tmux_session_name: The session's tmux session name
            active_agent: Agent name for color styling
            attachment_destination: Resolved connection inputs published by the daemon
        """
        if not self._in_tmux:
            logger.debug("show_session: not in tmux, skipping")
            return

        logger.debug(
            "show_session: %s (agent=%s, remote=%s, sticky_count=%d)",
            tmux_session_name,
            active_agent,
            isinstance(attachment_destination, SshSessionAttachmentDTO),
            len(self._sticky_specs),
        )

        spec_session_id = session_id or tmux_session_name
        self._layout_state.active_spec = SessionPaneSpec(
            session_id=spec_session_id,
            tmux_session_name=tmux_session_name,
            attachment_destination=attachment_destination,
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
        attachment_destination: SessionAttachmentDestinationDTO | None,
        session_id: str | None = None,
    ) -> bool:
        """Toggle active/preview session pane visibility.

        If already showing this session, hide it.
        If showing different session or none, show this one.

        Args:
            tmux_session_name: The session's tmux session name
            active_agent: Agent name for color styling
            attachment_destination: Resolved connection inputs published by the daemon

        Returns:
            True if now showing, False if now hidden
        """
        if not self._in_tmux:
            logger.debug("toggle_session: not in tmux, returning False")
            return False

        logger.debug(
            _TOGGLE_SESSION_LOG,
            tmux_session_name,
            active_agent,
            isinstance(attachment_destination, SshSessionAttachmentDTO),
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
            attachment_destination,
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
    ) -> None:
        """Show 1-5 sticky sessions using tmux's fixed layouts.

        Args:
            sticky_sessions: List of SessionDTO objects
        """
        if not self._in_tmux:
            logger.debug("show_sticky_sessions: not in tmux, skipping")
            return

        logger.info("show_sticky_sessions: showing %d sticky sessions", len(sticky_sessions))

        sticky_specs: list[SessionPaneSpec] = []
        for session_info in sticky_sessions:
            spec = self._session_pane_spec(session_info, is_sticky=True)
            if spec is not None:
                sticky_specs.append(spec)

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
            if self._layout_state.geometry_dirty:
                self._layout_state.recovery_focus = pane_id
            if pane_id in self._layout_state.detached_panes:
                return False
            self._run_tmux("select-pane", "-t", pane_id)
            logger.debug("Focused pane %s for session %s", pane_id, session_id)
            return True

        logger.debug("No pane found for session %s", session_id)
        return False
