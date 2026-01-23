"""Sessions view - shows running AI sessions."""

from __future__ import annotations

import asyncio
import curses
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
from teleclaude.cli.models import (
    ComputerInfo as ApiComputerInfo,
)
from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager
from teleclaude.cli.tui.session_launcher import attach_tmux_from_result
from teleclaude.cli.tui.theme import AGENT_COLORS
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
from teleclaude.cli.tui.types import (
    ActivePane,
    CursesWindow,
    FocusLevelType,
    NodeType,
    StickySessionInfo,
)
from teleclaude.cli.tui.views.base import BaseView, ScrollableViewMixin
from teleclaude.cli.tui.widgets.modal import ConfirmModal, StartSessionModal

if TYPE_CHECKING:
    from teleclaude.cli.api_client import TelecAPIClient
    from teleclaude.cli.tui.app import FocusContext

logger = get_logger(__name__)


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


class SessionsView(ScrollableViewMixin[TreeNode], BaseView):
    """View 1: Sessions - project-centric tree with AI-to-AI nesting."""

    def __init__(
        self,
        api: "TelecAPIClient",
        agent_availability: dict[str, AgentAvailabilityInfo],
        focus: FocusContext,
        pane_manager: TmuxPaneManager,
        notify: Callable[[str, str], None] | None = None,
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
        self.notify = notify
        self.tree: list[TreeNode] = []
        self.flat_items: list[TreeNode] = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.collapsed_sessions: set[str] = set()  # Session IDs that are collapsed
        # State tracking for color coding (detect changes between refreshes)
        self._prev_state: dict[str, dict[str, str]] = {}  # session_id -> {input, output}
        self._active_field: dict[str, ActivePane] = {}
        # Track running highlight timers (for 60-second auto-dim)
        self._highlight_timers: dict[str, asyncio.Task[None]] = {}  # session_id -> timer task
        # Store sessions for child lookup
        self._sessions: list[SessionInfo] = []
        # Store computers for SSH connection lookup
        self._computers: list[ApiComputerInfo] = []
        # Row-to-item mapping for mouse click handling (built during render)
        self._row_to_item: dict[int, int] = {}
        # Row mapping for session ID line clicks (double-click behavior)
        self._row_to_id_item: dict[int, SessionNode] = {}
        self._id_row_clicked: bool = False
        self._missing_last_input_logged: set[str] = set()
        # Signal for app to trigger data refresh
        self.needs_refresh: bool = False
        # Visible height for scroll calculations (updated during render)
        self._visible_height: int = 20  # Default, updated in render
        # Track rendered item range for scroll calculations
        self._last_rendered_range: tuple[int, int] = (0, 0)
        # Sticky session state (max 5 sessions across 3 lanes)
        self.sticky_sessions: list[StickySessionInfo] = []
        self._active_session_id: str | None = None
        self._active_child_session_id: str | None = None
        self._last_click_time: dict[int, float] = {}  # screen_row -> timestamp
        self._double_click_threshold = 0.4  # seconds
        self._selection_method: str = "arrow"  # "arrow" | "click"
        self._pending_select_session_id: str | None = None

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

        # Store sessions for child lookup
        self._sessions = sessions
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
        self._apply_pending_selection()

    def request_select_session(self, session_id: str) -> bool:
        """Request that a session be selected once it appears in the tree."""
        if not session_id:
            return False
        if self._pending_select_session_id == session_id:
            return False
        self._pending_select_session_id = session_id
        return True

    def _apply_pending_selection(self) -> None:
        """Select any pending session once the tree is available."""
        target = self._pending_select_session_id
        if not target:
            return

        for idx, item in enumerate(self.flat_items):
            if is_session_node(item) and item.data.session.session_id == target:
                self.selected_index = idx
                self._selection_method = "click"
                if self.selected_index < self.scroll_offset:
                    self.scroll_offset = self.selected_index
                else:
                    _, last_rendered = self._last_rendered_range
                    if self.selected_index > last_rendered:
                        self.scroll_offset += self.selected_index - last_rendered
                self._pending_select_session_id = None
                logger.debug("Selected new session %s at index %d", target[:8], idx)
                return

    async def _clear_highlight_after_delay(self, session_id: str) -> None:
        """Clear highlight after 60 seconds if no new changes occurred.

        Args:
            session_id: Session ID to clear highlight for
        """
        await asyncio.sleep(60)
        # Timer completed - remove highlight
        self._active_field[session_id] = ActivePane.NONE
        # Clean up timer reference
        self._highlight_timers.pop(session_id, None)
        logger.debug("Highlight timer expired for session %s", session_id[:8])

    def _start_highlight_timer(self, session_id: str, field: ActivePane) -> None:
        """Start 60-second highlight timer, canceling any existing timer.

        Args:
            session_id: Session ID
            field: Which field to highlight (INPUT or OUTPUT)
        """
        # Cancel existing timer if any
        existing_timer = self._highlight_timers.get(session_id)
        if existing_timer and not existing_timer.done():
            existing_timer.cancel()
            logger.debug("Cancelled existing highlight timer for session %s", session_id[:8])

        # Set highlight
        self._active_field[session_id] = field

        # Start new 60-second timer
        timer = asyncio.create_task(self._clear_highlight_after_delay(session_id))
        self._highlight_timers[session_id] = timer
        logger.debug("Started highlight timer for session %s (%s)", session_id[:8], field.name)

    def _update_activity_state(self, sessions: list[SessionInfo]) -> None:
        """Update activity state tracking for color coding.

        Event-based highlighting: when input/output changes, start 60-second timer.
        When timer completes (no new changes), remove highlight.

        Args:
            sessions: List of session dicts
        """
        now = datetime.now(timezone.utc)

        def _is_recent(last_activity: str | None) -> bool:
            if not last_activity:
                return False
            try:
                last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
            except ValueError:
                return False
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            return (now - last_dt).total_seconds() <= 60

        for session in sessions:
            session_id = session.session_id
            curr_input = session.last_input or ""
            curr_output = session.last_output or ""

            # Get previous state
            prev = self._prev_state.get(session_id)
            if prev is None:
                # New session - store state and check if there's activity
                self._prev_state[session_id] = {"input": curr_input, "output": curr_output}
                # If there's recent activity, highlight it
                if _is_recent(session.last_activity):
                    if curr_input:
                        self._start_highlight_timer(session_id, ActivePane.INPUT)
                    elif curr_output:
                        self._start_highlight_timer(session_id, ActivePane.OUTPUT)
                else:
                    self._active_field[session_id] = ActivePane.NONE
                continue

            # Existing session - check what changed
            prev_input = prev.get("input", "")
            prev_output = prev.get("output", "")

            input_changed = curr_input != prev_input
            output_changed = curr_output != prev_output

            if output_changed:
                # New output → highlight output, start timer
                self._start_highlight_timer(session_id, ActivePane.OUTPUT)
            elif input_changed:
                # New input → highlight input, start timer
                self._start_highlight_timer(session_id, ActivePane.INPUT)

            # Store current state for next comparison
            self._prev_state[session_id] = {"input": curr_input, "output": curr_output}

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

        return walk(self.tree)

    def sync_layout(self) -> None:
        """Sync pane layout with current session list."""
        session_ids = {session.session_id for session in self._sessions}
        if self._active_session_id and self._active_session_id not in session_ids:
            self._active_session_id = None
            self._active_child_session_id = None
        if self._active_child_session_id and self._active_child_session_id not in session_ids:
            self._active_child_session_id = None

        if self.sticky_sessions:
            self.sticky_sessions = [s for s in self.sticky_sessions if s.session_id in session_ids]

        self.pane_manager.apply_layout(
            active_session_id=self._active_session_id,
            sticky_session_ids=[s.session_id for s in self.sticky_sessions],
            child_session_id=self._active_child_session_id,
            get_computer_info=self._get_computer_info,
            focus=False,
        )

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

        # Reset selection if out of bounds
        if self.selected_index >= len(self.flat_items):
            self.selected_index = max(0, len(self.flat_items) - 1)
        self.scroll_offset = 0

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
            tmux_session = selected.data.session.tmux_session_name or ""
            is_previewing = self.pane_manager.active_session == tmux_session
            preview_action = "[Enter] Hide Preview" if is_previewing else "[Enter] Preview"
            return f"{back_hint}{preview_action}  [←/→] Collapse/Expand  [R] Restart  [k] Kill"
        if is_project_node(selected):
            return f"{back_hint}[n] New Session  [a] Open Sessions"
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
        self._selection_method = "arrow"

    def move_down(self) -> None:
        """Move selection down (arrow key navigation)."""
        super().move_down()
        self._selection_method = "arrow"

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
            self.selected_index = 0
            logger.debug("drill_down: pushed computer focus")
            return True
        if is_session_node(item):
            # Expand this session (if not already expanded)
            session_id = item.data.session.session_id
            if session_id in self.collapsed_sessions:
                self.collapsed_sessions.discard(session_id)
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
                self.collapsed_sessions.add(session_id)
                logger.debug("collapse_selected: collapsed session %s", session_id[:8])
                return True
            logger.debug("collapse_selected: session already collapsed")
            return False  # Already collapsed - let navigation take over
        logger.debug("collapse_selected: not a session, returning False")
        return False

    def expand_all(self) -> None:
        """Expand all sessions (show input/output)."""
        logger.debug("expand_all: clearing collapsed_sessions (was %d)", len(self.collapsed_sessions))
        self.collapsed_sessions.clear()

    def collapse_all(self) -> None:
        """Collapse all sessions (hide input/output)."""
        logger.debug("collapse_all: collecting all session IDs")
        self._collect_all_session_ids(self.tree)
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
            self._activate_session(item)
            logger.trace(
                "sessions_enter",
                item_type="session",
                action="activate",
                duration_ms=int((time.perf_counter() - enter_start) * 1000),
            )
            self._id_row_clicked = False

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

    def _toggle_sticky(self, session_id: str, show_child: bool) -> None:
        """Toggle sticky state for a session (max 5 sessions).

        Args:
            session_id: Session ID to toggle
            show_child: Whether to show child session (False for parent-only mode)
        """
        # Find existing sticky entry (check session_id only, ignore show_child)
        existing_idx = None
        for i, sticky in enumerate(self.sticky_sessions):
            if sticky.session_id == session_id:
                existing_idx = i
                break

        if existing_idx is not None:
            # Remove from sticky
            removed = self.sticky_sessions.pop(existing_idx)
            logger.info(
                "REMOVED STICKY: %s (was show_child=%s, now count=%d, remaining=%s)",
                session_id[:8],
                removed.show_child,
                len(self.sticky_sessions),
                [s.session_id[:8] for s in self.sticky_sessions],
            )
        elif len(self.sticky_sessions) < 5:
            # Double-check: no duplicates allowed (defensive)
            if any(s.session_id == session_id for s in self.sticky_sessions):
                logger.error("BUG: Attempted to add duplicate session_id %s to sticky list", session_id[:8])
                return

            # Add to sticky with child preference
            self.sticky_sessions.append(StickySessionInfo(session_id, show_child))
            logger.info(
                "Added sticky: %s (show_child=%s, total=%d)",
                session_id[:8],
                show_child,
                len(self.sticky_sessions),
            )
        else:
            # Max 5 reached
            if self.notify:
                self.notify("warning", "Maximum 5 sticky sessions")
            logger.warning("Cannot add sticky session %s: maximum 5 reached", session_id[:8])
            return

        # Rebuild panes with new sticky set
        self._rebuild_sticky_panes()

    def _activate_session(self, item: SessionNode) -> None:
        """Activate a single session (single-click or Enter from arrows).

        Shows the session in preview mode without affecting sticky panes.
        If session is already sticky, hides the active pane entirely.

        Args:
            item: Session node to activate
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
            logger.warning("_activate_session: tmux_session_name missing, cannot activate")
            return

        # If session is already sticky, hide active pane (no duplication)
        is_already_sticky = any(sticky.session_id == session_id for sticky in self.sticky_sessions)
        if is_already_sticky:
            logger.info(
                "_activate_session: session %s ALREADY STICKY, hiding active pane",
                session_id[:8],
            )
            self._active_session_id = None
            self._active_child_session_id = None
            self.pane_manager.apply_layout(
                active_session_id=None,
                sticky_session_ids=[s.session_id for s in self.sticky_sessions],
                child_session_id=None,
                get_computer_info=self._get_computer_info,
            )
            return

        # Find child session if exists
        child_session_id: str | None = None
        for sess in self._sessions:
            if sess.initiator_session_id == session_id:
                child_session_id = sess.session_id
                break

        self._active_session_id = session_id
        self._active_child_session_id = child_session_id

        # Apply deterministic layout
        self.pane_manager.apply_layout(
            active_session_id=self._active_session_id,
            sticky_session_ids=[s.session_id for s in self.sticky_sessions],
            child_session_id=self._active_child_session_id,
            get_computer_info=self._get_computer_info,
            focus=False,
        )
        logger.debug(
            "_activate_session: showing session in active pane (sticky_count=%d)",
            len(self.sticky_sessions),
        )

    def _rebuild_sticky_panes(self) -> None:
        """Rebuild pane layout based on sticky sessions."""
        if not self.sticky_sessions:
            # No sticky sessions - clear all panes
            self.pane_manager.apply_layout(
                active_session_id=self._active_session_id,
                sticky_session_ids=[],
                child_session_id=self._active_child_session_id,
                get_computer_info=self._get_computer_info,
                focus=False,
            )
            logger.debug("_rebuild_sticky_panes: no sticky sessions, hiding all panes")
            return

        # Gather SessionInfo objects for sticky sessions
        sticky_session_infos: list[tuple[SessionInfo, bool]] = []
        for sticky in self.sticky_sessions:
            for sess in self._sessions:
                if sess.session_id == sticky.session_id:
                    sticky_session_infos.append((sess, sticky.show_child))
                    break

        if not sticky_session_infos:
            logger.warning("_rebuild_sticky_panes: no matching sessions found for sticky IDs")
            return

        logger.info(
            "_rebuild_sticky_panes: showing %d sticky sessions across 3 lanes",
            len(sticky_session_infos),
        )

        # Apply deterministic layout
        self.pane_manager.apply_layout(
            active_session_id=self._active_session_id,
            sticky_session_ids=[s.session_id for s in self.sticky_sessions],
            child_session_id=self._active_child_session_id,
            get_computer_info=self._get_computer_info,
            focus=False,
        )

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
            logger.warning("_toggle_session_pane: tmux_session_name missing, cannot toggle")
            return

        # Get computer info for SSH (if remote)
        computer_info = self._get_computer_info(computer_name)
        logger.debug(
            "_toggle_session_pane: computer_info=%s (is_remote=%s)",
            computer_info.name if computer_info else "None",
            computer_info.is_remote if computer_info else "N/A",
        )

        # Look for child sessions (sessions where initiator_session_id == this session's id)
        child_tmux_session: str | None = None
        for sess in self._sessions:
            if sess.initiator_session_id == session_id:
                child_tmux = sess.tmux_session_name
                if child_tmux:
                    child_tmux_session = child_tmux
                    break

        # Toggle pane visibility (handles both local and remote via SSH)
        self.pane_manager.toggle_session(tmux_session, agent, child_tmux_session, computer_info)

    def _show_single_session_pane(self, item: SessionNode) -> None:
        """Show only the selected session in the side pane (no child split)."""
        session = item.data.session
        tmux_session = session.tmux_session_name or ""
        computer_name = session.computer or "local"
        agent = session.active_agent

        if not tmux_session:
            logger.warning("_show_single_session_pane: tmux_session_name missing, cannot show")
            return

        computer_info = self._get_computer_info(computer_name)
        self.pane_manager.show_session(tmux_session, agent, None, computer_info)

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
        agent = result.agent
        if not tmux_session_name:
            logger.warning("New session missing tmux_session_name, cannot attach")
            return
        if result.session_id:
            self.request_select_session(result.session_id)
            self._apply_pending_selection()

        if self.pane_manager.is_available:
            computer_info = self._get_computer_info(computer)
            self.pane_manager.show_session(tmux_session_name, agent, None, computer_info)
        else:
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
        """Make all sessions for a project sticky and attach them in panes."""
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
                self.notify("info", "No sessions found for project")
            logger.debug("_open_project_sessions: no matching sessions for %s", project.path)
            return

        tmux_sessions = [session for session in project_sessions if session.tmux_session_name]
        if not tmux_sessions:
            if self.notify:
                self.notify("info", "No attachable sessions found for project")
            logger.debug("_open_project_sessions: no tmux sessions for %s", project.path)
            return

        max_sticky = 5
        if len(tmux_sessions) > max_sticky and self.notify:
            self.notify("warning", f"Showing first {max_sticky} sessions (max 5 sticky panes)")

        self.sticky_sessions = [StickySessionInfo(session.session_id, True) for session in tmux_sessions[:max_sticky]]
        self._active_session_id = None
        self._active_child_session_id = None
        self._rebuild_sticky_panes()

        for sticky in self.sticky_sessions:
            self.pane_manager.focus_pane_for_session(sticky.session_id)

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
            self._id_row_clicked = False
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
            clicked_id_line = screen_row in self._row_to_id_item

            # DOUBLE CLICK - toggle sticky
            if clicked_id_line:
                # ID line → parent only, no child
                self._toggle_sticky(session_id, show_child=False)
                logger.debug("Double-click on ID line: toggled sticky (parent-only) for %s", session_id[:8])
            else:
                # Title/other line → parent + child
                self._toggle_sticky(session_id, show_child=True)
                logger.debug("Double-click on title: toggled sticky (parent+child) for %s", session_id[:8])

            logger.trace(
                "sessions_double_click",
                row=screen_row,
                session_id=session_id[:8],
                id_line=clicked_id_line,
                duration_ms=int((time.perf_counter() - click_start) * 1000),
            )
            # Select the item but don't activate (sticky toggle is the action)
            self.selected_index = item_idx
            self._selection_method = "click"
            self._focus_selected_pane()  # Focus the sticky pane
            return True

        # SINGLE CLICK - select and activate
        self.selected_index = item_idx
        self._selection_method = "click"
        self._id_row_clicked = screen_row in self._row_to_id_item

        # Activate session immediately on single click
        if is_session_node(item):
            self._activate_session(item)
            self._focus_selected_pane()  # Focus the pane (sticky or active)

        logger.trace(
            "sessions_click",
            row=screen_row,
            item_type=item.type,
            id_row=self._id_row_clicked,
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
            path = item.data.path
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

        # Collapse indicator
        collapse_indicator = "▶" if is_collapsed else "▼"

        # Line 1: [idx] ▶/▼ agent/mode "title"
        lines: list[str] = []
        line1 = f'[{idx}] {collapse_indicator} {agent}/{mode}  "{title}"'
        lines.append(line1[:width])

        # If collapsed, only show title line
        if is_collapsed:
            return lines

        # Detail lines use 3-space indent
        content_indent = "   "

        # Line 2 (expanded only): ID + last activity time
        activity_time = _format_time(session.last_activity)
        line2 = f"{content_indent}[{activity_time}] ID: {session_id}"
        lines.append(line2[:width])

        # Line 3: Last input (only if content exists)
        last_input = (session.last_input or "").strip()
        last_input_at = session.last_input_at
        if last_input:
            input_text = last_input.replace("\n", " ")[:60]
            input_time = _format_time(last_input_at)
            line3 = f"{content_indent}[{input_time}] in: {input_text}"
            lines.append(line3[:width])

        # Line 4: Last output (only if content exists)
        last_output = (session.last_output or "").strip()
        last_output_at = session.last_output_at
        if last_output:
            output_text = last_output.replace("\n", " ")[:60]
            output_time = _format_time(last_output_at)
            line4 = f"{content_indent}[{output_time}] out: {output_text}"
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

        logger.debug(
            "SessionsView.render: start_row=%d, height=%d, width=%d, flat_items=%d, scroll=%d",
            start_row,
            height,
            width,
            len(self.flat_items),
            self.scroll_offset,
        )

        # Clear row-to-item mapping (rebuilt each render)
        self._row_to_item.clear()
        self._row_to_id_item.clear()

        if not self.flat_items:
            msg = "(no items)"
            logger.debug("render: no items to display")
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
                logger.debug("render: stopped at row %d (out of space), rendered %d items", row, items_rendered)
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

        logger.debug(
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
            path = item.data.path
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

        session_display = item.data
        session = session_display.session
        session_id = session.session_id
        is_collapsed = session_id in self.collapsed_sessions

        agent = session.active_agent or "?"
        mode = session.thinking_mode or "?"
        title = session.title
        idx = session_display.display_index

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

        # Sticky sessions get highlighted [N] indicator
        if is_sticky and sticky_position is not None:
            idx_text = f"[{sticky_position}]"
            idx_attr = curses.A_REVERSE | curses.A_BOLD
        else:
            idx_text = f"[{idx}]"
            idx_attr = normal_attr

        # Title line uses normal color (the original agent color)
        title_attr = curses.A_REVERSE if selected else normal_attr

        # Collapse indicator
        collapse_indicator = "▶" if is_collapsed else "▼"

        # Line 1: [idx] ▶/▼ agent/mode "title"
        # Render [idx] with special attr if sticky, then rest with title_attr
        try:
            col = 0
            stdscr.addstr(row, col, idx_text, idx_attr if not selected else curses.A_REVERSE)  # type: ignore[attr-defined]
            col += len(idx_text)
            rest = f' {collapse_indicator} {agent}/{mode}  "{title}"'
            stdscr.addstr(row, col, rest[: width - col], title_attr)  # type: ignore[attr-defined]
        except curses.error:
            pass  # Ignore if line doesn't fit

        # If collapsed, only show title line
        if is_collapsed:
            return 1

        lines_used = 1
        if lines_used >= remaining:
            return lines_used

        # Detail lines use 3-space indent
        content_indent = "   "

        # Line 2 (expanded only): ID + last activity time
        activity_time = _format_time(session.last_activity)
        line2 = f"{content_indent}[{activity_time}] ID: {session_id}"
        _safe_addstr(row + lines_used, line2, normal_attr)
        self._row_to_id_item[row + lines_used] = item
        lines_used += 1
        if lines_used >= remaining:
            return lines_used

        # Determine which field is "active" (highlight) based on state tracking
        active = self._active_field.get(session_id, ActivePane.NONE)
        input_attr = highlight_attr if active is ActivePane.INPUT else muted_attr
        output_attr = highlight_attr if active is ActivePane.OUTPUT else muted_attr

        # Line 3: Last input (only if content exists)
        last_input = (session.last_input or "").strip()
        last_input_at = session.last_input_at
        if last_input:
            input_text = last_input.replace("\n", " ")[:60]
            input_time = _format_time(last_input_at)
            line3 = f"{content_indent}[{input_time}] in: {input_text}"
            _safe_addstr(row + lines_used, line3, input_attr)
            lines_used += 1
            if lines_used >= remaining:
                return lines_used

        # Line 4: Last output (only if content exists)
        last_output = (session.last_output or "").strip()
        last_output_at = session.last_output_at
        if last_output and not last_input and session_id not in self._missing_last_input_logged:
            self._missing_last_input_logged.add(session_id)
            logger.trace("missing_last_input", session=session_id[:8])
        if last_output:
            output_text = last_output.replace("\n", " ")[:60]
            output_time = _format_time(last_output_at)
            line4 = f"{content_indent}[{output_time}] out: {output_text}"
            _safe_addstr(row + lines_used, line4, output_attr)
            lines_used += 1

        return lines_used
