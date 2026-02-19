"""Main TUI application with view switching.

Required reads:
- @docs/project/design/tui-state-layout.md
"""

import asyncio
import curses
import os
import queue
import random
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from instrukt_ai_logging import get_logger

from teleclaude.cli.models import (
    AgentActivityEvent,
    AgentAvailabilityInfo,
    ErrorEvent,
    ProjectInfo,
    ProjectsInitialEvent,
    ProjectWithTodosInfo,
    SessionClosedEvent,
    SessionInfo,
    SessionsInitialEvent,
    SessionStartedEvent,
    SessionUpdatedEvent,
    SettingsPatchInfo,
    TodoInfo,
    TTSSettingsPatchInfo,
    WsEvent,
)
from teleclaude.cli.models import (
    ComputerInfo as ApiComputerInfo,
)
from teleclaude.cli.tui.animation_colors import palette_registry
from teleclaude.cli.tui.animation_engine import AnimationEngine, AnimationPriority
from teleclaude.cli.tui.animation_triggers import ActivityTrigger, PeriodicTrigger, StateDrivenTrigger
from teleclaude.cli.tui.animations.config import (
    ErrorAnimation,
    PulseAnimation,
    SuccessAnimation,
    TypingAnimation,
)
from teleclaude.cli.tui.controller import TuiController
from teleclaude.cli.tui.pane_manager import ComputerInfo, TmuxPaneManager
from teleclaude.cli.tui.state import Intent, IntentType, TuiState
from teleclaude.cli.tui.state_store import save_sticky_state
from teleclaude.cli.tui.theme import (
    PANE_THEMING_MODE_CYCLE,
    get_current_mode,
    get_pane_theming_mode,
    get_pane_theming_mode_level,
    get_system_dark_mode,
    get_tab_line_attr,
    init_colors,
    is_dark_mode,
    normalize_pane_theming_mode,
    set_pane_theming_mode,
)
from teleclaude.cli.tui.tree import is_computer_node, is_session_node
from teleclaude.cli.tui.types import CursesWindow, FocusLevelType, NotificationLevel
from teleclaude.cli.tui.views.configuration import ConfigurationView
from teleclaude.cli.tui.views.jobs import JobsView
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.banner import BANNER_HEIGHT, render_banner
from teleclaude.cli.tui.widgets.footer import Footer
from teleclaude.cli.tui.widgets.tab_bar import TabBar
from teleclaude.config import config
from teleclaude.constants import LOCAL_COMPUTER

logger = get_logger(__name__)

# WebSocket update polling interval in milliseconds
WS_POLL_INTERVAL_MS = 100
WS_HEAL_REFRESH_S = 5.0
API_DISCONNECT_GRACE_S = 15.0
THEME_MODE_PROBE_S = 1.0

# Mouse mask for curses - clicks, double-clicks, scroll wheel (NOT drag to allow text selection)
MOUSE_MASK = (
    curses.BUTTON1_CLICKED
    | curses.BUTTON1_DOUBLE_CLICKED
    | curses.BUTTON4_PRESSED
    | 0x8000000
    | 0x200000  # Scroll down (varies by system)
)

# Key name mapping for debug logging
KEY_NAMES = {
    curses.KEY_UP: "KEY_UP",
    curses.KEY_DOWN: "KEY_DOWN",
    curses.KEY_LEFT: "KEY_LEFT",
    curses.KEY_RIGHT: "KEY_RIGHT",
    curses.KEY_ENTER: "KEY_ENTER",
    curses.KEY_MOUSE: "KEY_MOUSE",
    10: "ENTER(10)",
    13: "ENTER(13)",
    27: "ESCAPE",
}


# Notification durations in seconds
NOTIFICATION_DURATION_INFO = 3.0
NOTIFICATION_DURATION_ERROR = 5.0


def _key_name(key: int) -> str:
    """Get human-readable key name for logging."""
    if key in KEY_NAMES:
        return KEY_NAMES[key]
    if 32 <= key < 127:
        return f"'{chr(key)}'({key})"
    return f"KEY({key})"


@dataclass
class FocusLevel:
    """A single level in the focus stack."""

    type: FocusLevelType
    name: str  # Computer name or project path


@dataclass
class FocusContext:
    """Shared focus context across views."""

    stack: list[FocusLevel] = field(default_factory=list)

    def push(self, level_type: FocusLevelType, name: str) -> None:
        """Push a new focus level."""
        self.stack.append(FocusLevel(type=level_type, name=name))

    def pop(self) -> bool:
        """Pop the last focus level. Returns True if popped, False if empty."""
        if self.stack:
            self.stack.pop()
            return True
        return False

    def clear(self) -> None:
        """Clear the focus stack."""
        self.stack.clear()

    @property
    def computer(self) -> str | None:
        """Get focused computer name, if any."""
        for level in self.stack:
            if level.type is FocusLevelType.COMPUTER:
                return level.name
        return None

    @property
    def project(self) -> str | None:
        """Get focused project path, if any."""
        for level in self.stack:
            if level.type is FocusLevelType.PROJECT:
                return level.name
        return None

    def get_breadcrumb(self) -> str:
        """Get breadcrumb string."""
        if not self.stack:
            return ""
        parts: list[str] = []
        for level in self.stack:
            if level.type is FocusLevelType.COMPUTER:
                parts.append(level.name)
            elif level.type is FocusLevelType.PROJECT:
                # Show just the last directory name
                parts.append(level.name.split("/")[-1] or level.name)
        return " > ".join(parts)


@dataclass
class NotificationLine:
    """A single line in a notification with its own level."""

    text: str
    level: NotificationLevel


@dataclass
class Notification:
    """A temporary notification message (supports multi-line)."""

    lines: list[NotificationLine]
    expires_at: float  # timestamp when it should disappear

    @property
    def level(self) -> NotificationLevel:
        """Return highest severity level among lines."""
        if any(line.level is NotificationLevel.ERROR for line in self.lines):
            return NotificationLevel.ERROR
        if any(line.level is NotificationLevel.WARNING for line in self.lines):
            return NotificationLevel.WARNING
        if any(line.level is NotificationLevel.SUCCESS for line in self.lines):
            return NotificationLevel.SUCCESS
        return NotificationLevel.INFO


class TelecApp:
    """Main TUI application with view switching (1=Sessions, 2=Preparation, 3=Jobs, 4=Configuration)."""

    def __init__(self, api: "TelecAPIClient", start_view: int = 1, config_guided: bool = False):
        """Initialize TUI app.

        Args:
            api: API client instance
            start_view: Initial view to show (default 1)
            config_guided: Whether to start configuration in guided mode
        """
        self.api = api
        self.current_view = start_view
        self.views: dict[int, SessionsView | PreparationView | ConfigurationView | JobsView] = {}
        self.tab_bar = TabBar()
        # Set initial active tab
        self.tab_bar.set_active(start_view)

        self.footer: Footer | None = None
        self.running = True
        self.agent_availability: dict[str, AgentAvailabilityInfo] = {}
        self.tts_enabled: bool = False
        self.pane_theming_mode: str = get_pane_theming_mode()
        self._pane_mode_pending_patch: bool = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self.focus = FocusContext()  # Shared focus across views
        self.notification: Notification | None = None
        self.pane_manager = TmuxPaneManager()
        self.state = TuiState()

        # Set initial config state
        if config_guided:
            self.state.config.guided_mode = True

        self._computers: list[ApiComputerInfo] = []
        self.controller = TuiController(self.state, self.pane_manager, self._get_computer_info)
        # Content area bounds for mouse click handling
        self._content_start: int = 0
        self._content_height: int = 0
        # WebSocket event queue (thread-safe)
        self._ws_queue: queue.Queue[WsEvent] = queue.Queue()
        self._subscribed_computers: set[str] = set()
        self._theme_refresh_requested = False
        self._reload_requested = False
        self._session_status_cache: dict[str, str] = {}
        self._last_ws_heal = time.monotonic()
        self._refresh_error_since: float | None = None
        self._refresh_error_notified = False
        self._refresh_error_escalated = False
        self._last_theme_probe = time.monotonic()
        self._loop: asyncio.AbstractEventLoop | None = None

        # Animation system
        self.animation_engine = AnimationEngine()
        self.periodic_trigger = PeriodicTrigger(self.animation_engine, animations_subset=config.ui.animations_subset)
        self.activity_trigger = ActivityTrigger(self.animation_engine, animations_subset=config.ui.animations_subset)
        self.state_driven_trigger = StateDrivenTrigger(self.animation_engine)

        # Register config animations
        sections = [
            "adapters.telegram",
            "adapters.discord",
            "adapters.ai_keys",
            "adapters.whatsapp",
            "people",
            "notifications",
            "environment",
            "validate",
        ]
        for section in sections:
            self.state_driven_trigger.register(section, "idle", PulseAnimation)
            self.state_driven_trigger.register(section, "interacting", TypingAnimation)
            self.state_driven_trigger.register(section, "success", SuccessAnimation)
            self.state_driven_trigger.register(section, "error", ErrorAnimation)

    async def initialize(self) -> None:
        """Load initial data and create views."""
        await self.api.connect()
        self._loop = asyncio.get_event_loop()
        self._loop = asyncio.get_running_loop()

        # Create views BEFORE refresh so they can receive data
        # Pass shared focus context to each view
        self.views[1] = SessionsView(
            self.api,
            self.agent_availability,
            self.focus,
            self.pane_manager,
            self.state,
            self.controller,
            on_agent_output=self._on_agent_output,
            notify=self.notify,
        )
        self.views[2] = PreparationView(
            self.api,
            self.agent_availability,
            self.focus,
            self.pane_manager,
            self.state,
            self.controller,
            notify=self.notify,
        )
        self.views[3] = JobsView(
            self.api,
            notify=self.notify,
        )
        self.views[4] = ConfigurationView(
            self.api,
            self.agent_availability,
            self.focus,
            self.pane_manager,
            self.state,
            self.controller,
            notify=self.notify,
            on_animation_context_change=self.state_driven_trigger.set_context,
        )

        # Start animation triggers (palette initialization deferred to run())
        self._apply_animation_mode()
        self.periodic_trigger.task = asyncio.create_task(self.periodic_trigger.start())

        # Now refresh to populate views with data (always include todos so prep view has data)
        await self.refresh_data()

        # Start WebSocket connection for push updates
        self.api.start_websocket(
            callback=self._on_ws_event,
            subscriptions=["sessions", "projects", "todos"],
        )

    def _apply_pane_theming_mode(self, mode: str, *, from_api: bool = False) -> None:
        """Apply pane mode override and refresh pane colors."""
        try:
            normalized = normalize_pane_theming_mode(mode)
        except ValueError:
            logger.warning("Ignoring unknown pane_theming_mode: %s", mode)
            return

        if normalized == self.pane_theming_mode:
            if from_api:
                self._pane_mode_pending_patch = False
            return

        if from_api and self._pane_mode_pending_patch:
            return

        self.pane_theming_mode = normalized
        set_pane_theming_mode(normalized)
        self.pane_manager.reapply_agent_colors()

        if self.footer:
            self.footer.pane_theming_mode = normalized

    def _cycle_pane_theming_mode(self) -> None:
        """Advance pane theming mode to the next presentation option."""
        cycle = PANE_THEMING_MODE_CYCLE
        index = get_pane_theming_mode_level(self.pane_theming_mode)
        next_mode = cycle[(index + 1) % len(cycle)]
        self._pane_mode_pending_patch = True
        self._apply_pane_theming_mode(next_mode)

        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self.api.patch_settings(SettingsPatchInfo(pane_theming_mode=next_mode)),
                self._loop,
            )

    async def refresh_data(self) -> None:
        """Refresh all data from API."""
        logger.debug("Refreshing data from API...")
        try:
            # Split gather to help type inference
            computers, projects, sessions = await asyncio.gather(
                self.api.list_computers(),
                self.api.list_projects(),
                self.api.list_sessions(),
            )
            availability, todos, settings, jobs = await asyncio.gather(
                self.api.get_agent_availability(),
                self.api.list_todos(),
                self.api.get_settings(),
                self.api.list_jobs(),
            )

            todos_by_project: dict[tuple[str, str], list[TodoInfo]] = {}
            for todo in todos:
                if not todo.computer or not todo.project_path:
                    continue
                key = (todo.computer, todo.project_path)
                todos_by_project.setdefault(key, []).append(todo)

            projects_with_todos: list[ProjectWithTodosInfo] = []
            for project in projects:
                computer = project.computer or ""
                key = (computer, project.path)
                projects_with_todos.append(
                    ProjectWithTodosInfo(
                        computer=project.computer,
                        name=project.name,
                        path=project.path,
                        description=project.description,
                        todos=todos_by_project.get(key, []),
                    )
                )

            total_todos = sum(len(p.todos) for p in projects_with_todos)
            logger.debug(
                "API returned: %d computers, %d projects, %d sessions, %d todos attached",
                len(computers),
                len(projects_with_todos),
                len(sessions),
                total_todos,
            )

            self._computers = computers
            self.pane_manager.update_session_catalog(sessions)
            self.controller.update_sessions(sessions)
            self.controller.dispatch(
                Intent(IntentType.SYNC_SESSIONS, {"session_ids": [s.session_id for s in sessions]})
            )
            # Update in-place so views keep the same shared dict reference.
            self.agent_availability.clear()
            self.agent_availability.update(availability)

            # Update TTS state from settings
            self.tts_enabled = settings.tts.enabled
            self._apply_pane_theming_mode(settings.pane_theming_mode, from_api=True)

            # Refresh ALL views with data (not just current)
            for view_num, view in self.views.items():
                if view_num == 3:
                    if isinstance(view, JobsView):
                        await view.refresh(jobs, sessions)
                else:
                    if not isinstance(view, JobsView):
                        await view.refresh(computers, projects_with_todos, sessions)
                logger.debug(
                    "View %d refreshed: flat_items=%d",
                    view_num,
                    len(view.flat_items),
                )

            # Update footer with new availability and TTS state
            self.footer = Footer(
                self.agent_availability,
                tts_enabled=self.tts_enabled,
                animation_mode=self.state.animation_mode,
                pane_theming_mode=self.pane_theming_mode,
                pane_theming_agent=self._get_footer_pane_theming_agent(),
            )
            logger.debug("Data refresh complete")
            self._refresh_error_since = None
            self._refresh_error_notified = False
            self._refresh_error_escalated = False
        except Exception as e:
            now = time.monotonic()
            if self._refresh_error_since is None:
                self._refresh_error_since = now
                self._refresh_error_notified = False
                self._refresh_error_escalated = False

            elapsed = now - self._refresh_error_since
            if elapsed < API_DISCONNECT_GRACE_S:
                if not self._refresh_error_notified:
                    self.notify(
                        "API temporarily unavailable; retrying...",
                        NotificationLevel.INFO,
                    )
                    self._refresh_error_notified = True
                logger.debug(
                    "Refresh failed within grace window (%.1fs): %s",
                    elapsed,
                    e,
                )
                return

            if not self._refresh_error_escalated:
                logger.error(
                    "Failed to refresh data (after %.1fs): %s",
                    elapsed,
                    e,
                    exc_info=True,
                )
                self.notify(f"Refresh failed: {e}", NotificationLevel.ERROR)
                self._refresh_error_escalated = True
            else:
                logger.debug(
                    "Refresh still failing after grace window (%.1fs): %s",
                    elapsed,
                    e,
                )

    def notify(self, message: str, level: NotificationLevel = NotificationLevel.INFO) -> None:
        """Show a temporary notification.

        Args:
            message: Message to display
            level: Notification level ("info", "error", "success")
        """
        duration = NOTIFICATION_DURATION_ERROR if level is NotificationLevel.ERROR else NOTIFICATION_DURATION_INFO
        self.notification = Notification(
            lines=[NotificationLine(text=message, level=level)],
            expires_at=time.time() + duration,
        )

    def notify_bulk_result(
        self, operation: str, context: str, total: int, successes: int, errors: list["APIError"]
    ) -> None:
        """Central handler for bulk operation results. Shows multi-line toast.

        Args:
            operation: What was done (e.g., "Restarted")
            context: Where (e.g., "on MozBook")
            total: Total attempted
            successes: How many succeeded
            errors: List of APIError for failures
        """
        lines: list[NotificationLine] = []

        # Success line with green checkmark
        if successes > 0:
            count_text = f"{successes}/{total}" if errors else str(successes)
            lines.append(
                NotificationLine(
                    text=f"✔ {operation} {count_text} sessions {context}",
                    level=NotificationLevel.SUCCESS,
                )
            )

        # Error lines with red cross
        for error in errors:
            if error.detail:
                lines.append(
                    NotificationLine(
                        text=f"✘ {error.detail}",
                        level=NotificationLevel.ERROR,
                    )
                )

        if not lines:
            return

        # Use longer duration if there are errors
        has_errors = any(line.level is NotificationLevel.ERROR for line in lines)
        duration = NOTIFICATION_DURATION_ERROR if has_errors else NOTIFICATION_DURATION_INFO
        self.notification = Notification(lines=lines, expires_at=time.time() + duration)

    def _sync_focus_subscriptions(self) -> None:
        """Subscribe/unsubscribe remote computers based on current focus."""
        current = self.focus.computer
        if not current or current == LOCAL_COMPUTER:
            for computer in list(self._subscribed_computers):
                if computer != LOCAL_COMPUTER:
                    self.api.unsubscribe(computer)
                    self._subscribed_computers.discard(computer)
            return

        if current not in self._subscribed_computers:
            self.api.subscribe(current, ["sessions", "projects"])
            self._subscribed_computers.add(current)
            if self._loop:
                self._loop.run_until_complete(self.refresh_data())

    def _get_computer_info(self, computer_name: str) -> ComputerInfo | None:
        """Get SSH connection info for a computer."""
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

    def cleanup(self) -> None:
        """Clean up resources before exit."""
        # Save sticky sessions state before exit
        sessions_view = self.views.get(1)
        if isinstance(sessions_view, SessionsView):
            save_sticky_state(sessions_view.state)

        self.pane_manager.cleanup()
        # Stop WebSocket connection
        self.api.stop_websocket()
        # Cancel periodic animation task
        if self.periodic_trigger.task:
            self.periodic_trigger.task.cancel()

    def _on_ws_event(self, event: WsEvent) -> None:
        """Handle WebSocket event from background thread.

        Queues the event for processing in the main loop (thread-safe).

        Args:
            event: Event type (e.g., "session_updated", "sessions_initial")
            data: Event data
        """
        self._ws_queue.put(event)

    def _process_ws_events(self) -> bool:
        """Process pending WebSocket events from the queue.

        Returns:
            True if any events were processed (view may need re-render)
        """
        updated = False

        while True:
            try:
                event = self._ws_queue.get_nowait()
            except queue.Empty:
                break

            logger.debug("Processing WebSocket event: %s", event.event)
            updated = True

            # Handle initial state events (sent after subscription)
            if isinstance(event, SessionsInitialEvent):
                self._update_sessions_view(event.data.sessions)

            elif isinstance(event, ProjectsInitialEvent):
                self._update_preparation_view(event.data.projects)

            # Handle incremental update events
            elif isinstance(event, SessionStartedEvent):
                sessions_view = self.views.get(1)
                if isinstance(sessions_view, SessionsView):
                    # Do not auto-select delegated child sessions; they should appear in
                    # the tree without hijacking the user's current preview.
                    is_ai_child = bool(event.data.initiator_session_id)
                    if event.data.tmux_session_name and not is_ai_child:
                        sessions_view.request_select_session(event.data.session_id, source="system")
                if self._loop:
                    self._loop.run_until_complete(self.refresh_data())

            elif isinstance(event, SessionUpdatedEvent):
                updated_session = event.data

                old_status = self._session_status_cache.get(updated_session.session_id)
                new_status = updated_session.status
                if old_status and old_status != new_status:
                    self.notify(
                        f"Session status: {old_status} → {new_status}",
                        NotificationLevel.INFO,
                    )
                self._session_status_cache[updated_session.session_id] = new_status

                # Refresh data for state changes (title, status, etc.)
                # Activity events (user input, tool use, agent output) flow through AgentActivityEvent
                if self._loop:
                    self._loop.run_until_complete(self.refresh_data())

            elif isinstance(event, AgentActivityEvent):
                # Dispatch AGENT_ACTIVITY intent with event_type, session_id, tool metadata, summary
                self.controller.dispatch(
                    Intent(
                        IntentType.AGENT_ACTIVITY,
                        {
                            "session_id": event.session_id,
                            "event_type": event.type,
                            "tool_name": event.tool_name,
                            "tool_preview": event.tool_preview,
                            "summary": event.summary,
                            "timestamp": event.timestamp,
                        },
                    )
                )
                if event.type == "agent_stop" and event.summary:
                    save_sticky_state(self.state)

            elif isinstance(event, SessionClosedEvent):
                if self._loop:
                    self._loop.run_until_complete(self.refresh_data())

            elif isinstance(event, ErrorEvent):
                self.notify(event.data.message, NotificationLevel.ERROR)

            elif hasattr(event, "event") and str(event.event).startswith("todo_"):
                # Granular todo events — refresh with todos included
                if self._loop:
                    self._loop.run_until_complete(self.refresh_data())

            else:
                # For now, trigger a full refresh for computer/project updates
                # In the future, could apply incremental updates
                if self._loop:
                    self._loop.run_until_complete(self.refresh_data())

        return updated

    def _update_sessions_view(self, sessions: list[SessionInfo]) -> None:
        """Update sessions view with fresh session data.

        Args:
            sessions: List of session dicts
        """
        sessions_view = self.views.get(1)
        if not isinstance(sessions_view, SessionsView):
            return

        sessions_view._sessions = sessions
        self._session_status_cache = {session.session_id: session.status for session in sessions}
        sessions_view._update_activity_state(sessions)
        logger.debug("Sessions view updated with %d sessions", len(sessions))

    def _on_agent_output(self, agent_name: str) -> None:
        """Trigger banner/logo animations for agent output (agent_stop)."""
        self.activity_trigger.on_agent_activity(agent_name, is_big=True)
        self.activity_trigger.on_agent_activity(agent_name, is_big=False)

    def _update_preparation_view(self, projects: list[ProjectInfo | ProjectWithTodosInfo]) -> None:  # noqa: ARG002
        """Update preparation view with fresh project data.

        Args:
            projects: List of project dicts with todos (unused - triggers full refresh)
        """
        # For now, trigger a full async refresh since preparation view
        # needs to rebuild its tree with todos
        if self._loop:
            self._loop.run_until_complete(self.refresh_data())

    def _apply_session_update(self, session: SessionInfo) -> None:
        """Apply incremental session update.

        Args:
            session: Session data dict
        """
        sessions_view = self.views.get(1)
        if not isinstance(sessions_view, SessionsView):
            return

        session_id = session.session_id

        # Find and update/add the session
        found = False
        for i, s in enumerate(sessions_view._sessions):
            if s.session_id == session_id:
                sessions_view._sessions[i] = session
                found = True
                break

        if not found:
            # Unknown session: refresh from source-of-truth data
            if self._loop:
                self._loop.run_until_complete(self.refresh_data())
            return

        # Update activity state for the changed session
        sessions_view._update_activity_state([session])
        sessions_view.update_session_node(session)
        logger.debug("Session %s updated", str(session_id)[:8])

    def _apply_session_removal(self, session_id: str) -> None:
        """Apply session removal.

        Args:
            session_id: ID of removed session
        """
        sessions_view = self.views.get(1)
        if not isinstance(sessions_view, SessionsView):
            return

        sessions_view._sessions = [s for s in sessions_view._sessions if s.session_id != session_id]
        self.controller.update_sessions(sessions_view._sessions)
        self.controller.dispatch(
            Intent(IntentType.SYNC_SESSIONS, {"session_ids": [s.session_id for s in sessions_view._sessions]})
        )
        logger.debug("Session %s removed", session_id[:8])

    def _apply_animation_mode(self) -> None:
        """Update animation engine based on current mode."""
        mode = self.state.animation_mode

        if mode == "off":
            self.animation_engine.is_enabled = False
        else:
            self.animation_engine.is_enabled = True
            self.periodic_trigger.interval_sec = config.ui.animations_periodic_interval

    def _maybe_play_party_animation(self) -> None:
        """Play continuous animations in party mode.

        Called from the render loop so it doesn't depend on the async
        event loop being pumped. Starts a new animation whenever the
        banner slot is idle.
        """
        banner_slot = self.animation_engine._targets.get("banner")
        if banner_slot and banner_slot.animation is not None:
            return  # Animation still playing

        from teleclaude.cli.tui.animation_triggers import filter_animations
        from teleclaude.cli.tui.animations.general import GENERAL_ANIMATIONS

        palette = palette_registry.get("spectrum")
        filtered = filter_animations(GENERAL_ANIMATIONS, self.periodic_trigger.animations_subset)
        if not filtered or not palette:
            return

        anim_cls = random.choice(filtered)
        self.animation_engine.play(
            anim_cls(palette=palette, is_big=True, duration_seconds=random.uniform(3, 6)),
            priority=AnimationPriority.PERIODIC,
        )

        # Also play on logo
        small_compatible = [cls for cls in filtered if cls.supports_small]
        if small_compatible:
            anim_cls_small = random.choice(small_compatible)
            self.animation_engine.play(
                anim_cls_small(palette=palette, is_big=False, duration_seconds=random.uniform(3, 6)),
                priority=AnimationPriority.PERIODIC,
            )

    def _cycle_animation_mode(self) -> None:
        """Cycle animation mode: periodic -> party -> off -> periodic."""
        modes = ["periodic", "party", "off"]
        current = self.state.animation_mode
        try:
            next_mode = modes[(modes.index(current) + 1) % len(modes)]
        except ValueError:
            next_mode = "periodic"

        self.controller.dispatch(Intent(IntentType.SET_ANIMATION_MODE, {"mode": next_mode}))
        self._apply_animation_mode()
        save_sticky_state(self.state)

        if self.footer:
            self.footer.animation_mode = next_mode

        msg = f"Animation mode: {next_mode.upper()}"
        level = NotificationLevel.INFO if next_mode != "off" else NotificationLevel.WARNING
        self.notify(msg, level)
        logger.debug("Animation mode toggled to %s", next_mode)

    def run(self, stdscr: CursesWindow) -> None:
        """Main event loop.

        Uses short timeout to poll for WebSocket updates while still responsive
        to user input. Screen updates on user input or WebSocket events.

        Args:
            stdscr: Curses screen object
        """
        curses.curs_set(0)
        init_colors()
        palette_registry.initialize_colors()  # Must be after init_colors() -> start_color()
        self._install_appearance_hook()

        # Enable mouse support (can be toggled with 'm' key to allow tmux copy-mode)
        curses.mousemask(MOUSE_MASK)

        # Use short timeout to poll for WebSocket events
        stdscr.timeout(WS_POLL_INTERVAL_MS)  # type: ignore[attr-defined]

        # Initial render
        self._render(stdscr)

        while self.running:
            # Process any pending WebSocket events
            self._process_ws_events()
            self._maybe_heal_ws()
            self._poll_theme_drift()

            key = stdscr.getch()  # type: ignore[attr-defined]

            if self._consume_reload_request():
                self._reload_self()
                return

            if self._consume_theme_refresh():
                init_colors()
                # Re-apply agent colors after theme change
                self.pane_manager.reapply_agent_colors()
                self._render(stdscr)
                continue

            if key != -1:
                self._handle_key(key, stdscr)
                # Check if view needs data refresh
                view = self.views.get(self.current_view)
                if view and getattr(view, "needs_refresh", False):
                    if self._loop:
                        self._loop.run_until_complete(self.refresh_data())
                    view.needs_refresh = False

            # Always render to advance animations, even during idle periods
            self._render(stdscr)
            sessions_view = self.views.get(1)
            if isinstance(sessions_view, SessionsView):
                sessions_view.apply_pending_activation()
                sessions_view.apply_pending_focus()
            self.controller.apply_pending_layout()
            # Detect user pane clicks on every iteration (not just layout changes)
            if isinstance(sessions_view, SessionsView):
                sessions_view.detect_pane_focus_change()

    def _consume_theme_refresh(self) -> bool:
        if self._theme_refresh_requested:
            self._theme_refresh_requested = False
            return True
        return False

    def _consume_reload_request(self) -> bool:
        if self._reload_requested:
            self._reload_requested = False
            return True
        return False

    def _maybe_heal_ws(self, now: float | None = None) -> bool:
        """Auto-heal when WebSocket is down by refreshing periodically."""
        if self.api.ws_connected:
            self._last_ws_heal = now or time.monotonic()
            return False

        current = now or time.monotonic()
        if current - self._last_ws_heal < WS_HEAL_REFRESH_S:
            return False

        self._last_ws_heal = current
        if self._loop:
            self._loop.run_until_complete(self.refresh_data())
        return True

    def _poll_theme_drift(self, now: float | None = None) -> None:
        """Fallback refresh when external mode changed but SIGUSR1 was missed."""
        current = now or time.monotonic()
        if current - self._last_theme_probe < THEME_MODE_PROBE_S:
            return
        self._last_theme_probe = current

        system_dark = get_system_dark_mode()
        if system_dark is not None:
            external_dark = system_dark
        else:
            try:
                external_dark = is_dark_mode()
            except (OSError, ValueError):
                return

        cached_dark = get_current_mode()
        if external_dark != cached_dark:
            logger.debug(
                "Detected theme mode drift (cached=%s external=%s); scheduling refresh",
                cached_dark,
                external_dark,
            )
            self._theme_refresh_requested = True

    def _install_appearance_hook(self) -> None:
        if not os.environ.get("TMUX"):
            return

        def _handle_signal(_signum: int, _frame: object | None) -> None:
            logger.debug("Received SIGUSR1 appearance refresh signal")
            self._theme_refresh_requested = True

        def _handle_reload_signal(_signum: int, _frame: object | None) -> None:
            logger.debug("Received SIGUSR2 TUI reload signal")
            self._reload_requested = True

        signal.signal(signal.SIGUSR1, _handle_signal)
        signal.signal(signal.SIGUSR2, _handle_reload_signal)
        logger.debug("Installed SIGUSR1 handler for appearance reload")

    def _reload_self(self) -> None:
        logger.debug("Reloading TUI process")
        self.cleanup()
        os.execv(sys.executable, [sys.executable, "-m", "teleclaude.cli.telec", *sys.argv[1:]])

    def _handle_key(self, key: int, stdscr: CursesWindow) -> None:
        """Handle key press.

        Args:
            key: Key code
            stdscr: Curses screen object
        """
        key_str = _key_name(key)
        logger.trace("Key pressed: %s, current_view=%d", key_str, self.current_view)

        if key == ord("q"):
            logger.debug("Quit requested")
            self.cleanup()
            self.running = False

        # Mouse events - clicks, double-clicks, and scroll wheel
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                mouse_start = time.perf_counter()
                logger.trace("Mouse event: bstate=%d (0x%x)", bstate, bstate)
                # Scroll wheel - move selection up/down
                # BUTTON4_PRESSED (0x80000) = scroll up on macOS
                # 0x8000000 or 0x200000 = scroll down (varies by system)
                if bstate & curses.BUTTON4_PRESSED:
                    view = self.views.get(self.current_view)
                    if view:
                        view.move_up()
                    logger.trace(
                        "mouse_scroll_up",
                        view=self.current_view,
                        x=mx,
                        y=my,
                        duration_ms=int((time.perf_counter() - mouse_start) * 1000),
                    )
                elif bstate & (0x8000000 | 0x200000):  # Scroll down
                    view = self.views.get(self.current_view)
                    if view:
                        view.move_down()
                    logger.trace(
                        "mouse_scroll_down",
                        view=self.current_view,
                        x=mx,
                        y=my,
                        duration_ms=int((time.perf_counter() - mouse_start) * 1000),
                    )
                # Double-click: select item and execute default action (or toggle sticky for sessions)
                elif bstate & curses.BUTTON1_DOUBLE_CLICKED:
                    if self._content_start <= my < self._content_start + self._content_height:
                        view = self.views.get(self.current_view)
                        if view and hasattr(view, "handle_click"):
                            click_start = time.perf_counter()
                            # Pass is_double_click=True to allow view-specific double-click handling
                            if view.handle_click(my, is_double_click=True):
                                click_ms = int((time.perf_counter() - click_start) * 1000)
                                logger.trace(
                                    "mouse_double_click_action",
                                    view=self.current_view,
                                    x=mx,
                                    y=my,
                                    click_ms=click_ms,
                                    total_ms=int((time.perf_counter() - mouse_start) * 1000),
                                )
                # Single click: select item or switch tab
                elif bstate & curses.BUTTON1_CLICKED:
                    height, _ = stdscr.getmaxyx()  # type: ignore[attr-defined]
                    # Check if click is on footer row
                    if my == height - 1 and self.footer and (clicked := self.footer.handle_click(mx)):
                        if clicked == "tts":
                            self.tts_enabled = not self.tts_enabled
                            self.footer.tts_enabled = self.tts_enabled
                            if self._loop:
                                asyncio.run_coroutine_threadsafe(
                                    self.api.patch_settings(
                                        SettingsPatchInfo(
                                            tts=TTSSettingsPatchInfo(enabled=self.tts_enabled),
                                        )
                                    ),
                                    self._loop,
                                )
                            logger.debug("TTS toggled to %s via footer click", self.tts_enabled)
                        elif clicked == "pane_theming_mode":
                            self._cycle_pane_theming_mode()
                        elif clicked == "animation_mode":
                            self._cycle_animation_mode()
                    # Check if a tab was clicked
                    elif self.tab_bar.handle_click(my, mx) is not None:
                        clicked_tab = self.tab_bar.handle_click(my, mx)
                        self._switch_view(clicked_tab)
                        logger.trace(
                            "mouse_single_click_tab",
                            view=self.current_view,
                            x=mx,
                            y=my,
                            duration_ms=int((time.perf_counter() - mouse_start) * 1000),
                            tab=clicked_tab,
                        )
                    # Otherwise check if click is in content area
                    elif self._content_start <= my < self._content_start + self._content_height:
                        view = self.views.get(self.current_view)
                        if view and hasattr(view, "handle_click"):
                            click_start = time.perf_counter()
                            view.handle_click(my)
                            logger.trace(
                                "mouse_single_click_content",
                                view=self.current_view,
                                x=mx,
                                y=my,
                                click_ms=int((time.perf_counter() - click_start) * 1000),
                                total_ms=int((time.perf_counter() - mouse_start) * 1000),
                            )
            except curses.error:
                pass  # Mouse event couldn't be retrieved

        # Escape - always go back in focus stack
        elif key == 27:  # Escape
            logger.debug("Escape: popping focus stack")
            if self.focus.pop():
                view = self.views.get(self.current_view)
                if view:
                    view.rebuild_for_focus()
                    logger.debug("Focus popped, view rebuilt")
                self._sync_focus_subscriptions()

        # Left Arrow - collapse session or go back in focus stack
        elif key == curses.KEY_LEFT:
            view = self.views.get(self.current_view)
            logger.debug("Left arrow: view=%s", type(view).__name__ if view else None)
            # Try to collapse session first (SessionsView only)
            if isinstance(view, SessionsView):
                collapsed = view.collapse_selected()
                logger.debug("collapse_selected() returned %s", collapsed)
                if collapsed:
                    pass  # Session collapsed
                elif self.focus.pop():
                    # Go back in focus stack
                    view.rebuild_for_focus()
                    logger.debug("Focus popped after collapse_selected returned False")
                    self._sync_focus_subscriptions()
            elif self.focus.pop():
                if view:
                    view.rebuild_for_focus()
                self._sync_focus_subscriptions()

        # Right Arrow - drill down into selected item
        elif key == curses.KEY_RIGHT:
            view = self.views.get(self.current_view)
            logger.debug("Right arrow: view=%s", type(view).__name__ if view else None)
            if isinstance(view, SessionsView):
                result = view.drill_down()
                logger.debug("drill_down() returned %s", result)
                if result:
                    self._sync_focus_subscriptions()

        # View switching with number keys
        elif key == ord("1"):
            logger.debug("Switching to view 1 (Sessions)")
            self._switch_view(1)
        elif key == ord("2"):
            logger.debug("Switching to view 2 (Preparation)")
            self._switch_view(2)
        elif key == ord("3"):
            logger.debug("Switching to view 3 (Jobs)")
            self._switch_view(3)
        elif key == ord("4"):
            logger.debug("Switching to view 4 (Configuration)")
            self._switch_view(4)

        # Navigation - delegate to current view
        elif key == curses.KEY_UP:
            view = self.views.get(self.current_view)
            if view:
                view.move_up()
                logger.debug("move_up: selected_index=%d", view.selected_index)
        elif key == curses.KEY_DOWN:
            view = self.views.get(self.current_view)
            if view:
                view.move_down()
                logger.debug("move_down: selected_index=%d", view.selected_index)

        # Common actions
        elif key in (curses.KEY_ENTER, 10, 13):
            view = self.views.get(self.current_view)
            logger.debug("Enter: view=%s", type(view).__name__ if view else None)
            if view:
                view.handle_enter(stdscr)
        elif key == ord("r"):
            logger.debug("Refresh requested")
            if self._loop:
                self._loop.run_until_complete(self.refresh_data())

        # Agent restart (Sessions view only)
        elif key == ord("R"):
            view = self.views.get(self.current_view)
            if isinstance(view, SessionsView) and view.flat_items:
                selected = view.flat_items[view.selected_index]
                if is_session_node(selected):
                    session_id = selected.data.session.session_id
                    if session_id:
                        logger.debug("Agent restart requested for session %s", session_id[:8])
                        try:
                            asyncio.get_event_loop().run_until_complete(self.api.agent_restart(session_id))
                            self.notify("Agent restart triggered", NotificationLevel.INFO)
                        except Exception as e:
                            logger.error("Error restarting agent: %s", e)
                            self.notify(f"Restart failed: {e}", NotificationLevel.ERROR)
                elif is_computer_node(selected):
                    computer_name = selected.data.computer.name
                    session_ids = view.get_session_ids_for_computer(computer_name)
                    if not session_ids:
                        self.notify(
                            f"No sessions to restart on {computer_name}",
                            NotificationLevel.INFO,
                        )
                        return
                    logger.debug(
                        "Agent restart requested for computer %s (%d sessions)",
                        computer_name,
                        len(session_ids),
                    )
                    try:
                        successes, errors = asyncio.get_event_loop().run_until_complete(
                            self._restart_sessions(session_ids)
                        )
                        self.notify_bulk_result("Restarted", f"on {computer_name}", len(session_ids), successes, errors)
                    except Exception as e:
                        logger.error("Error restarting agents: %s", e)
                        self.notify(f"Restart failed: {e}", NotificationLevel.ERROR)

        # TTS toggle hotkey
        elif key == ord("v"):
            self.tts_enabled = not self.tts_enabled
            if self.footer:
                self.footer.tts_enabled = self.tts_enabled
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.api.patch_settings(SettingsPatchInfo(tts=TTSSettingsPatchInfo(enabled=self.tts_enabled))),
                    self._loop,
                )
            logger.debug("TTS toggled to %s via hotkey", self.tts_enabled)
        elif key == ord("c"):
            self._cycle_pane_theming_mode()
            logger.debug("Pane theming mode toggled to %s via hotkey", self.pane_theming_mode)

        # Animation mode toggle
        elif key == ord("m"):
            self._cycle_animation_mode()

        # View-specific actions
        else:
            view = self.views.get(self.current_view)
            logger.debug(
                "Delegating key %s to view.handle_key(), view=%s",
                key_str,
                type(view).__name__ if view else None,
            )
            if view:
                view.handle_key(key, stdscr)
            else:
                logger.warning("No view found for current_view=%d", self.current_view)

    async def _restart_sessions(self, session_ids: list[str]) -> tuple[int, list["APIError"]]:
        """Restart multiple sessions in parallel.

        Returns:
            Tuple of (successes, list of APIError for failures)
        """
        from teleclaude.cli.api_client import APIError

        results = await asyncio.gather(
            *(self.api.agent_restart(session_id) for session_id in session_ids),
            return_exceptions=True,
        )
        successes = 0
        errors: list[APIError] = []
        for result in results:
            if isinstance(result, APIError):
                errors.append(result)
            elif isinstance(result, Exception):
                # Wrap unexpected exceptions
                errors.append(APIError(str(result), detail=str(result)))
            elif result is True:
                successes += 1
            else:
                errors.append(APIError("Unknown failure", detail="Restart failed"))
        return successes, errors

    def _switch_view(self, view_num: int) -> None:
        """Switch to a different view.

        Args:
            view_num: View number (1 or 2)
        """
        current_view = self.current_view
        if view_num in self.views:
            logger.debug("Switching from view %d to view %d", self.current_view, view_num)
            self.current_view = view_num
            self.tab_bar.set_active(view_num)
            # Rebuild the new view with current focus
            view = self.views.get(view_num)
            if view:
                view.rebuild_for_focus()
                logger.debug(
                    "View %d rebuilt: flat_items=%d, selected_index=%d",
                    view_num,
                    len(view.flat_items),
                    view.selected_index,
                )
                if view_num == 2:
                    if self._loop:
                        self._loop.run_until_complete(self.refresh_data())
            # Panes remain unchanged across view switches.
            if current_view == 2 and view_num != 2:
                prep_view = self.views.get(2)
                if isinstance(prep_view, PreparationView):
                    prep_view.controller.dispatch(Intent(IntentType.CLEAR_PREP_PREVIEW), defer_layout=True)
        else:
            logger.warning("Attempted to switch to non-existent view %d", view_num)

    def _render(self, stdscr: CursesWindow) -> None:
        """Render current view with banner, tab bar, and footer.

        Args:
            stdscr: Curses screen object
        """
        stdscr.erase()  # type: ignore[attr-defined]  # erase() doesn't affect scroll buffer
        height, width = stdscr.getmaxyx()  # type: ignore[attr-defined]

        # Update animations
        self.animation_engine.update()

        # Party mode: play continuous back-to-back animations directly
        # (bypasses async periodic trigger which depends on event loop pumping)
        if self.state.animation_mode == "party":
            self._maybe_play_party_animation()

        # Calculate pane counts (1 TUI pane + session panes)
        total_panes = 1  # TUI pane
        banner_panes = 1  # TUI pane + sticky panes only (stable across previews)
        sticky_session_ids = [s.session_id for s in self.state.sessions.sticky_sessions]
        total_sticky = len(sticky_session_ids)
        total_panes += total_sticky
        banner_panes += total_sticky

        if self.state.sessions.preview and self.state.sessions.preview.session_id not in sticky_session_ids:
            total_panes += 1
        elif self.state.preparation.preview:
            total_panes += 1

        # Hide banner for 4 or 6 panes (optimizes vertical space for grid layouts)
        show_banner = banner_panes not in (4, 6)
        if show_banner:
            render_banner(stdscr, 0, width, self.animation_engine)

        # Row after banner: Tab bar (3 rows for browser-style tabs)
        tab_row = BANNER_HEIGHT if show_banner else 0
        # When banner is hidden, tab bar bottom line stops before logo
        logo_width = 39 if not show_banner else None
        self.tab_bar.render(stdscr, tab_row, width, logo_width)

        # When banner is hidden, show TELECLAUDE ASCII art at top right (render after tab bar)
        if not show_banner:
            self._render_hidden_banner_header(stdscr, width, self.animation_engine)

        # Row after tab bar: empty row for spacing, then breadcrumb (if focused)
        content_start = tab_row + TabBar.HEIGHT + 1  # +HEIGHT for tab bar + 1 for spacing
        if self.focus.stack:
            self._render_breadcrumb(stdscr, content_start, width)
            content_start += 1

        # Content area: after breadcrumb to before footer section
        content_height = height - content_start - 4  # Reserve 4 rows for separator + action bar + global bar + footer

        # Store bounds for mouse click handling
        self._content_start = content_start
        self._content_height = content_height

        current = self.views.get(self.current_view)
        if current and content_height > 0:
            current.render(stdscr, content_start, content_height, width)

        # Render notification (toast) if active - position on empty line below tab bar
        toast_row = tab_row + TabBar.HEIGHT
        self._render_notification(stdscr, width, toast_row)

        # Row height-4: Separator (avoid last-column writes)
        separator_attr = get_tab_line_attr()
        line_width = max(0, width - 1)
        separator_width = max(0, width)
        stdscr.addstr(height - 4, 0, "─" * separator_width, separator_attr)  # type: ignore[attr-defined]

        # Row height-3: Action bar (view-specific)
        action_bar = current.get_action_bar() if current else ""
        stdscr.addstr(height - 3, 0, action_bar[:line_width])  # type: ignore[attr-defined]

        # Row height-2: Global shortcuts bar
        global_bar = "[+/-] Expand/Collapse  [r] Refresh  [v] TTS  [m] Anim  [c] Colors  [q] Quit"
        stdscr.addstr(height - 2, 0, global_bar[:line_width], curses.A_DIM)  # type: ignore[attr-defined]

        # Row height-1: Footer
        if self.footer and line_width > 0:
            self.footer.pane_theming_agent = self._get_footer_pane_theming_agent()
            self.footer.render(stdscr, height - 1, line_width)

        stdscr.move(0, 0)  # type: ignore[attr-defined]
        stdscr.refresh()  # type: ignore[attr-defined]

    def _get_footer_pane_theming_agent(self) -> str:
        """Pick the current row agent so pane-theming indicator can mirror highlights."""
        view = self.views.get(self.current_view)
        if not view or not hasattr(view, "flat_items") or not hasattr(view, "selected_index"):
            return "codex"

        flat_items = getattr(view, "flat_items")
        selected_index = getattr(view, "selected_index")
        if not flat_items or not isinstance(selected_index, int):
            return "codex"
        if selected_index < 0 or selected_index >= len(flat_items):
            return "codex"

        selected = flat_items[selected_index]
        if self.current_view == 1 and is_session_node(selected):
            return selected.data.session.active_agent or "codex"

        return "codex"

    def _render_breadcrumb(self, stdscr: object, row: int, width: int) -> None:
        """Render breadcrumb with last part bold.

        Args:
            stdscr: Curses screen object
            row: Row to render at
            width: Screen width
        """
        if not self.focus.stack:
            return

        prefix = "  📍 "
        parts: list[str] = []
        for level in self.focus.stack:
            if level.type is FocusLevelType.COMPUTER:
                parts.append(level.name)
            elif level.type is FocusLevelType.PROJECT:
                parts.append(level.name.split("/")[-1] or level.name)

        try:
            col = 0
            # Render prefix
            stdscr.addstr(row, col, prefix)  # type: ignore[attr-defined]
            col += len(prefix)

            # Render all parts except last (normal)
            for part in parts[:-1]:
                stdscr.addstr(row, col, part)  # type: ignore[attr-defined]
                col += len(part)
                stdscr.addstr(row, col, " > ")  # type: ignore[attr-defined]
                col += 3

            # Render last part (bold)
            if parts:
                stdscr.addstr(row, col, parts[-1], curses.A_BOLD)  # type: ignore[attr-defined]
        except curses.error:
            pass  # Screen too small

    def _render_hidden_banner_header(
        self, stdscr: object, width: int, animation_engine: Optional[AnimationEngine] = None
    ) -> None:
        """Render TELECLAUDE ASCII art logo at top right when banner is hidden.

        Args:
            stdscr: Curses screen object
            width: Screen width
            animation_engine: Optional animation engine for colors
        """
        from teleclaude.cli.tui.theme import get_banner_attr, get_current_mode

        logo_lines = [
            "▀█▀ ▛▀▀ ▌   ▛▀▀ ▛▀▜ ▌   ▞▀▚ ▌ ▐ ▛▀▚ ▛▀▀",
            " █  ■■  ▌   ■■  ▌   ▌   ▙▄▟ ▌ ▐ ▌ ▐ ■■",
            " █  ▙▄▄ ▙▄▄ ▙▄▄ ▙▄▟ ▙▄▄ ▌ ▐ ▚▄▞ ▙▄▞ ▙▄▄",
        ]
        logo_width = 39  # Width of the logo

        if width > logo_width + 1:  # +1 for the gap
            try:
                is_dark_mode = get_current_mode()
                banner_attr = get_banner_attr(is_dark_mode)
                start_col = width - logo_width
                for i, line in enumerate(logo_lines):
                    for j, char in enumerate(line):
                        attr = banner_attr
                        if animation_engine:
                            color_idx = animation_engine.get_color(j, i, is_big=False)
                            if color_idx is not None:
                                attr = curses.color_pair(color_idx)
                        stdscr.addstr(i, start_col + j, char, attr)  # type: ignore[attr-defined]
            except curses.error:
                pass  # Ignore if can't render

    def _render_notification(self, stdscr: object, width: int, row: int) -> None:
        """Render notification toast if active (supports multi-line with box).

        Args:
            stdscr: Curses screen object
            width: Screen width
            row: Row to render notification at
        """
        if not self.notification:
            return

        # Check if expired
        if time.time() > self.notification.expires_at:
            self.notification = None
            return

        lines = self.notification.lines
        if not lines:
            return

        # Calculate box dimensions
        max_text_len = max(len(line.text) for line in lines)
        box_width = max_text_len + 4  # 2 padding + 2 border
        start_col = max(0, (width - box_width) // 2)

        # Box drawing characters
        top_border = "┌" + "─" * (box_width - 2) + "┐"
        bottom_border = "└" + "─" * (box_width - 2) + "┘"

        # Determine border color (red if any errors, else normal)
        has_error = any(line.level is NotificationLevel.ERROR for line in lines)
        border_attr = curses.color_pair(1) | curses.A_BOLD if has_error else curses.A_NORMAL

        try:
            # Top border
            stdscr.addstr(row, start_col, top_border[: width - start_col], border_attr)  # type: ignore[attr-defined]

            # Content lines
            for i, line in enumerate(lines):
                content_row = row + 1 + i
                # Line color based on level
                if line.level is NotificationLevel.ERROR:
                    text_attr = curses.color_pair(1) | curses.A_BOLD  # Red
                elif line.level is NotificationLevel.SUCCESS:
                    text_attr = curses.color_pair(2) | curses.A_BOLD  # Green
                else:
                    text_attr = curses.A_NORMAL

                # Render line with padding
                padded_text = line.text.ljust(max_text_len)
                stdscr.addstr(content_row, start_col, "│", border_attr)  # type: ignore[attr-defined]
                stdscr.addstr(content_row, start_col + 1, f" {padded_text} ", text_attr)  # type: ignore[attr-defined]
                stdscr.addstr(content_row, start_col + box_width - 1, "│", border_attr)  # type: ignore[attr-defined]

            # Bottom border
            bottom_row = row + 1 + len(lines)
            stdscr.addstr(bottom_row, start_col, bottom_border[: width - start_col], border_attr)  # type: ignore[attr-defined]
        except curses.error:
            pass  # Ignore if can't render (screen too small)


if TYPE_CHECKING:
    from teleclaude.cli.api_client import APIError, TelecAPIClient
