"""Main TUI application built on Textual."""

from __future__ import annotations

import asyncio
import signal
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from textual import work
from textual.app import App, ComposeResult
from textual.widgets import TabbedContent, TabPane

from teleclaude.cli.models import (
    AgentActivityEvent,
    ErrorEvent,
    ProjectsInitialEvent,
    SessionClosedEvent,
    SessionsInitialEvent,
    SessionStartedEvent,
    SessionUpdatedEvent,
    WsEvent,
)
from teleclaude.cli.tui.messages import (
    AgentActivity,
    CreateSessionRequest,
    DataRefreshed,
    KillSessionRequest,
    RestartSessionRequest,
    SessionClosed,
    SessionStarted,
    SessionUpdated,
    SettingsChanged,
)
from teleclaude.cli.tui.pane_bridge import PaneManagerBridge
from teleclaude.cli.tui.state_store import load_state, save_state
from teleclaude.cli.tui.views.config import ConfigView
from teleclaude.cli.tui.views.jobs import JobsView
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.action_bar import ActionBar
from teleclaude.cli.tui.widgets.banner import Banner
from teleclaude.cli.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from teleclaude.cli.api_client import TelecAPIClient

logger = get_logger(__name__)


# Legacy stub — old configuration.py imports this via TYPE_CHECKING.
# Remove in Phase 4 cleanup.
class FocusContext:
    pass


class TelecApp(App[None]):
    """Main TeleClaude TUI application."""

    CSS_PATH = "telec.tcss"

    TITLE = "TeleClaude"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("1", "switch_tab('sessions')", "Sessions"),
        ("2", "switch_tab('preparation')", "Preparation"),
        ("3", "switch_tab('jobs')", "Jobs"),
        ("4", "switch_tab('config')", "Config"),
        ("r", "refresh", "Refresh"),
        ("t", "cycle_pane_theming", "Cycle pane theme"),
    ]

    def __init__(
        self,
        api: TelecAPIClient,
        start_view: int = 1,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.api = api
        self._start_view = start_view
        self._persisted = load_state()
        self._session_status_cache: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Banner()
        with TabbedContent(id="main-tabs"):
            with TabPane("[1] Sessions", id="sessions"):
                yield SessionsView(id="sessions-view")
            with TabPane("[2] Preparation", id="preparation"):
                yield PreparationView(id="preparation-view")
            with TabPane("[3] Jobs", id="jobs"):
                yield JobsView(id="jobs-view")
            with TabPane("[4] Config", id="config"):
                yield ConfigView(id="config-view")
        yield ActionBar(id="action-bar")
        yield StatusBar(id="status-bar")
        yield PaneManagerBridge(id="pane-bridge")

    async def on_mount(self) -> None:
        """Initialize on mount: load state, connect API, start refresh."""
        # Restore persisted state to views
        sessions_view = self.query_one("#sessions-view", SessionsView)
        prep_view = self.query_one("#preparation-view", PreparationView)
        status_bar = self.query_one("#status-bar", StatusBar)

        sessions_view.load_persisted_state(
            sticky_ids=self._persisted.sticky_session_ids,
            input_highlights=self._persisted.input_highlights,
            output_highlights=self._persisted.output_highlights,
            last_output_summary=self._persisted.last_output_summary,
            collapsed_sessions=self._persisted.collapsed_sessions,
            preview_session_id=self._persisted.preview_session_id,
        )
        prep_view.load_persisted_state(
            expanded_todos=self._persisted.expanded_todos,
        )
        status_bar.animation_mode = self._persisted.animation_mode

        # Switch to starting tab
        tab_ids = {1: "sessions", 2: "preparation", 3: "jobs", 4: "config"}
        start_tab = tab_ids.get(self._start_view, "sessions")
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = start_tab

        # Connect API and start refresh
        try:
            await self.api.connect()
        except Exception:
            logger.exception("Failed to connect API")

        # Start WebSocket for push updates
        self.api.start_websocket(
            callback=self._on_ws_event,
            subscriptions=["sessions", "projects", "todos"],
        )

        # Initial data load
        self._refresh_data()

        # Periodic refresh every 5s
        self.set_interval(5, self._refresh_data)

        # SIGUSR2 handler for reload
        try:
            signal.signal(signal.SIGUSR2, self._handle_sigusr2)
        except (ValueError, OSError):
            pass

    @work(exclusive=True, group="refresh")
    async def _refresh_data(self) -> None:
        """Fetch all data from API and post DataRefreshed."""
        try:
            computers, projects, projects_with_todos, sessions, availability, jobs = await asyncio.gather(
                self.api.list_computers(),
                self.api.list_projects(),
                self.api.list_projects_with_todos(),
                self.api.list_sessions(),
                self.api.get_agent_availability(),
                self.api.list_jobs(),
            )

            # Get settings for TTS and pane theming
            try:
                settings = await self.api.get_settings()
                tts_enabled = bool(getattr(settings, "tts_enabled", False))
                pane_theming_mode = getattr(settings, "pane_theming_mode", "off") or "off"
            except Exception:
                tts_enabled = False
                pane_theming_mode = "off"

            self.post_message(
                DataRefreshed(
                    computers=computers,
                    projects=projects,
                    projects_with_todos=projects_with_todos,
                    sessions=sessions,
                    availability=availability,
                    jobs=jobs,
                    tts_enabled=tts_enabled,
                    pane_theming_mode=pane_theming_mode,
                )
            )
        except Exception:
            logger.exception("Data refresh failed")

    def on_data_refreshed(self, message: DataRefreshed) -> None:
        """Handle refreshed data — update all views."""
        sessions_view = self.query_one("#sessions-view", SessionsView)
        prep_view = self.query_one("#preparation-view", PreparationView)
        jobs_view = self.query_one("#jobs-view", JobsView)
        status_bar = self.query_one("#status-bar", StatusBar)

        sessions_view.update_data(
            computers=message.computers,
            projects=message.projects,
            sessions=message.sessions,
            availability=message.availability,
        )
        prep_view.update_data(message.projects_with_todos)
        jobs_view.update_data(message.jobs)
        status_bar.update_availability(message.availability)
        status_bar.tts_enabled = message.tts_enabled
        status_bar.pane_theming_mode = message.pane_theming_mode

        # Update session status cache
        self._session_status_cache = {s.session_id: s.status for s in message.sessions}

    # --- WebSocket event handling ---

    def _on_ws_event(self, event: WsEvent) -> None:
        """Handle WebSocket event from background thread — safe handoff to Textual."""
        self.call_from_thread(self._handle_ws_event, event)

    def _handle_ws_event(self, event: WsEvent) -> None:
        """Process WebSocket event in the main thread."""
        if isinstance(event, SessionsInitialEvent):
            sessions_view = self.query_one("#sessions-view", SessionsView)
            sessions_view.update_data(
                computers=sessions_view._computers,
                projects=sessions_view._projects,
                sessions=event.data.sessions,
            )

        elif isinstance(event, ProjectsInitialEvent):
            prep_view = self.query_one("#preparation-view", PreparationView)
            prep_view.update_data(event.data.projects)

        elif isinstance(event, SessionStartedEvent):
            self.post_message(SessionStarted(event.data))
            self._session_status_cache[event.data.session_id] = event.data.status

        elif isinstance(event, SessionUpdatedEvent):
            session = event.data
            old_status = self._session_status_cache.get(session.session_id)
            if old_status and old_status != session.status:
                self.notify(f"Session: {old_status} -> {session.status}")
            self._session_status_cache[session.session_id] = session.status
            self.post_message(SessionUpdated(session))

        elif isinstance(event, AgentActivityEvent):
            self.post_message(
                AgentActivity(
                    session_id=event.session_id,
                    activity_type=event.type,
                    tool_name=event.tool_name,
                    tool_preview=event.tool_preview,
                    summary=event.summary,
                    timestamp=event.timestamp,
                )
            )

        elif isinstance(event, SessionClosedEvent):
            self.post_message(SessionClosed(event.data.session_id))
            self._session_status_cache.pop(event.data.session_id, None)

        elif isinstance(event, ErrorEvent):
            self.notify(event.data.message, severity="error")

        else:
            event_name = getattr(event, "event", "")
            if str(event_name).startswith("todo_"):
                self._refresh_data()
            else:
                logger.debug("Unhandled WS event: %s", event_name)

    # --- Message handlers for WS-generated messages ---

    def on_session_started(self, message: SessionStarted) -> None:
        sessions_view = self.query_one("#sessions-view", SessionsView)
        sessions_view.update_session(message.session)

    def on_session_updated(self, message: SessionUpdated) -> None:
        sessions_view = self.query_one("#sessions-view", SessionsView)
        sessions_view.update_session(message.session)

    def on_session_closed(self, message: SessionClosed) -> None:
        self._refresh_data()

    def on_agent_activity(self, message: AgentActivity) -> None:
        sessions_view = self.query_one("#sessions-view", SessionsView)
        if message.activity_type == "agent_input":
            sessions_view.set_input_highlight(message.session_id)
        elif message.activity_type == "agent_stop":
            sessions_view.set_output_highlight(message.session_id, message.summary or "")
            self._save_state()
        elif message.activity_type == "tool_use" and message.tool_name:
            preview = message.tool_preview or ""
            tool_info = f"{message.tool_name}: {preview}" if preview else message.tool_name
            sessions_view.set_active_tool(message.session_id, tool_info)

    # --- Action handlers for user-initiated actions ---

    @work(exclusive=True, group="session-action")
    async def on_create_session_request(self, message: CreateSessionRequest) -> None:
        try:
            await self.api.create_session(
                computer=message.computer,
                project_path=message.project_path,
                agent=message.agent or "claude",
                thinking_mode=message.thinking_mode or "slow",
                title=message.title,
                message=message.message,
            )
        except Exception as e:
            self.notify(f"Failed to create session: {e}", severity="error")

    @work(exclusive=True, group="session-action")
    async def on_kill_session_request(self, message: KillSessionRequest) -> None:
        try:
            await self.api.end_session(message.session_id, message.computer)
        except Exception as e:
            self.notify(f"Failed to kill session: {e}", severity="error")

    @work(exclusive=True, group="session-action")
    async def on_restart_session_request(self, message: RestartSessionRequest) -> None:
        try:
            await self.api.end_session(message.session_id, message.computer)
            await asyncio.sleep(1)
            await self.api.revive_session(message.session_id)
        except Exception as e:
            self.notify(f"Failed to restart session: {e}", severity="error")

    async def on_settings_changed(self, message: SettingsChanged) -> None:
        key = message.key
        if key.startswith("run_job:"):
            job_name = key.split(":", 1)[1]
            try:
                await self.api.run_job(job_name)
                self.notify(f"Job '{job_name}' started")
            except Exception as e:
                self.notify(f"Failed to run job: {e}", severity="error")

    # --- Tab switching ---

    def action_switch_tab(self, tab_id: str) -> None:
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = tab_id
        action_bar = self.query_one("#action-bar", ActionBar)
        action_bar.active_view = tab_id

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        action_bar = self.query_one("#action-bar", ActionBar)
        action_bar.active_view = event.pane.id or "sessions"

    # --- Pane theming ---

    def action_cycle_pane_theming(self) -> None:
        from teleclaude.cli.tui import theme

        current_level = theme.get_pane_theming_mode_level()
        next_level = (current_level + 1) % 5
        mode = theme.get_pane_theming_mode_from_level(next_level)
        theme.set_pane_theming_mode(mode)
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.pane_theming_mode = mode
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.reapply_colors()

    # --- Refresh ---

    def action_refresh(self) -> None:
        self._refresh_data()

    # --- State persistence ---

    def _save_state(self) -> None:
        sessions_view = self.query_one("#sessions-view", SessionsView)
        prep_view = self.query_one("#preparation-view", PreparationView)
        status_bar = self.query_one("#status-bar", StatusBar)
        save_state(
            sessions_state=sessions_view.get_persisted_state(),
            preparation_state=prep_view.get_persisted_state(),
            animation_mode=status_bar.animation_mode,
        )

    # --- Signal handlers ---

    def _handle_sigusr2(self, _signum: int, _frame: object) -> None:
        """SIGUSR2: reload TUI."""
        self.call_from_thread(self._refresh_data)

    # --- Lifecycle ---

    async def action_quit(self) -> None:
        self._save_state()
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.cleanup()
        await self.api.close()
        self.exit()
