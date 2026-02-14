"""Sessions view - shows running AI sessions.

Required reads:
- @docs/project/design/tui-state-layout.md
"""

from __future__ import annotations

import asyncio
import curses
import os
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

from instrukt_ai_logging import get_logger

from teleclaude.cli.models import (
    AgentAvailabilityInfo,
    CreateSessionResult,
    ProjectInfo,
    ProjectWithTodosInfo,
    SessionInfo,
)
from teleclaude.cli.models import ComputerInfo as ApiComputerInfo
from teleclaude.cli.tui.controller import TuiController
from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager
from teleclaude.cli.tui.session_launcher import attach_tmux_from_result
from teleclaude.cli.tui.state import DocStickyInfo, Intent, IntentType, PreviewState, TuiState
from teleclaude.cli.tui.state_store import load_sticky_state, save_sticky_state
from teleclaude.cli.tui.theme import (
    AGENT_COLORS,
    get_agent_preview_selected_bg_attr,
    get_agent_preview_selected_focus_attr,
)
from teleclaude.cli.tui.tree import (
    ComputerDisplayInfo,
    ComputerNode,
    ProjectNode,
    SessionDisplayInfo,
    SessionNode,
    TreeNode,
    build_tree,
    is_computer_node,
    is_project_node,
    is_session_node,
)
from teleclaude.cli.tui.types import CursesWindow, FocusLevelType, NodeType, NotificationLevel, StickySessionInfo
from teleclaude.cli.tui.views.base import BaseView, ScrollableViewMixin
from teleclaude.cli.tui.widgets.modal import ConfirmModal, StartSessionModal
from teleclaude.paths import TUI_STATE_PATH as _TUI_STATE_PATH

TUI_STATE_PATH = _TUI_STATE_PATH

if TYPE_CHECKING:
    from teleclaude.cli.api_client import TelecAPIClient
    from teleclaude.cli.tui.app import FocusContext

logger = get_logger(__name__)
_THINKING_BASE_TEXT = "Thinking..."
_STARTING_BASE_TEXT = "..."
_STREAMING_SAFETY_TIMEOUT = 30.0  # Safety net; agent_stop is the authoritative clear signal
_WATCHED_OUTPUT_HIGHLIGHT_TIMEOUT = 3.0


def _format_time(iso_timestamp: str | None) -> str:
    """Convert ISO timestamp to HH:MM:SS (24h) local time.

    Args:
        iso_timestamp: ISO 8601 timestamp string or None

    Returns:
        Time like "17:43:21" or "" if unavailable
    """
    if not iso_timestamp:
        return ""
    dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    local_dt = dt.astimezone()
    return local_dt.strftime("%H:%M:%S")


# Pattern matches /Users/<user>/... (macOS) or /home/<user>/... (Linux)
_HOME_PATH_PATTERN = re.compile(r"^(/(?:Users|home)/[^/]+)")


def _shorten_path(path: str) -> str:
    """Replace home directory prefix with ~ to save space.

    Works for both local paths and remote paths by detecting common
    home directory patterns (/Users/... on macOS, /home/... on Linux).

    Args:
        path: Full path string

    Returns:
        Path with home directory replaced by ~ if applicable
    """
    if not path:
        return path

    # Try local home directory first (exact match)
    local_home = os.path.expanduser("~")
    if path.startswith(local_home + "/"):
        return "~" + path[len(local_home) :]
    if path == local_home:
        return "~"

    # For remote paths, use pattern matching
    match = _HOME_PATH_PATTERN.match(path)
    if match:
        home_prefix = match.group(1)
        return "~" + path[len(home_prefix) :]

    return path


def _thinking_placeholder_text(tool_preview: str | None = None) -> str:
    """Return placeholder text shown during temporary streaming highlight.

    Args:
        tool_preview: If set, shows a compact tool activity line instead of "thinking..."
    """
    if tool_preview:
        text = tool_preview
    else:
        text = _THINKING_BASE_TEXT

    if getattr(curses, "A_ITALIC", 0):
        return text
    return f"**{text}**"


def _working_placeholder_text() -> str:
    """Return placeholder text shown after temp highlight while agent is still working."""
    if getattr(curses, "A_ITALIC", 0):
        return _STARTING_BASE_TEXT
    return f"**{_STARTING_BASE_TEXT}**"


def _temp_output_placeholder_text(active_agent: str | None, tool_preview: str | None = None) -> str:
    """Return placeholder text for temporary output highlight."""
    if tool_preview:
        return _thinking_placeholder_text(tool_preview)
    if (active_agent or "").lower() == "codex":
        return _working_placeholder_text()
    return _thinking_placeholder_text()


class SessionsView(ScrollableViewMixin[TreeNode], BaseView):
    """View 1: Sessions - project-centric tree with AI-to-AI nesting."""

    def __init__(
        self,
        api: "TelecAPIClient",
        agent_availability: dict[str, AgentAvailabilityInfo],
        focus: FocusContext,
        pane_manager: TmuxPaneManager,
        state: TuiState,
        controller: TuiController,
        on_agent_output: Callable[[str], None] | None = None,
        notify: Callable[[str, NotificationLevel], None] | None = None,
    ):
        """Initialize sessions view.

        Args:
            api: API client instance
            agent_availability: Agent availability status
            focus: Shared focus context
            pane_manager: Tmux pane manager for session preview
        """
        self.api = api
        self.agent_availability = agent_availability
        self.focus = focus
        self.pane_manager = pane_manager
        self.state = state
        self.controller = controller
        self._on_agent_output = on_agent_output
        self.notify = notify
        self.tree: list[TreeNode] = []
        self.flat_items: list[TreeNode] = []
        # State tracking for color coding (detect changes between refreshes)
        self._prev_state: dict[str, dict[str, str]] = {}  # session_id -> {input, output}
        # Store sessions for child lookup
        self._sessions: list[SessionInfo] = []
        # Store computers for SSH connection lookup
        self._computers: list[ApiComputerInfo] = []
        # Row-to-item mapping for mouse click handling (built during render)
        self._row_to_item: dict[int, int] = {}
        self._missing_last_input_logged: set[str] = set()
        # Signal for app to trigger data refresh
        self.needs_refresh: bool = False
        # Visible height for scroll calculations (updated during render)
        self._visible_height: int = 20  # Default, updated in render
        # Track rendered item range for scroll calculations
        self._last_rendered_range: tuple[int, int] = (0, 0)
        self._last_click_time: dict[int, float] = {}  # screen_row -> timestamp
        self._double_click_threshold = 0.4  # seconds
        self._pending_select_session_id: str | None = None
        self._pending_select_source: str | None = None
        self._pending_activate_session_id: str | None = None
        self._pending_activate_clear_preview: bool = False
        self._pending_focus_session_id: str | None = None
        self._pending_ready_session_id: str | None = None
        self._last_data_counts: dict[str, int] = {}
        # Pane focus detection for reverse sync (pane click → tree selection)
        self._last_detected_pane_id: str | None = None
        self._we_caused_focus: bool = False
        self._initial_layout_done: bool = False
        # Auto-clear timer for currently watched preview session.
        self._viewing_timer_session: str | None = None
        self._viewing_timer_expires: float | None = None
        # Per-session 3-second streaming timers (session_id -> expiry time)
        self._streaming_timers: dict[str, float] = {}

        # Load persisted sticky state (sessions + docs)
        load_sticky_state(self.state)

    @property
    def selected_index(self) -> int:
        return self.state.sessions.selected_index

    @selected_index.setter
    def selected_index(self, value: int) -> None:
        self.state.sessions.selected_index = value

    @property
    def scroll_offset(self) -> int:
        return self.state.sessions.scroll_offset

    @scroll_offset.setter
    def scroll_offset(self, value: int) -> None:
        self.state.sessions.scroll_offset = value

    @property
    def collapsed_sessions(self) -> set[str]:
        return self.state.sessions.collapsed_sessions

    @collapsed_sessions.setter
    def collapsed_sessions(self, value: set[str]) -> None:
        self.state.sessions.collapsed_sessions = value

    @property
    def sticky_sessions(self) -> list[StickySessionInfo]:
        return self.state.sessions.sticky_sessions

    @sticky_sessions.setter
    def sticky_sessions(self, value: list[StickySessionInfo]) -> None:
        self.state.sessions.sticky_sessions = value

    @property
    def _preview(self) -> PreviewState | None:
        return self.state.sessions.preview

    @_preview.setter
    def _preview(self, value: PreviewState | None) -> None:
        self.state.sessions.preview = value

    @property
    def _selection_method(self) -> str:
        return self.state.sessions.selection_method

    @_selection_method.setter
    def _selection_method(self, value: str) -> None:
        self.state.sessions.selection_method = value

    @property
    def _prep_sticky_previews(self) -> list[DocStickyInfo]:
        return self.state.preparation.sticky_previews

    async def refresh(
        self,
        computers: list[ApiComputerInfo],
        projects: list[ProjectWithTodosInfo],
        sessions: list[SessionInfo],
    ) -> None:
        """Refresh view data.

        Args:
            computers: List of computers
            projects: List of projects
            sessions: List of sessions
        """
        logger.debug(
            "SessionsView.refresh: %d computers, %d projects, %d sessions",
            len(computers),
            len(projects),
            len(sessions),
        )

        previous_selection = self._get_selected_key()
        last_summary_before = dict(self.state.sessions.last_summary)

        # Store sessions for child lookup
        self._sessions = sessions
        if not sessions and self._last_data_counts.get("sessions", 1) != 0:
            logger.debug("SessionsView.refresh: no sessions returned")
        self._last_data_counts["sessions"] = len(sessions)
        self.controller.update_sessions(sessions)
        self.controller.dispatch(Intent(IntentType.SYNC_SESSIONS, {"session_ids": [s.session_id for s in sessions]}))
        # Keep render summary state aligned with persisted session summaries.
        # This prevents losing "out:" content after TUI reload/reconnect.
        for session in sessions:
            summary = (session.last_output_summary or "").strip()
            if summary:
                self.state.sessions.last_summary[session.session_id] = summary

        if self.state.sessions.last_summary != last_summary_before:
            save_sticky_state(self.state)
        # Store computers for SSH connection lookup
        self._computers = computers

        # Track state changes for color coding
        self._update_activity_state(sessions)

        # Aggregate session counts and recent activity per computer
        session_counts: dict[str, int] = {}
        recent_activity: dict[str, bool] = {}
        now = datetime.now(timezone.utc)
        for session in sessions:
            comp_name = session.computer or ""
            if not comp_name:
                continue
            session_counts[comp_name] = session_counts.get(comp_name, 0) + 1

            last_activity = session.last_activity
            if last_activity:
                try:
                    last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if (now - last_dt).total_seconds() <= 300:
                        recent_activity[comp_name] = True
                except ValueError:
                    continue

        # Enrich computer data for badges
        enriched_computers: list[ComputerDisplayInfo] = []
        for computer in computers:
            name = computer.name
            enriched_computers.append(
                ComputerDisplayInfo(
                    computer=computer,
                    session_count=session_counts.get(name, 0),
                    recent_activity=bool(recent_activity.get(name, False)),
                )
            )

        project_infos = [
            ProjectInfo(
                computer=p.computer,
                name=p.name,
                path=p.path,
                description=p.description,
            )
            for p in projects
        ]
        self.tree = build_tree(enriched_computers, project_infos, sessions)
        logger.debug("Tree built with %d root nodes", len(self.tree))
        self.rebuild_for_focus()
        if self._pending_select_session_id:
            found = self._apply_pending_selection()
            if not found:
                if self.state.sessions.selected_session_id:
                    self._restore_selection(("session", self.state.sessions.selected_session_id))
                else:
                    self._restore_selection(previous_selection)
        else:
            if self.state.sessions.selected_session_id:
                self._restore_selection(("session", self.state.sessions.selected_session_id))
            else:
                self._restore_selection(previous_selection)
        if self.pane_manager.is_available and not self._initial_layout_done:
            has_expected_panes = bool(
                self.sticky_sessions or self._preview or self._prep_sticky_previews or self.state.preparation.preview
            )
            panes_missing = False
            if self.sticky_sessions or self._prep_sticky_previews:
                if not self.pane_manager.state.sticky_pane_ids:
                    panes_missing = True
            if self._preview or self.state.preparation.preview:
                if not self.pane_manager.state.parent_pane_id:
                    panes_missing = True
            if has_expected_panes and panes_missing:
                self.controller.apply_layout(focus=False)
                self._initial_layout_done = True
        self._maybe_activate_ready_session()

    def request_select_session(self, session_id: str, *, source: str | None = None) -> bool:
        """Request that a session be selected once it appears in the tree."""
        if not session_id:
            return False
        if self._pending_select_session_id == session_id:
            return False
        self._pending_select_session_id = session_id
        self._pending_select_source = source
        return True

    def _apply_pending_selection(self, *, source: str | None = None) -> bool:
        """Select any pending session once the tree is available."""
        target = self._pending_select_session_id
        if not target:
            return False
        if source is None:
            source = self._pending_select_source
        activated = self._select_session_by_id(target, source=source, activate=True)
        if activated:
            self._pending_select_session_id = None
            self._pending_select_source = None
        return activated

    def _is_session_ready_for_preview(self, session: SessionInfo) -> bool:
        if not session.tmux_session_name:
            return False
        return session.status == "active"

    def _select_session_by_id(self, session_id: str, *, source: str | None, activate: bool) -> bool:
        for idx, item in enumerate(self.flat_items):
            if is_session_node(item) and item.data.session.session_id == session_id:
                self._select_index(idx, source=source)
                self.controller.dispatch(
                    Intent(
                        IntentType.SET_SELECTION,
                        {
                            "view": "sessions",
                            "index": idx,
                            "session_id": session_id,
                            "source": source or "system",
                            "active_agent": item.data.session.active_agent,
                        },
                    )
                )
                if activate:
                    self.controller.dispatch(Intent(IntentType.SET_SELECTION_METHOD, {"method": "click"}))
                    self._schedule_activate_session(item, clear_preview=False)
                logger.debug("Selected new session %s at index %d", session_id[:8], idx)
                return True
        return False

    def detect_pane_focus_change(self) -> bool:
        """Detect user-initiated pane focus changes and sync tree selection.

        Called every loop iteration to detect when user clicks a tmux pane directly.
        When detected, fires SET_SELECTION intent with source="pane" to update tree.

        Returns:
            True if a user-initiated pane change was detected and handled.
        """
        if not self.pane_manager.is_available:
            return False

        active_pane_id = self.pane_manager.get_active_pane_id()

        # If we caused the focus change, just update tracking and skip
        if self._we_caused_focus:
            self._we_caused_focus = False
            self._last_detected_pane_id = active_pane_id
            return False

        # No change in pane focus
        if active_pane_id == self._last_detected_pane_id:
            return False

        # Pane focus changed - update tracking
        self._last_detected_pane_id = active_pane_id

        # If it's the TUI pane or no pane, nothing to sync
        if not active_pane_id:
            return False

        # Get session for this pane
        session_id = self.pane_manager.get_session_id_for_pane(active_pane_id)
        if not session_id:
            return False

        # Skip pending operations - they'll handle their own selection
        if self._pending_select_session_id or self._pending_activate_session_id:
            return False

        # User clicked a pane - sync tree selection to match
        logger.debug("Pane focus changed by user: pane=%s session=%s", active_pane_id, session_id[:8])
        return self._select_session_by_id(session_id, source="pane", activate=False)

    def _get_selected_key(self) -> tuple[str, str] | None:
        if not self.flat_items or not (0 <= self.selected_index < len(self.flat_items)):
            return None
        item = self.flat_items[self.selected_index]
        if is_session_node(item):
            return ("session", item.data.session.session_id)
        if is_project_node(item):
            return ("project", f"{item.data.computer}::{item.data.path}")
        if is_computer_node(item):
            return ("computer", item.data.computer.name)
        return None

    def _restore_selection(self, selection_key: tuple[str, str] | None) -> None:
        if not selection_key:
            return
        target_type, target_key = selection_key
        for idx, item in enumerate(self.flat_items):
            if target_type == "session" and is_session_node(item):
                if item.data.session.session_id == target_key:
                    self._select_index(idx)
                    return
            if target_type == "project" and is_project_node(item):
                item_key = f"{item.data.computer}::{item.data.path}"
                if item_key == target_key:
                    self._select_index(idx)
                    return
            if target_type == "computer" and is_computer_node(item):
                if item.data.computer.name == target_key:
                    self._select_index(idx)
                    return

    def _select_index(self, idx: int, *, source: str | None = None) -> None:
        self.selected_index = idx
        self._sync_selected_session_id(source=source)
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        else:
            _, last_rendered = self._last_rendered_range
            if self.selected_index > last_rendered:
                self.scroll_offset += self.selected_index - last_rendered

    def _sync_selected_session_id(self, *, source: str | None = None) -> None:
        item = self.flat_items[self.selected_index] if 0 <= self.selected_index < len(self.flat_items) else None
        if item and is_session_node(item):
            self.state.sessions.selected_session_id = item.data.session.session_id
            self.state.sessions.last_selection_session_id = item.data.session.session_id
            if source in ("user", "pane", "system"):
                self.state.sessions.last_selection_source = source
        else:
            self.state.sessions.selected_session_id = None

    def _revive_headless_session(self, session: SessionInfo) -> None:
        session_id = session.session_id
        computer = session.computer or "local"
        try:
            result = asyncio.get_event_loop().run_until_complete(
                self.api.send_keys(session_id=session_id, computer=computer, key="enter", count=1)
            )
            if result:
                self.request_select_session(session_id, source="user")
                self.needs_refresh = True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Failed to revive headless session %s: %s", session_id[:8], exc)
            if self.notify:
                self.notify(f"Revive failed: {exc}", NotificationLevel.ERROR)

    def _update_activity_state(self, sessions: list[SessionInfo]) -> None:
        """Update activity state tracking for animations.

        Note: SESSION_ACTIVITY intents with reason are now dispatched from app.py
        when WebSocket events arrive. This method only tracks state for animation triggers.

        Args:
            sessions: List of session dicts
        """
        for session in sessions:
            session_id = session.session_id
            curr_input = session.last_input or ""
            curr_output_digest = session.last_output_digest or ""

            # Get previous state
            prev = self._prev_state.get(session_id)
            if prev is None:
                # New session - store state
                self._prev_state[session_id] = {"input": curr_input, "output_digest": curr_output_digest}
                continue

            # Existing session - check what changed for animation triggers
            prev_output_digest = prev.get("output_digest", "")
            output_changed = curr_output_digest != prev_output_digest

            if output_changed and self._on_agent_output and session.active_agent:
                self._on_agent_output(session.active_agent)

            # Store current state for next comparison
            self._prev_state[session_id] = {"input": curr_input, "output_digest": curr_output_digest}

    def _update_viewing_timer(self) -> None:
        """Manage short auto-clear timer for actively watched preview sessions.

        If user is actively watching a selected session in the preview pane and that
        session has output highlight, clear it after a short delay. Sessions not being
        actively previewed keep their persistent highlight.
        """
        selected_id = self.state.sessions.selected_session_id
        preview_session_id = self.state.sessions.preview.session_id if self.state.sessions.preview else None
        is_actively_watched = bool(selected_id and preview_session_id == selected_id)
        now = time.monotonic()

        # Check if timer expired.
        if self._viewing_timer_session and self._viewing_timer_expires and now >= self._viewing_timer_expires:
            # Timer expired - clear highlight directly.
            if self._viewing_timer_session in self.state.sessions.output_highlights:
                self.state.sessions.output_highlights.discard(self._viewing_timer_session)
                logger.debug(
                    "Watched preview timer expired (%.1fs), cleared highlight for %s",
                    _WATCHED_OUTPUT_HIGHLIGHT_TIMEOUT,
                    self._viewing_timer_session[:8],
                )
            self._viewing_timer_session = None
            self._viewing_timer_expires = None

        # Cancel timer when watched context changed or highlight is gone.
        if self._viewing_timer_session and (
            not is_actively_watched
            or selected_id != self._viewing_timer_session
            or self._viewing_timer_session not in self.state.sessions.output_highlights
        ):
            self._viewing_timer_session = None
            self._viewing_timer_expires = None

        # Start timer only for actively watched preview sessions.
        if (
            is_actively_watched
            and selected_id is not None
            and selected_id in self.state.sessions.output_highlights
            and self._viewing_timer_session != selected_id
        ):
            self._viewing_timer_session = selected_id
            self._viewing_timer_expires = now + _WATCHED_OUTPUT_HIGHLIGHT_TIMEOUT
            logger.debug(
                "Started watched preview timer (%.1fs) for session %s",
                _WATCHED_OUTPUT_HIGHLIGHT_TIMEOUT,
                selected_id[:8],
            )

    def _update_streaming_timers(self) -> None:
        """Manage safety timers for streaming output highlights.

        Agent activity events (tool_use, tool_done) set temp_output_highlights.
        agent_stop is the authoritative signal that clears them. The timer is a safety
        net that clears stale highlights if agent_stop is missed.
        """
        now = time.monotonic()

        # Reset timers for sessions with new activity events
        for session_id in list(self.state.sessions.activity_timer_reset):
            if session_id in self._streaming_timers:
                self._streaming_timers[session_id] = now + _STREAMING_SAFETY_TIMEOUT
                logger.debug("Reset streaming timer for %s (new activity)", session_id[:8])
        self.state.sessions.activity_timer_reset.clear()

        # Check for expired timers
        expired = [sid for sid, expiry in self._streaming_timers.items() if now >= expiry]
        for session_id in expired:
            del self._streaming_timers[session_id]
            if session_id in self.state.sessions.temp_output_highlights:
                self.controller.dispatch(Intent(IntentType.CLEAR_TEMP_HIGHLIGHT, {"session_id": session_id}))
                logger.debug("Streaming safety timer expired for %s, cleared temp highlight", session_id[:8])

        # Start timers for sessions with temp highlights that don't have one yet
        for session_id in self.state.sessions.temp_output_highlights:
            if session_id not in self._streaming_timers:
                self._streaming_timers[session_id] = now + _STREAMING_SAFETY_TIMEOUT
                logger.debug("Started streaming safety timer for %s", session_id[:8])

        # Remove timers for sessions no longer in temp highlights
        stale = [sid for sid in self._streaming_timers if sid not in self.state.sessions.temp_output_highlights]
        for session_id in stale:
            del self._streaming_timers[session_id]

    def update_session_node(self, session: SessionInfo) -> bool:
        """Update a session node in the tree if it exists."""
        session_id = session.session_id

        def walk(nodes: list[TreeNode]) -> bool:
            for node in nodes:
                if is_session_node(node):
                    node_session_id = node.data.session.session_id
                    if node_session_id == session_id:
                        node.data = SessionDisplayInfo(
                            session=session,
                            display_index=node.data.display_index,
                        )
                        return True
                if node.children and walk(node.children):
                    return True
            return False

        updated = walk(self.tree)
        if updated:
            self._maybe_activate_ready_session()
        return updated

    def sync_layout(self) -> None:
        """Sync pane layout with current session list."""
        session_ids = {session.session_id for session in self._sessions}
        self.controller.dispatch(Intent(IntentType.SYNC_SESSIONS, {"session_ids": list(session_ids)}))

    def rebuild_for_focus(self) -> None:
        """Rebuild flat_items based on current focus context."""
        logger.debug(
            "SessionsView.rebuild_for_focus: focus.computer=%s, focus.project=%s",
            self.focus.computer,
            self.focus.project,
        )

        # Start from root and filter based on focus
        nodes = self.tree

        # If focused on a computer, filter to that computer's children
        if self.focus.computer:
            for node in self.tree:
                if is_computer_node(node) and node.data.computer.name == self.focus.computer:
                    nodes = node.children
                    logger.debug("Filtered to computer '%s': %d children", self.focus.computer, len(nodes))
                    break
            else:
                nodes = []  # Computer not found
                logger.warning("Computer '%s' not found in tree", self.focus.computer)

        # If also focused on a project, filter to that project's children
        if self.focus.project and nodes:
            for node in nodes:
                if is_project_node(node) and node.data.path == self.focus.project:
                    nodes = node.children
                    logger.debug("Filtered to project '%s': %d children", self.focus.project, len(nodes))
                    break
            else:
                nodes = []  # Project not found
                logger.warning("Project '%s' not found in tree", self.focus.project)

        self.flat_items = self._flatten_tree(nodes, base_depth=0)
        logger.debug("Flattened to %d items", len(self.flat_items))

        if self.state.sessions.selected_session_id:
            for idx, item in enumerate(self.flat_items):
                if is_session_node(item) and item.data.session.session_id == self.state.sessions.selected_session_id:
                    self._select_index(idx)
                    break
        # Reset selection if out of bounds
        if self.selected_index >= len(self.flat_items):
            self._select_index(0)
        # Clamp scroll_offset to valid range (don't reset to 0 — _select_index
        # already adjusts scroll to keep the selected item visible, and resetting
        # here causes a visible one-line jump on every WebSocket data refresh).
        max_offset = max(0, len(self.flat_items) - 1)
        if self.scroll_offset > max_offset:
            self.scroll_offset = max_offset
        self._sync_selected_session_id()

    def _flatten_tree(self, nodes: list[TreeNode], base_depth: int = 0) -> list[TreeNode]:
        """Flatten tree for navigation.

        Args:
            nodes: Tree nodes
            base_depth: Base depth offset for rendering

        Returns:
            Flattened list of nodes with adjusted depth
        """
        result: list[TreeNode] = []
        for node in nodes:
            display_node: TreeNode
            if is_computer_node(node):
                display_node = ComputerNode(
                    type=NodeType.COMPUTER,
                    data=node.data,
                    depth=base_depth,
                    children=node.children,
                    parent=node.parent,
                )
            elif is_project_node(node):
                display_node = ProjectNode(
                    type=NodeType.PROJECT,
                    data=node.data,
                    depth=base_depth,
                    children=node.children,
                    parent=node.parent,
                )
            else:
                display_node = SessionNode(
                    type=NodeType.SESSION,
                    data=node.data,
                    depth=base_depth,
                    children=node.children,
                    parent=node.parent,
                )
            result.append(display_node)
            result.extend(self._flatten_tree(node.children, base_depth + 1))
        return result

    def get_action_bar(self) -> str:
        """Return action bar string based on selected item type.

        Returns:
            Context-appropriate action bar text
        """
        back_hint = "[←] Back  " if self.focus.stack else ""

        if not self.flat_items or self.selected_index >= len(self.flat_items):
            return back_hint.strip() if back_hint else ""

        selected = self.flat_items[self.selected_index]
        if is_session_node(selected):
            # Show toggle state in action bar
            preview_action = "[Enter] Preview"
            return f"{back_hint}{preview_action}  [←/→] Collapse/Expand  [R] Restart  [k] Kill"
        if is_project_node(selected):
            # Check if any sessions for this project are sticky
            project = selected.data
            project_sessions = [
                session
                for session in self._sessions
                if session.project_path == project.path and (session.computer or "") == project.computer
            ]
            project_session_ids = {session.session_id for session in project_sessions}
            has_sticky = any(s.session_id in project_session_ids for s in self.sticky_sessions)

            sessions_action = "[a] Close Sessions" if has_sticky else "[a] Open Sessions"
            return f"{back_hint}[n] New Session  {sessions_action}"
        # computer
        return f"{back_hint}[→] View Projects  [R] Restart Agents"

    def get_session_ids_for_computer(self, computer_name: str) -> list[str]:
        """Return session IDs for the given computer."""
        if not computer_name:
            return []
        return [session.session_id for session in self._sessions if session.computer == computer_name]

    # move_up() and move_down() inherited from ScrollableViewMixin
    # Override them to track selection method

    def move_up(self) -> None:
        """Move selection up (arrow key navigation)."""
        super().move_up()
        self._sync_selected_session_id(source="user")
        self.controller.dispatch(Intent(IntentType.SET_SELECTION_METHOD, {"method": "arrow"}))

    def move_down(self) -> None:
        """Move selection down (arrow key navigation)."""
        super().move_down()
        self._sync_selected_session_id(source="user")
        self.controller.dispatch(Intent(IntentType.SET_SELECTION_METHOD, {"method": "arrow"}))

    def _focus_selected_pane(self) -> None:
        """Focus the pane for currently selected session."""
        if not self.flat_items or self.selected_index >= len(self.flat_items):
            return

        item = self.flat_items[self.selected_index]
        if not is_session_node(item):
            return

        session_id = item.data.session.session_id
        self.pane_manager.focus_pane_for_session(session_id)

    def drill_down(self) -> bool:
        """Drill down into selected item (arrow right).

        For computers: navigate into them (show projects).
        For projects: do nothing - sessions are already visible as children.
        For sessions: expand to show input/output.

        Returns:
            True if action taken, False if not possible
        """
        if not self.flat_items or self.selected_index >= len(self.flat_items):
            logger.debug("drill_down: no items or invalid index")
            return False

        item = self.flat_items[self.selected_index]
        logger.debug("drill_down: item.type=%s", item.type)

        if is_computer_node(item):
            self.focus.push(FocusLevelType.COMPUTER, item.data.computer.name)
            self.rebuild_for_focus()
            self._select_index(0, source="user")
            logger.debug("drill_down: pushed computer focus")
            return True
        if is_session_node(item):
            # Expand this session (if not already expanded)
            session_id = item.data.session.session_id
            if session_id in self.collapsed_sessions:
                self.controller.dispatch(Intent(IntentType.EXPAND_SESSION, {"session_id": session_id}))
                logger.debug("drill_down: expanded session %s", session_id[:8])
                return True
            logger.debug("drill_down: session already expanded")
            return False  # Already expanded
        # Projects don't drill down - sessions are visible as children
        logger.debug("drill_down: no action for type=%s", item.type)
        return False

    def collapse_selected(self) -> bool:
        """Collapse selected session (arrow left on session).

        Returns:
            True if collapsed, False if not a session or already collapsed
        """
        if not self.flat_items or self.selected_index >= len(self.flat_items):
            logger.debug("collapse_selected: no items or invalid index")
            return False

        item = self.flat_items[self.selected_index]
        logger.debug("collapse_selected: item.type=%s", item.type)

        if is_session_node(item):
            session_id = item.data.session.session_id
            if session_id not in self.collapsed_sessions:
                self.controller.dispatch(Intent(IntentType.COLLAPSE_SESSION, {"session_id": session_id}))
                logger.debug("collapse_selected: collapsed session %s", session_id[:8])
                return True
            logger.debug("collapse_selected: session already collapsed")
            return False  # Already collapsed - let navigation take over
        logger.debug("collapse_selected: not a session, returning False")
        return False

    def expand_all(self) -> None:
        """Expand all sessions (show input/output)."""
        logger.debug("expand_all: clearing collapsed_sessions (was %d)", len(self.collapsed_sessions))
        self.controller.dispatch(Intent(IntentType.EXPAND_ALL_SESSIONS))

    def collapse_all(self) -> None:
        """Collapse all sessions (hide input/output)."""
        logger.debug("collapse_all: collecting all session IDs")
        self._collect_all_session_ids(self.tree)
        self.controller.dispatch(
            Intent(IntentType.COLLAPSE_ALL_SESSIONS, {"session_ids": list(self.collapsed_sessions)})
        )
        logger.debug("collapse_all: collapsed_sessions now has %d entries", len(self.collapsed_sessions))

    def _collect_all_session_ids(self, nodes: list[TreeNode]) -> None:
        """Recursively collect all session IDs into collapsed_sessions.

        Args:
            nodes: Tree nodes to scan
        """
        for node in nodes:
            if is_session_node(node):
                self.collapsed_sessions.add(node.data.session.session_id)
            if node.children:
                self._collect_all_session_ids(node.children)

    def handle_enter(self, stdscr: CursesWindow) -> None:
        """Handle Enter key - perform action on selected item.

        Only activates sessions if navigated via arrow keys (not after single-click).

        Args:
            stdscr: Curses screen object
        """
        if not self.flat_items:
            return
        enter_start = time.perf_counter()
        item = self.flat_items[self.selected_index]

        if is_computer_node(item):
            # Drill down into computer (same as right arrow)
            self.drill_down()
        elif is_project_node(item):
            # Start new session on project
            self._start_session_for_project(stdscr, item.data)
        elif is_session_node(item):
            # Activate session (same behavior as clicking)
            self._schedule_activate_session(item)
            logger.trace(
                "sessions_enter",
                item_type="session",
                action="activate",
                duration_ms=int((time.perf_counter() - enter_start) * 1000),
            )

    def _get_computer_info(self, computer_name: str) -> ComputerInfo | None:
        """Get SSH connection info for a computer.

        Args:
            computer_name: Computer name to look up

        Returns:
            ComputerInfo with user/host for SSH, or None if not found
        """
        for comp in self._computers:
            if comp.name == computer_name:
                return ComputerInfo(
                    name=computer_name,
                    is_local=comp.is_local,
                    user=comp.user,
                    host=comp.host,
                    tmux_binary=comp.tmux_binary,
                )
        return None

    def _toggle_sticky(self, session_id: str, *, active_agent: str | None = None, clear_preview: bool = False) -> None:
        """Toggle sticky state for a session (max 5 sessions).

        Args:
            session_id: Session ID to toggle
            clear_preview: Whether to clear preview before toggling sticky
        """
        existing_idx = None
        for i, sticky in enumerate(self.sticky_sessions):
            if sticky.session_id == session_id:
                existing_idx = i
                break

        if existing_idx is None and (len(self.sticky_sessions) + len(self._prep_sticky_previews)) >= 5:
            if self.notify:
                self.notify("Maximum 5 sticky sessions", NotificationLevel.WARNING)
            logger.warning("Cannot add sticky session %s: maximum 5 reached", session_id[:8])
            return
        if existing_idx is None and any(s.session_id == session_id for s in self.sticky_sessions):
            logger.error("BUG: Attempted to add duplicate session_id %s to sticky list", session_id[:8])
            return

        if clear_preview and self._preview:
            self.controller.dispatch(Intent(IntentType.CLEAR_PREVIEW), defer_layout=True)
        self.controller.dispatch(
            Intent(IntentType.TOGGLE_STICKY, {"session_id": session_id, "active_agent": active_agent}),
            defer_layout=True,
        )
        logger.info("Toggled sticky: %s (total=%d)", session_id[:8], len(self.sticky_sessions))

    def _activate_session(self, item: SessionNode, *, clear_preview: bool = False) -> None:
        """Activate a single session (single-click or Enter from arrows).

        Shows the session in preview mode without affecting sticky panes.
        If session is already sticky, hides the active pane entirely.

        Args:
            item: Session node to activate
            clear_preview: Whether to clear preview before activating
        """
        session = item.data.session
        session_id = session.session_id
        tmux_session = session.tmux_session_name or ""

        logger.info(
            "_activate_session: session_id=%s, tmux=%s, sticky_count=%d, sticky_ids=%s",
            session_id[:8],
            tmux_session or "MISSING",
            len(self.sticky_sessions),
            [s.session_id[:8] for s in self.sticky_sessions],
        )

        if not tmux_session:
            logger.warning("_activate_session: tmux_session_name missing, attempting revive")
            self._revive_headless_session(session)
            return

        # If session is already sticky, hide active pane (no duplication)
        is_already_sticky = any(sticky.session_id == session_id for sticky in self.sticky_sessions)
        if is_already_sticky:
            logger.info(
                "_activate_session: session %s ALREADY STICKY, hiding active pane",
                session_id[:8],
            )
            if self._preview:
                self.controller.dispatch(Intent(IntentType.CLEAR_PREVIEW), defer_layout=True)
            return

        if clear_preview and self._preview:
            self.controller.dispatch(Intent(IntentType.CLEAR_PREVIEW), defer_layout=True)
        self.controller.dispatch(
            Intent(
                IntentType.SET_PREVIEW,
                {"session_id": session_id, "active_agent": session.active_agent},
            ),
            defer_layout=True,
        )
        logger.debug(
            "_activate_session: showing session in active pane (sticky_count=%d)",
            len(self.sticky_sessions),
        )

    def _schedule_activate_session(self, item: SessionNode, *, clear_preview: bool = False) -> None:
        """Defer activation so selection is rendered immediately."""
        session = item.data.session
        session_id = session.session_id
        is_headless = session.status == "headless" or not session.tmux_session_name
        # Headless sessions bypass readiness check - _activate_session handles revival
        if not is_headless and not self._is_session_ready_for_preview(session):
            if self._pending_ready_session_id != session_id:
                if self.notify:
                    self.notify("Spawning new session...", NotificationLevel.INFO)
                self._pending_ready_session_id = session_id
            return
        if is_headless and self.notify:
            self.notify("Adopting headless session...", NotificationLevel.INFO)
        if self._pending_ready_session_id == session_id:
            self._pending_ready_session_id = None
        self._pending_activate_session_id = session_id
        self._pending_activate_clear_preview = clear_preview

    def apply_pending_activation(self) -> None:
        """Apply any deferred activation once per loop tick."""
        target = self._pending_activate_session_id
        if not target:
            return
        clear_preview = self._pending_activate_clear_preview
        self._pending_activate_session_id = None
        self._pending_activate_clear_preview = False

        for item in self.flat_items:
            if is_session_node(item) and item.data.session.session_id == target:
                self._activate_session(item, clear_preview=clear_preview)
                self._queue_focus_session(target)
                return

    def _queue_focus_session(self, session_id: str) -> None:
        """Request pane focus after the next layout apply."""
        self._pending_focus_session_id = session_id

    def apply_pending_focus(self) -> None:
        """Focus the requested session pane after layout changes settle."""
        session_id = self._pending_focus_session_id
        if not session_id:
            return
        self._pending_focus_session_id = None
        self._we_caused_focus = True  # Mark that we triggered focus, not user
        self.pane_manager.focus_pane_for_session(session_id)

    def _maybe_activate_ready_session(self) -> None:
        """Activate a pending session once it is ready for preview."""
        session_id = self._pending_ready_session_id
        if not session_id:
            return
        if self.state.sessions.selected_session_id != session_id:
            return
        session = next((s for s in self._sessions if s.session_id == session_id), None)
        if not session or not self._is_session_ready_for_preview(session):
            return
        for item in self.flat_items:
            if is_session_node(item) and item.data.session.session_id == session_id:
                self._schedule_activate_session(item, clear_preview=False)
                return

    def _toggle_session_pane(self, item: SessionNode) -> None:
        """Toggle session preview pane visibility.

        Args:
            item: Session node
        """
        session = item.data.session
        session_id = session.session_id
        tmux_session = session.tmux_session_name or ""
        computer_name = session.computer or "local"
        agent = session.active_agent

        logger.debug(
            "_toggle_session_pane: session_id=%s, tmux=%s, computer=%s",
            session_id[:8] if session_id else "?",
            tmux_session or "MISSING",
            computer_name,
        )

        if not tmux_session:
            logger.warning("_toggle_session_pane: tmux_session_name missing, attempting revive")
            self._revive_headless_session(session)
            return

        computer_info = self._get_computer_info(computer_name)

        self.pane_manager.toggle_session(
            tmux_session,
            agent,
            computer_info,
            session_id=session_id,
        )

    def _start_session_for_project(self, stdscr: CursesWindow, project: ProjectInfo) -> None:
        """Open modal to start session on project.

        Args:
            stdscr: Curses screen object
            project: Project data
        """
        # Use project's computer field, fallback to focused computer, then "local"
        computer_value = project.computer or self.focus.computer or "local"
        logger.info(
            "_start_session_for_project: project_computer=%s, focus_computer=%s, resolved=%s",
            project.computer,
            self.focus.computer,
            computer_value,
        )
        modal = StartSessionModal(
            computer=str(computer_value),
            project_path=project.path,
            api=self.api,
            agent_availability=self.agent_availability,
            notify=self.notify,
        )
        result = modal.run(stdscr)
        if result:
            self._attach_new_session(result, str(computer_value), stdscr)
            self.needs_refresh = True
        elif modal.start_requested:
            self.needs_refresh = True

    def _attach_new_session(
        self,
        result: CreateSessionResult,
        computer: str,
        stdscr: CursesWindow,
    ) -> None:
        """Attach newly created session to the side pane immediately."""
        tmux_session_name = result.tmux_session_name or ""
        if not tmux_session_name:
            logger.warning("New session missing tmux_session_name, cannot attach")
            return
        if result.session_id:
            self.request_select_session(result.session_id, source="user")
            self._apply_pending_selection(source="user")

        if not self.pane_manager.is_available:
            attach_tmux_from_result(result, stdscr)

    def _collect_project_session_ids_in_view(self, project: ProjectInfo) -> list[str]:
        """Collect project session ids in the current tree order."""
        if not self.flat_items:
            return []

        start_idx: int | None = None
        if 0 <= self.selected_index < len(self.flat_items):
            selected_item = self.flat_items[self.selected_index]
            if (
                is_project_node(selected_item)
                and selected_item.data.path == project.path
                and selected_item.data.computer == project.computer
            ):
                start_idx = self.selected_index
        if start_idx is None:
            for idx, item in enumerate(self.flat_items):
                if is_project_node(item) and item.data.path == project.path and item.data.computer == project.computer:
                    start_idx = idx
                    break

        if start_idx is None:
            return []

        base_depth = self.flat_items[start_idx].depth
        session_ids: list[str] = []
        for item in self.flat_items[start_idx + 1 :]:
            if item.depth <= base_depth:
                break
            if is_session_node(item):
                session_ids.append(item.data.session.session_id)
        return session_ids

    def _open_project_sessions(self, project: ProjectInfo) -> None:
        """Toggle sticky sessions for a project.

        First press: Make first 5 sessions sticky
        Second press: Remove sticky sessions and close panes
        """
        if not project.path:
            logger.debug("_open_project_sessions: missing project path")
            return

        session_by_id = {session.session_id: session for session in self._sessions}
        ordered_ids = self._collect_project_session_ids_in_view(project)
        if ordered_ids:
            project_sessions = [session_by_id[session_id] for session_id in ordered_ids if session_id in session_by_id]
        else:
            project_sessions = [
                session
                for session in self._sessions
                if session.project_path == project.path and (session.computer or "") == project.computer
            ]

        if not project_sessions:
            if self.notify:
                self.notify("No sessions found for project", NotificationLevel.INFO)
            logger.debug("_open_project_sessions: no matching sessions for %s", project.path)
            return

        project_session_ids = {session.session_id for session in project_sessions}

        # Check if any of the project's sessions are currently sticky
        sticky_project_sessions = [s for s in self.sticky_sessions if s.session_id in project_session_ids]

        if sticky_project_sessions:
            # Toggle OFF: Remove all sticky sessions for this project
            if self._preview:
                self.controller.dispatch(Intent(IntentType.CLEAR_PREVIEW), defer_layout=True)
            for sticky in sticky_project_sessions:
                self.controller.dispatch(
                    Intent(
                        IntentType.TOGGLE_STICKY,
                        {
                            "session_id": sticky.session_id,
                            "active_agent": session_by_id[sticky.session_id].active_agent
                            if sticky.session_id in session_by_id
                            else None,
                        },
                    ),
                    defer_layout=True,
                )
            logger.info("_open_project_sessions: closed %d sticky sessions for project", len(sticky_project_sessions))
            return

        # Toggle ON: Make first 5 sessions sticky
        tmux_sessions = [session for session in project_sessions if session.tmux_session_name]
        if not tmux_sessions:
            if self.notify:
                self.notify("No attachable sessions found for project", NotificationLevel.INFO)
            logger.debug("_open_project_sessions: no tmux sessions for %s", project.path)
            return

        max_sticky = 5
        if len(tmux_sessions) > max_sticky and self.notify:
            self.notify(
                f"Showing first {max_sticky} sessions (max 5 sticky panes)",
                NotificationLevel.WARNING,
            )

        current_sticky_ids = {s.session_id for s in self.sticky_sessions}
        if self._preview:
            self.controller.dispatch(Intent(IntentType.CLEAR_PREVIEW), defer_layout=True)
        for session in tmux_sessions[:max_sticky]:
            if session.session_id in current_sticky_ids:
                continue
            self.controller.dispatch(
                Intent(
                    IntentType.TOGGLE_STICKY,
                    {"session_id": session.session_id, "active_agent": session.active_agent},
                ),
                defer_layout=True,
            )

    def handle_key(self, key: int, stdscr: CursesWindow) -> None:
        """Handle view-specific keys.

        Args:
            key: Key code
            stdscr: Curses screen object
        """
        key_char = chr(key) if 32 <= key < 127 else f"({key})"
        logger.debug("SessionsView.handle_key: key=%s (%d)", key_char, key)

        # Global expand/collapse (works even with no selection)
        if key == ord("+") or key == ord("="):  # = for convenience (shift not needed)
            logger.debug("handle_key: expand_all triggered")
            self.expand_all()
            return
        if key == ord("-"):
            logger.debug("handle_key: collapse_all triggered")
            self.collapse_all()
            return

        if not self.flat_items or self.selected_index >= len(self.flat_items):
            logger.debug("handle_key: no items or invalid index, ignoring key")
            return

        selected = self.flat_items[self.selected_index]
        logger.debug("handle_key: selected.type=%s", selected.type)

        if key == ord("n"):
            # Start new session - only on project
            if is_project_node(selected):
                logger.debug("handle_key: starting new session on project")
                self._start_session_for_project(stdscr, selected.data)
            else:
                logger.debug("handle_key: 'n' ignored, not on a project")
            return
        if key in (ord("a"), ord("A")):
            if is_project_node(selected):
                logger.debug("handle_key: opening all sessions for project")
                self._open_project_sessions(selected.data)
            else:
                logger.debug("handle_key: 'a' ignored, not on a project")
            return

        if key == ord("k"):
            # Kill selected session
            if not is_session_node(selected):
                logger.debug("handle_key: 'k' ignored, not on a session")
                return  # Only kill sessions, not computers/projects

            session = selected.data.session
            session_id = session.session_id
            computer = session.computer or ""
            title = session.title

            # Confirm kill with modal
            modal = ConfirmModal(
                title="Kill Session",
                message="Are you sure you want to kill this session?",
                details=[
                    f"Title: {title}",
                    f"Computer: {computer}",
                    f"Session ID: {session_id[:16]}...",
                ],
            )
            if not modal.run(stdscr):
                return  # Cancelled

            try:
                result = asyncio.get_event_loop().run_until_complete(
                    self.api.end_session(session_id=session_id, computer=computer)
                )
                if result:
                    self.needs_refresh = True
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error killing session: %s", e)

    def handle_click(self, screen_row: int, is_double_click: bool = False) -> bool:
        """Handle mouse click at screen row.

        Single click: Select and activate session
        Double click on title: Toggle sticky with parent + child
        Double click on ID line: Toggle sticky with parent only

        Args:
            screen_row: The screen row that was clicked
            is_double_click: True if this is a double-click event (from curses BUTTON1_DOUBLE_CLICKED)

        Returns:
            True if an item was selected, False otherwise
        """
        click_start = time.perf_counter()
        item_idx = self._row_to_item.get(screen_row)
        if item_idx is None:
            logger.trace(
                "sessions_click_miss",
                row=screen_row,
                duration_ms=int((time.perf_counter() - click_start) * 1000),
            )
            return False

        item = self.flat_items[item_idx]

        # Handle double-click on session nodes
        if is_double_click and is_session_node(item):
            session_id = item.data.session.session_id
            self._toggle_sticky(session_id, active_agent=item.data.session.active_agent, clear_preview=True)
            logger.debug("Double-click: toggled sticky for %s", session_id[:8])

            logger.trace(
                "sessions_double_click",
                row=screen_row,
                session_id=session_id[:8],
                duration_ms=int((time.perf_counter() - click_start) * 1000),
            )
            # Select the item but don't activate (sticky toggle is the action)
            self._select_index(item_idx, source="user")
            self.controller.dispatch(Intent(IntentType.SET_SELECTION_METHOD, {"method": "click"}))
            self._queue_focus_session(session_id)
            return True

        # SINGLE CLICK - select and activate (preview lane) or highlight sticky (sticky lane)
        self._select_index(item_idx, source="user")
        self.controller.dispatch(Intent(IntentType.SET_SELECTION_METHOD, {"method": "click"}))

        # Activate session immediately on single click
        if is_session_node(item):
            session_id = item.data.session.session_id
            is_sticky = any(sticky.session_id == session_id for sticky in self.sticky_sessions)
            if is_sticky:
                # Don't clear preview here — the layout change causes a visible
                # screen jump.  The preview pane will be replaced naturally on
                # the next non-sticky activation.
                self._queue_focus_session(session_id)
            else:
                self._schedule_activate_session(item, clear_preview=False)

        logger.trace(
            "sessions_click",
            row=screen_row,
            item_type=item.type,
            duration_ms=int((time.perf_counter() - click_start) * 1000),
        )
        return True

    def get_render_lines(self, width: int, height: int) -> list[str]:
        """Return lines this view would render (testable without curses).

        Args:
            width: Tmux width
            height: Tmux height

        Returns:
            List of strings representing what would be rendered
        """
        lines: list[str] = []

        if not self.flat_items:
            lines.append("(no items)")
            return lines

        # Calculate scroll range
        max_scroll = max(0, len(self.flat_items) - height + 3)
        scroll_offset = max(0, min(self.scroll_offset, max_scroll))

        for i, item in enumerate(self.flat_items):
            # Skip items before scroll offset
            if i < scroll_offset:
                continue
            if len(lines) >= height:
                break  # No more space

            is_selected = i == self.selected_index
            item_lines = self._format_item(item, width, is_selected)
            lines.extend(item_lines)

        return lines

    def _format_item(self, item: TreeNode, width: int, selected: bool) -> list[str]:
        """Format a single tree item for display.

        Args:
            item: Tree node
            width: Screen width
            selected: Whether this item is selected

        Returns:
            List of formatted lines for this item
        """
        if is_computer_node(item):
            name = item.data.computer.name
            session_count = item.data.session_count
            suffix = f"({session_count})" if session_count else ""
            line = f"🖥  {name} {suffix}"
            return [line[:width]]

        if is_project_node(item):
            path = _shorten_path(item.data.path)
            session_count = len(item.children)
            suffix = f"({session_count})" if session_count else ""
            line = f"📁 {path} {suffix}"
            return [line[:width]]

        if is_session_node(item):
            return self._format_session(item, width, selected)

        return [""]

    def _format_session(self, item: SessionNode, width: int, selected: bool) -> list[str]:  # noqa: ARG002
        """Format session for display (1-3 lines).

        Args:
            item: Session node
            width: Screen width
            selected: Whether selected (currently unused but kept for consistency)

        Returns:
            List of formatted lines (1-3 depending on content and collapsed state)
        """
        session_display = item.data
        session = session_display.session
        session_id = session.session_id
        is_collapsed = session_id in self.collapsed_sessions

        agent = session.active_agent or "?"
        mode = session.thinking_mode or "?"
        title = session.title
        idx = session_display.display_index

        # Child indentation: 2 spaces per nesting level
        # Parent (depth 2) = 0, Child (depth 3) = 2, Grandchild (depth 4) = 4
        child_indent = " " * (max(0, item.depth - 2) * 2)

        # Collapse indicator
        collapse_indicator = "▶" if is_collapsed else "▼"

        # Title line uses child indentation
        if session.subdir:
            subdir_part = f" {session.subdir.removeprefix('trees/')} "
            line1 = f'{child_indent}[{idx}] {collapse_indicator} {agent}/{mode}{subdir_part}"{title}"'
        else:
            line1 = f'{child_indent}[{idx}] {collapse_indicator} {agent}/{mode}  "{title}"'
        lines: list[str] = []
        lines.append(line1[:width])

        # If collapsed, only show title line
        if is_collapsed:
            return lines

        # Detail lines: child indentation + 4 spaces (expansion offset)
        detail_indent = child_indent + "    "

        # Line 2 (expanded only): ID + last activity time
        activity_time = _format_time(session.last_activity)
        native_session_id = session.native_session_id or "-"
        line2 = f"{detail_indent}[{activity_time}] {session_id} / {native_session_id}"
        lines.append(line2[:width])

        # Line 3: Last input (only if content exists)
        last_input = (session.last_input or "").strip()
        last_input_at = session.last_input_at
        if last_input:
            input_text = last_input.replace("\n", " ")[:60]
            input_time = _format_time(last_input_at)
            line3 = f"{detail_indent}[{input_time}] in: {input_text}"
            lines.append(line3[:width])

        # Line 4: Last output — driven by activity events, not session record
        last_output = self.state.sessions.last_summary.get(session_id, "")
        has_input_highlight = session_id in self.state.sessions.input_highlights
        has_temp_output_highlight = session_id in self.state.sessions.temp_output_highlights
        activity_time = _format_time(session.last_activity)
        if has_temp_output_highlight:
            tool_preview = self.state.sessions.active_tool.get(session_id)
            line4 = (
                f"{detail_indent}[{activity_time}] out: "
                f"{_temp_output_placeholder_text(session.active_agent, tool_preview)}"
            )
            lines.append(line4[:width])
        elif has_input_highlight:
            line4 = f"{detail_indent}[{activity_time}] out: {_working_placeholder_text()}"
            lines.append(line4[:width])
        elif last_output:
            output_text = last_output.replace("\n", " ")[:60]
            line4 = f"{detail_indent}[{activity_time}] out: {output_text}"
            lines.append(line4[:width])

        return lines

    def render(self, stdscr: CursesWindow, start_row: int, height: int, width: int) -> None:
        """Render view content with scrolling support.

        Args:
            stdscr: Curses screen object
            start_row: Starting row
            height: Available height
            width: Screen width
        """
        # Store visible height for scroll calculations
        self._visible_height = height

        # Check/update viewing timer for auto-clear
        self._update_viewing_timer()
        # Check/update streaming timers for 3s output highlights
        self._update_streaming_timers()

        logger.trace(
            "SessionsView.render: start_row=%d, height=%d, width=%d, flat_items=%d, scroll=%d",
            start_row,
            height,
            width,
            len(self.flat_items),
            self.scroll_offset,
        )

        # Clear row-to-item mapping (rebuilt each render)
        self._row_to_item.clear()

        if not self.flat_items:
            msg = "(no items)"
            stdscr.addstr(start_row, 2, msg, curses.A_DIM)  # type: ignore[attr-defined]
            return

        # Clamp scroll_offset to valid range
        max_scroll = max(0, len(self.flat_items) - height + 3)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))

        row = start_row
        items_rendered = 0
        first_rendered = self.scroll_offset
        last_rendered = self.scroll_offset
        for i, item in enumerate(self.flat_items):
            # Skip items before scroll offset
            if i < self.scroll_offset:
                continue
            if row >= start_row + height:
                break  # No more space

            last_rendered = i
            is_selected = i == self.selected_index
            remaining = start_row + height - row
            lines_used = self._render_item(stdscr, row, item, width, is_selected, remaining)
            # Map all lines of this item to its index (for mouse click)
            for offset in range(lines_used):
                screen_row = row + offset
                self._row_to_item[screen_row] = i
            row += lines_used
            items_rendered += 1

        # Track rendered range for scroll calculations
        self._last_rendered_range = (first_rendered, last_rendered)

        logger.trace(
            "render: rendered %d of %d items (scroll_offset=%d)",
            items_rendered,
            len(self.flat_items),
            self.scroll_offset,
        )

    def _render_item(
        self,
        stdscr: CursesWindow,
        row: int,
        item: TreeNode,
        width: int,
        selected: bool,
        remaining: int,
    ) -> int:
        """Render a single tree item.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            item: Tree node
            width: Screen width
            selected: Whether this item is selected

        Returns:
            Number of lines used
        """
        attr = curses.A_REVERSE if selected else 0

        if remaining <= 0:
            return 0
        if is_computer_node(item):
            name = item.data.computer.name
            session_count = item.data.session_count
            suffix = f"({session_count})" if session_count else ""
            line = f"🖥  {name} {suffix}"
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1
        if is_project_node(item):
            path = _shorten_path(item.data.path)
            session_count = len(item.children)
            suffix = f"({session_count})" if session_count else ""
            line = f"📁 {path} {suffix}"
            # Mute empty projects
            if not session_count and not selected:
                attr = curses.A_DIM
            stdscr.addstr(row, 0, line[:width], attr)  # type: ignore[attr-defined]
            return 1
        if is_session_node(item):
            return self._render_session(stdscr, row, item, width, selected, remaining)
        return 1

    def _render_session(
        self,
        stdscr: CursesWindow,
        row: int,
        item: SessionNode,
        width: int,
        selected: bool,
        remaining: int,
    ) -> int:
        """Render session with agent-colored text (1-3 lines).

        Color coding rules:
        - Input bright + Output muted/none = processing input
        - Input muted + Output bright = AI just responded
        - Both muted = idle (no changes on refresh)

        Args:
            stdscr: Curses screen object
            row: Row to render at
            item: Session node
            width: Screen width
            selected: Whether this item is selected

        Returns:
            Number of lines used (1-3 depending on content and collapsed state)
        """

        if remaining <= 0:
            return 0

        def _safe_addstr(target_row: int, text: str, attr: int) -> None:
            line = text[:width].ljust(width)
            try:
                stdscr.addstr(target_row, 0, line, attr)  # type: ignore[attr-defined]
            except curses.error as e:
                logger.warning("curses error rendering session line at row %d: %s", target_row, e)

        def _safe_addstr_with_italic_suffix(
            target_row: int,
            prefix_text: str,
            suffix_text: str,
            *,
            prefix_attr: int,
            suffix_attr: int,
        ) -> None:
            """Render one line where only suffix_text is italicized."""
            combined = f"{prefix_text}{suffix_text}"
            line = combined[:width].ljust(width)
            try:
                stdscr.addstr(target_row, 0, line, prefix_attr)  # type: ignore[attr-defined]
                prefix_len = min(len(prefix_text), width)
                available_for_suffix = max(0, width - prefix_len)
                suffix_visible = suffix_text[:available_for_suffix]
                if suffix_visible:
                    stdscr.addstr(target_row, prefix_len, suffix_visible, suffix_attr)  # type: ignore[attr-defined]
            except curses.error as e:
                logger.warning("curses error rendering session line at row %d: %s", target_row, e)

        session_display = item.data
        session = session_display.session
        session_id = session.session_id
        is_collapsed = session_id in self.collapsed_sessions

        agent = session.active_agent or "?"
        mode = session.thinking_mode or "?"
        title = session.title
        idx = session_display.display_index

        # Child indentation: 2 spaces per nesting level
        # Parent (depth 2) = 0, Child (depth 3) = 2, Grandchild (depth 4) = 4
        child_indent = " " * (max(0, item.depth - 2) * 2)

        # Check if this session is sticky
        is_sticky = any(s.session_id == session_id for s in self.sticky_sessions)
        sticky_position = None
        if is_sticky:
            for i, s in enumerate(self.sticky_sessions):
                if s.session_id == session_id:
                    sticky_position = i + 1
                    break

        # Get agent color pairs (muted, normal, highlight)
        agent_colors = AGENT_COLORS.get(agent, {"muted": 0, "normal": 0, "highlight": 0})
        muted_pair = agent_colors.get("muted", 0)
        normal_pair = agent_colors.get("normal", 0)
        highlight_pair = agent_colors.get("highlight", 0)
        muted_attr = curses.color_pair(muted_pair) if muted_pair else curses.A_DIM
        normal_attr = curses.color_pair(normal_pair) if normal_pair else 0
        highlight_attr = curses.color_pair(highlight_pair) if highlight_pair else curses.A_BOLD

        status_raw = session.status or ""
        status_normalized = status_raw.strip().lower()
        is_headless = status_normalized.startswith("headless") or not session.tmux_session_name
        header_attr = muted_attr if is_headless else normal_attr

        is_previewed = bool(self._preview and self._preview.session_id == session_id)
        preview_title_attr = highlight_attr if is_previewed else header_attr
        preview_bold_attr = curses.A_BOLD if is_previewed and not is_headless else 0
        if is_previewed:
            preview_title_attr |= preview_bold_attr
            preview_title_attr |= get_agent_preview_selected_bg_attr(agent)

        # Sticky sessions get highlighted [N] indicator
        if is_sticky and sticky_position is not None:
            idx_text = f"[{sticky_position}]"
            idx_attr = curses.A_REVERSE | curses.A_BOLD
        else:
            idx_text = f"[{idx}]"
            idx_attr = preview_title_attr

        if selected and is_headless:
            selected_focus_attr = curses.A_REVERSE | preview_title_attr
        elif selected and is_previewed:
            selected_focus_attr = get_agent_preview_selected_focus_attr(agent) | preview_bold_attr
        elif selected:
            selected_focus_attr = get_agent_preview_selected_focus_attr(agent) | curses.A_BOLD
        else:
            selected_focus_attr = preview_title_attr

        selected_header_attr = selected_focus_attr if selected else preview_title_attr
        title_attr = selected_header_attr if selected else preview_title_attr

        # Collapse indicator
        collapse_indicator = "▶" if is_collapsed else "▼"

        # Line 1: [idx] ▶/▼ agent/mode  [subdir]  "title"
        # Render child indent + [idx] with special attr if sticky, then rest with title_attr
        # Subdir (if present) uses normal fg to stand out from agent-colored text
        try:
            col = 0
            # Render child indent first
            if child_indent:
                stdscr.addstr(row, col, child_indent, header_attr)  # type: ignore[attr-defined]
                col += len(child_indent)
            selected_idx_attr = selected_header_attr
            stdscr.addstr(row, col, idx_text, idx_attr if not selected else selected_idx_attr)  # type: ignore[attr-defined]
            col += len(idx_text)
            agent_part = f" {collapse_indicator} {agent}/{mode}"
            stdscr.addstr(row, col, agent_part[: width - col], title_attr)  # type: ignore[attr-defined]
            col += len(agent_part)
            if session.subdir and col < width:
                subdir_display = session.subdir.removeprefix("trees/")
                subdir_text = f" {subdir_display} "
                subdir_attr = selected_header_attr if selected else (preview_title_attr if is_previewed else 0)
                stdscr.addstr(row, col, subdir_text[: width - col], subdir_attr)  # type: ignore[attr-defined]
                col += len(subdir_text)
                title_text = f'"{title}" '
            else:
                title_text = f'  "{title}" '
            if col < width:
                stdscr.addstr(row, col, title_text[: width - col], title_attr)  # type: ignore[attr-defined]
        except curses.error:
            pass  # Ignore if line doesn't fit

        # If collapsed, only show title line
        if is_collapsed:
            return 1

        lines_used = 1
        if lines_used >= remaining:
            return lines_used

        # Detail lines: child indentation + 4 spaces (expansion offset)
        detail_indent = child_indent + "    "

        # Line 2 (expanded only): ID + last activity time
        activity_time = _format_time(session.last_activity)
        native_session_id = session.native_session_id or "-"
        line2 = f"{detail_indent}[{activity_time}] {session_id} / {native_session_id}"
        _safe_addstr(row + lines_used, line2, header_attr)
        lines_used += 1
        if lines_used >= remaining:
            return lines_used

        # Determine which field is "active" (highlight) based on centralized state
        has_input_highlight = session_id in self.state.sessions.input_highlights
        has_temp_output_highlight = session_id in self.state.sessions.temp_output_highlights
        has_output_highlight = session_id in self.state.sessions.output_highlights or has_temp_output_highlight
        input_attr = highlight_attr if has_input_highlight else normal_attr
        output_attr = highlight_attr if has_output_highlight else normal_attr

        # Line 3: Last input (only if content exists)
        last_input = (session.last_input or "").strip()
        last_input_at = session.last_input_at
        if last_input:
            input_text = last_input.replace("\n", " ")[:60]
            input_time = _format_time(last_input_at)
            line3 = f"{detail_indent}[{input_time}] in: {input_text}"
            _safe_addstr(row + lines_used, line3, input_attr)
            lines_used += 1
            if lines_used >= remaining:
                return lines_used

        # Line 4: Last output — driven by activity events, not session record
        last_output = self.state.sessions.last_summary.get(session_id, "")
        activity_time = _format_time(session.last_activity)
        if has_temp_output_highlight:
            italic_attr = getattr(curses, "A_ITALIC", 0)
            prefix_text = f"{detail_indent}[{activity_time}] out: "
            tool_preview = self.state.sessions.active_tool.get(session_id)
            placeholder_text = _temp_output_placeholder_text(session.active_agent, tool_preview)
            if italic_attr:
                _safe_addstr_with_italic_suffix(
                    row + lines_used,
                    prefix_text,
                    placeholder_text,
                    prefix_attr=output_attr,
                    suffix_attr=output_attr | italic_attr,
                )
            else:
                _safe_addstr(row + lines_used, f"{prefix_text}{placeholder_text}", output_attr)
            lines_used += 1
        elif has_input_highlight:
            italic_attr = getattr(curses, "A_ITALIC", 0)
            prefix_text = f"{detail_indent}[{activity_time}] out: "
            placeholder_text = _working_placeholder_text()
            if italic_attr:
                _safe_addstr_with_italic_suffix(
                    row + lines_used,
                    prefix_text,
                    placeholder_text,
                    prefix_attr=output_attr,
                    suffix_attr=output_attr | italic_attr,
                )
            else:
                _safe_addstr(row + lines_used, f"{prefix_text}{placeholder_text}", output_attr)
            lines_used += 1
        elif last_output:
            output_text = last_output.replace("\n", " ")[:60]
            line4 = f"{detail_indent}[{activity_time}] out: {output_text}"
            _safe_addstr(row + lines_used, line4, output_attr)
            lines_used += 1

        return lines_used
