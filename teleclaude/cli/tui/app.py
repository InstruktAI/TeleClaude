"""Main TUI application built on Textual."""

from __future__ import annotations

import asyncio
import os
import signal
import time as _t
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import TabbedContent, TabPane

from teleclaude.cli.models import (
    AgentActivityEvent,
    ComputerInfo,
    ErrorEvent,
    ProjectInfo,
    ProjectsInitialEvent,
    ProjectWithTodosInfo,
    SessionClosedEvent,
    SessionLifecycleStatusEvent,
    SessionsInitialEvent,
    SessionStartedEvent,
    SessionUpdatedEvent,
    WsEvent,
)
from teleclaude.cli.tui.messages import (
    AgentActivity,
    CreateSessionRequest,
    DataRefreshed,
    DocEditRequest,
    DocPreviewRequest,
    FocusPaneRequest,
    KillSessionRequest,
    PreviewChanged,
    RestartSessionRequest,
    RestartSessionsRequest,
    ReviveSessionRequest,
    SessionClosed,
    SessionStarted,
    SessionUpdated,
    SettingsChanged,
    StateChanged,
    StickyChanged,
)
from teleclaude.cli.tui.pane_bridge import PaneManagerBridge
from teleclaude.cli.tui.persistence import Persistable, get_persistence_key
from teleclaude.cli.tui.state_store import load_state, save_state
from teleclaude.cli.tui.theme import (
    _TELECLAUDE_DARK_AGENT_THEME,
    _TELECLAUDE_DARK_THEME,
    _TELECLAUDE_LIGHT_AGENT_THEME,
    _TELECLAUDE_LIGHT_THEME,
    get_pane_theming_mode_level,
    get_system_dark_mode,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    get_tui_inactive_background,
)
from teleclaude.cli.tui.views.config import ConfigView
from teleclaude.cli.tui.views.jobs import JobsView
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.banner import Banner
from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar
from teleclaude.cli.tui.widgets.telec_footer import TelecFooter

if TYPE_CHECKING:
    from teleclaude.cli.api_client import TelecAPIClient

logger = get_logger(__name__)


# Legacy stub — old configuration.py imports this via TYPE_CHECKING.
# Remove in Phase 4 cleanup.
class FocusContext:
    pass


RELOAD_EXIT = "__RELOAD__"


class TelecApp(App[str | None]):
    """Main TeleClaude TUI application."""

    CSS_PATH = "telec.tcss"

    TITLE = "TeleClaude"

    BINDINGS = [
        Binding("q", "quit", "Quit", key_display="⏻"),
        Binding(
            "1",
            "switch_tab('sessions')",
            "Sessions",
            key_display="①",
            group=Binding.Group("Views", compact=True),
            show=False,
        ),
        Binding(
            "2",
            "switch_tab('preparation')",
            "Prep",
            key_display="②",
            group=Binding.Group("Views", compact=True),
            show=False,
        ),
        Binding(
            "3",
            "switch_tab('jobs')",
            "Jobs",
            key_display="③",
            group=Binding.Group("Views", compact=True),
            show=False,
        ),
        Binding(
            "4",
            "switch_tab('config')",
            "Config",
            key_display="④",
            group=Binding.Group("Views", compact=True),
            show=False,
        ),
        Binding("r", "refresh", "Refresh", key_display="↻"),
        Binding("t", "cycle_pane_theming", "Cycle Theme", key_display="◑"),
    ]

    def __init__(
        self,
        api: TelecAPIClient,
        start_view: int = 1,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.register_theme(_TELECLAUDE_DARK_THEME)
        self.register_theme(_TELECLAUDE_LIGHT_THEME)
        self.register_theme(_TELECLAUDE_DARK_AGENT_THEME)
        self.register_theme(_TELECLAUDE_LIGHT_AGENT_THEME)
        from teleclaude.cli.tui import theme
        from teleclaude.cli.tui.theme import is_dark_mode

        self._persisted = load_state()
        persisted_status = self._persisted.get("status_bar", {})
        persisted_mode = persisted_status.get("pane_theming_mode")
        if isinstance(persisted_mode, str) and persisted_mode:
            try:
                theme.set_pane_theming_mode(persisted_mode)
            except ValueError:
                persisted_mode = None

        is_dark = is_dark_mode()
        try:
            level = get_pane_theming_mode_level(persisted_mode if isinstance(persisted_mode, str) else None)
        except ValueError:
            level = get_pane_theming_mode_level()
        is_agent = level in (1, 3, 4)

        if is_dark:
            self.theme = "teleclaude-dark-agent" if is_agent else "teleclaude-dark"
        else:
            self.theme = "teleclaude-light-agent" if is_agent else "teleclaude-light"

        self.api = api
        self._start_view = start_view
        self._state_save_timer: object | None = None
        self._computers: list[ComputerInfo] = []
        self._session_status_cache: dict[str, str] = {}
        self._session_agents: dict[str, str] = {}
        # On SIGUSR2 reload, panes already exist — the bridge's on_data_refreshed
        # will call seed_for_reload() to map them.  Skip layout re-application
        # on the first data refresh to avoid killing and recreating panes.
        self._is_reload = bool(os.environ.pop("TELEC_RELOAD", ""))
        self._initial_layout_applied = self._is_reload
        # Animation engine and triggers
        from teleclaude.cli.tui.animation_engine import AnimationEngine

        self._animation_engine = AnimationEngine()
        self._periodic_trigger: object | None = None
        self._activity_trigger: object | None = None
        self._animation_timer: object | None = None

    def get_css_variables(self) -> dict[str, str]:
        """Override CSS variables to inject haze background when unfocused.

        Textual emits explicit ANSI backgrounds for every cell, so tmux's
        window-style cannot apply its inactive haze. We swap $background
        at the CSS variable level so ALL widgets pick up the haze color.
        """
        variables = super().get_css_variables()
        if not self.app_focus:
            haze = get_tui_inactive_background()
            variables["background"] = haze
            variables["scrollbar-background"] = haze
        return variables

    def _watch_app_focus(self, focus: bool) -> None:
        """Trigger CSS variable recomputation on focus change.

        Uses refresh_css() — the same mechanism Textual uses for theme
        switching. This recomputes get_css_variables() and propagates
        $background to all widgets.
        """
        self.refresh_css(animate=False)

    def compose(self) -> ComposeResult:
        logger.trace("[PERF] compose START t=%.3f", _t.monotonic())
        yield Banner()
        yield BoxTabBar(id="box-tab-bar")
        with TabbedContent(id="main-tabs"):
            with TabPane("Sessions", id="sessions"):
                yield SessionsView(id="sessions-view")
            with TabPane("Preparation", id="preparation"):
                yield PreparationView(id="preparation-view")
            with TabPane("Jobs", id="jobs"):
                yield JobsView(id="jobs-view")
            with TabPane("Config", id="config"):
                yield ConfigView(id="config-view")
        with Vertical(id="footer-area"):
            yield TelecFooter(id="telec-footer")
        yield PaneManagerBridge(is_reload=self._is_reload, id="pane-bridge")
        logger.trace("[PERF] compose END t=%.3f", _t.monotonic())

    async def on_mount(self) -> None:
        """Initialize on mount: load state, connect API, start refresh."""
        _m0 = _t.monotonic()
        logger.trace("[PERF] on_mount START t=%.3f", _m0)
        # Restore persisted state to views
        sessions_view = self.query_one("#sessions-view", SessionsView)
        prep_view = self.query_one("#preparation-view", PreparationView)
        status_bar = self.query_one("#telec-footer", TelecFooter)

        sessions_state = self._persisted.get("sessions", {})
        sessions_view.load_persisted_state(sessions_state)

        preparation_state = self._persisted.get("preparation", {})
        prep_view.load_persisted_state(preparation_state)

        status_bar_state = self._persisted.get("status_bar", {})
        status_bar.load_persisted_state(status_bar_state)

        # Apply persisted pane theming to the in-memory theme override
        from teleclaude.cli.tui import theme

        theme.set_pane_theming_mode(status_bar.pane_theming_mode)
        self._apply_app_theme_for_mode(status_bar.pane_theming_mode)

        # Wire animation engine to banner
        banner = self.query_one(Banner)
        banner.animation_engine = self._animation_engine
        self._start_animation_mode(status_bar.animation_mode)

        # Switch to starting tab
        tab_ids = {1: "sessions", 2: "preparation", 3: "jobs", 4: "config"}
        persisted_app_state = self._persisted.get("app", {})
        persisted_tab = persisted_app_state.get("active_tab")
        if self._start_view != 1:
            start_tab = tab_ids.get(self._start_view, "sessions")
        elif isinstance(persisted_tab, str) and persisted_tab in tab_ids.values():
            start_tab = persisted_tab
        else:
            start_tab = "sessions"
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = start_tab
        box_tabs = self.query_one("#box-tab-bar", BoxTabBar)
        box_tabs.active_tab = start_tab

        # Focus the active view so key bindings work
        self._focus_active_view(start_tab)

        # Connect API and start refresh
        try:
            await self.api.connect()
        except Exception:
            logger.exception("Failed to connect API")

        # Start WebSocket for push updates
        self.api.start_websocket(
            callback=self._on_ws_event,
            subscriptions=["sessions", "preparation", "todos"],
        )

        logger.trace("[PERF] on_mount api+ws done dt=%.3f", _t.monotonic() - _m0)

        # Initial data load (computers loaded in parallel inside _refresh_data)
        self._refresh_data()
        self.call_after_refresh(lambda: logger.trace("[PERF] on_mount FIRST_PAINT dt=%.3f", _t.monotonic() - _m0))

        # SIGUSR2 handler for reload.
        # signal.signal() ensures the signal is always caught (preventing
        # default termination). Inside the handler, call_soon_threadsafe()
        # safely schedules the reload on the asyncio event loop.
        self._reload_loop = asyncio.get_running_loop()
        signal.signal(signal.SIGUSR1, self._handle_sigusr1)
        signal.signal(signal.SIGUSR2, self._handle_sigusr2)

    @work(exclusive=True, group="computers")
    async def _reload_computers(self) -> None:
        """Re-fetch computer list on computer_updated event."""
        try:
            self._computers = await self.api.list_computers()
        except Exception:
            logger.exception("Computer refresh failed")

    @work(exclusive=True, group="refresh")
    async def _refresh_data(self) -> None:
        """Fetch all data and post DataRefreshed.

        Computers are included in the parallel gather so the first load
        doesn't block on sequential list_computers(). After startup,
        computer_updated WS events trigger _reload_computers() separately.
        """
        _r0 = _t.monotonic()
        logger.trace("[PERF] _refresh_data START t=%.3f", _r0)
        try:
            computers, projects_with_todos, sessions, availability, jobs, settings = await asyncio.gather(
                self.api.list_computers(),
                self.api.list_projects_with_todos(),
                self.api.list_sessions(),
                self.api.get_agent_availability(),
                self.api.list_jobs(),
                self.api.get_settings(),
            )
            logger.trace("[PERF] _refresh_data gather done dt=%.3f", _t.monotonic() - _r0)
            self._computers = computers

            # Derive plain projects list from projects_with_todos
            projects = [
                ProjectInfo(
                    computer=p.computer,
                    name=p.name,
                    path=p.path,
                    description=p.description,
                )
                for p in projects_with_todos
            ]

            try:
                tts_enabled = settings.tts.enabled if settings else False
            except Exception:
                tts_enabled = False

            self.post_message(
                DataRefreshed(
                    computers=computers,
                    projects=projects,
                    projects_with_todos=projects_with_todos,
                    sessions=sessions,
                    availability=availability,
                    jobs=jobs,
                    tts_enabled=tts_enabled,
                )
            )
        except Exception:
            logger.exception("Data refresh failed")

    def on_data_refreshed(self, message: DataRefreshed) -> None:
        """Handle refreshed data — update all views."""
        _d0 = _t.monotonic()
        logger.trace("[PERF] on_data_refreshed START t=%.3f", _d0)
        sessions_view = self.query_one("#sessions-view", SessionsView)
        prep_view = self.query_one("#preparation-view", PreparationView)
        jobs_view = self.query_one("#jobs-view", JobsView)
        status_bar = self.query_one("#telec-footer", TelecFooter)

        sessions_view.update_data(
            computers=message.computers,
            projects=message.projects,
            sessions=message.sessions,
            availability=message.availability,
        )
        prep_view.update_data(message.projects_with_todos, availability=message.availability)
        jobs_view.update_data(message.jobs)
        status_bar.update_availability(message.availability)
        status_bar.tts_enabled = message.tts_enabled

        logger.trace("[PERF] on_data_refreshed views updated dt=%.3f", _t.monotonic() - _d0)

        # Update session status cache
        self._session_status_cache = {s.session_id: s.status for s in message.sessions}

        # Forward to pane bridge (sibling — messages don't reach it via bubbling).
        # Sync bridge state from sessions view first so seed_for_reload() has
        # correct active/sticky IDs on SIGUSR2 reload.
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge._preview_session_id = sessions_view.preview_session_id
        pane_bridge._sticky_session_ids = sessions_view._sticky_session_ids.copy()
        pane_bridge.on_data_refreshed(message)

        # On first data load, apply layout with persisted preview/sticky state.
        # After that, layout changes are driven only by user actions
        # (PreviewChanged/StickyChanged messages) to prevent focus hijacking.
        # On reload, _initial_layout_applied is already True — panes survive
        # via seed_for_reload() called from bridge.on_data_refreshed().
        if not self._initial_layout_applied:
            self._initial_layout_applied = True
            if sessions_view.preview_session_id or sessions_view._sticky_session_ids:
                pane_bridge.on_preview_changed(PreviewChanged(sessions_view.preview_session_id))
                if sessions_view._sticky_session_ids:
                    pane_bridge.on_sticky_changed(StickyChanged(sessions_view._sticky_session_ids.copy()))
            self._update_banner_compactness(len(sessions_view._sticky_session_ids))

    # --- Pane manager message forwarding ---
    # Textual messages bubble UP through ancestors, not sideways to siblings.
    # PaneManagerBridge is a sibling of TabbedContent, so it never receives
    # messages posted by SessionsView. We forward them here.

    def on_preview_changed(self, message: PreviewChanged) -> None:
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.on_preview_changed(message)

    def on_sticky_changed(self, message: StickyChanged) -> None:
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.on_sticky_changed(message)
        self._update_banner_compactness(len(message.session_ids))

    def on_state_changed(self, _message: StateChanged) -> None:
        self._schedule_state_save()

    def on_focus_pane_request(self, message: FocusPaneRequest) -> None:
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.on_focus_pane_request(message)

    def on_doc_preview_request(self, message: DocPreviewRequest) -> None:
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.on_doc_preview_request(message)

    def on_doc_edit_request(self, message: DocEditRequest) -> None:
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.on_doc_edit_request(message)

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
            projects_with_todos = [
                ProjectWithTodosInfo(
                    computer=p.computer,
                    name=p.name,
                    path=p.path,
                    description=p.description,
                    todos=getattr(p, "todos", []),
                )
                for p in event.data.projects
            ]
            prep_view.update_data(projects_with_todos)

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
                    canonical_type=event.canonical_type,
                    tool_name=event.tool_name,
                    tool_preview=event.tool_preview,
                    summary=event.summary,
                    timestamp=event.timestamp,
                )
            )

        elif isinstance(event, SessionClosedEvent):
            self.post_message(SessionClosed(event.data.session_id))
            self._session_status_cache.pop(event.data.session_id, None)

        elif isinstance(event, SessionLifecycleStatusEvent):
            # Surface stall and error transitions as TUI notifications.
            if event.status in ("stalled", "error"):
                self.notify(f"Session {event.session_id[:8]}: {event.status}", severity="warning")

        elif isinstance(event, ErrorEvent):
            self.notify(event.data.message, severity="error")

        else:
            if event.event == "computer_updated":
                self._reload_computers()
            self._refresh_data()

    # --- Message handlers for WS-generated messages ---

    def on_session_started(self, message: SessionStarted) -> None:
        session = message.session
        if session.active_agent:
            self._session_agents[session.session_id] = session.active_agent
        # Auto-select new user-initiated sessions (not AI-delegated children)
        if not session.initiator_session_id:
            sessions_view = self.query_one("#sessions-view", SessionsView)
            sessions_view.request_select_session(session.session_id)
        # Trigger full data refresh so tree rebuilds
        self._refresh_data()

    def on_session_updated(self, message: SessionUpdated) -> None:
        session = message.session
        if session.active_agent:
            self._session_agents[session.session_id] = session.active_agent
        sessions_view = self.query_one("#sessions-view", SessionsView)
        sessions_view.update_session(session)
        # Session may now have a tmux pane — try pending auto-select
        sessions_view._apply_pending_selection()

    def on_session_closed(self, message: SessionClosed) -> None:
        self._session_agents.pop(message.session_id, None)
        self._refresh_data()

    def on_agent_activity(self, message: AgentActivity) -> None:
        sessions_view = self.query_one("#sessions-view", SessionsView)
        canonical = message.canonical_type
        logger.debug(
            "tui lane: on_agent_activity lane=tui canonical_type=%s session=%s",
            canonical,
            message.session_id[:8] if message.session_id else "",
            extra={"lane": "tui", "canonical_type": canonical, "session_id": message.session_id},
        )
        if canonical is None:
            logger.warning(
                "tui lane: AgentActivity missing canonical_type lane=tui hook_type=%s session=%s",
                message.activity_type,
                message.session_id[:8] if message.session_id else "",
            )
            return
        if canonical == "user_prompt_submit":
            sessions_view.clear_active_tool(message.session_id)
            sessions_view.set_input_highlight(message.session_id)
        elif canonical == "agent_output_stop":
            sessions_view.clear_active_tool(message.session_id)
            sessions_view.set_output_highlight(message.session_id, message.summary or "")
        elif canonical == "agent_output_update":
            if message.tool_name:
                preview = message.tool_preview or ""
                if preview.startswith(message.tool_name):
                    preview = preview[len(message.tool_name) :].lstrip()
                tool_info = f"{message.tool_name}: {preview}" if preview else message.tool_name
                sessions_view.set_active_tool(message.session_id, tool_info)
            else:
                sessions_view.clear_active_tool(message.session_id)

        # Feed agent activity to animation trigger (both banner and logo targets)
        if self._activity_trigger is not None:
            from teleclaude.cli.tui.animation_triggers import ActivityTrigger

            if isinstance(self._activity_trigger, ActivityTrigger):
                agent = self._session_agents.get(message.session_id)
                if not agent:
                    self.notify(
                        f"Activity for session {message.session_id[:8]} with no cached agent",
                        severity="error",
                    )
                    return
                self._activity_trigger.on_agent_activity(agent, is_big=True)
                self._activity_trigger.on_agent_activity(agent, is_big=False)

    # --- Action handlers for user-initiated actions ---

    @work(exclusive=True, group="session-action")
    async def on_create_session_request(self, message: CreateSessionRequest) -> None:
        if not message.agent:
            self.notify("CreateSessionRequest has no agent", severity="error")
            return
        try:
            await self.api.create_session(
                computer=message.computer,
                project_path=message.project_path,
                agent=message.agent,
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
    async def on_revive_session_request(self, message: ReviveSessionRequest) -> None:
        """Revive a headless session by sending Enter key."""
        try:
            await self.api.send_keys(
                session_id=message.session_id,
                computer=message.computer,
                key="enter",
                count=1,
            )
            self.notify("Reviving headless session...")
            # Refresh after a delay to pick up the new tmux pane
            await asyncio.sleep(2)
            self._refresh_data()
        except Exception as e:
            self.notify(f"Failed to revive session: {e}", severity="error")

    @work(exclusive=True, group="session-action")
    async def on_restart_session_request(self, message: RestartSessionRequest) -> None:
        try:
            await self.api.agent_restart(message.session_id)
            self.notify("Restarting agent...")
        except Exception as e:
            self.notify(f"Failed to restart session: {e}", severity="error")

    @work(exclusive=True, group="session-action")
    async def on_restart_sessions_request(self, message: RestartSessionsRequest) -> None:
        failures = 0
        for session_id in message.session_ids:
            try:
                await self.api.agent_restart(session_id)
            except Exception:
                failures += 1
                logger.exception("Failed to restart session %s", session_id)

        if failures:
            self.notify(
                f"Restarted {len(message.session_ids) - failures}/{len(message.session_ids)} sessions",
                severity="warning",
            )
        else:
            self.notify(f"Restarted {len(message.session_ids)} sessions on {message.computer}")

    async def on_settings_changed(self, message: SettingsChanged) -> None:
        key = message.key
        if key == "pane_theming_mode":
            self.action_cycle_pane_theming()
        elif key == "tts_enabled":
            self._toggle_tts()
        elif key == "animation_mode":
            self._cycle_animation(str(message.value))
        elif key == "agent_status":
            # Handle agent pill clicks: cycle available → degraded → unavailable → available
            if isinstance(message.value, dict):
                agent = str(message.value.get("agent", ""))
                status_bar = self.query_one("#telec-footer", TelecFooter)
                current_info = status_bar._agent_availability.get(agent)

                # Determine next status
                if current_info:
                    current_status = current_info.status or "available"
                    if current_status == "available":
                        next_status = "degraded"
                    elif current_status == "degraded":
                        next_status = "unavailable"
                    else:
                        next_status = "available"
                else:
                    next_status = "degraded"

                try:
                    updated_info = await self.api.set_agent_status(
                        agent, next_status, reason="manual", duration_minutes=60
                    )
                    status_bar._agent_availability[agent] = updated_info
                    status_bar.refresh()
                except Exception as e:
                    self.notify(f"Failed to set agent status: {e}", severity="error")
        elif key.startswith("run_job:"):
            job_name = key.split(":", 1)[1]
            try:
                await self.api.run_job(job_name)
                self.notify(f"Job '{job_name}' started")
            except Exception as e:
                self.notify(f"Failed to run job: {e}", severity="error")

    # --- Tab switching ---

    def action_switch_tab(self, tab_id: str) -> None:
        _sw0 = _t.monotonic()
        logger.trace("[PERF] action_switch_tab(%s) START t=%.3f", tab_id, _sw0)
        tabs = self.query_one("#main-tabs", TabbedContent)
        old_tab = tabs.active
        tabs.active = tab_id
        box_tabs = self.query_one("#box-tab-bar", BoxTabBar)
        box_tabs.active_tab = tab_id
        self._focus_active_view(tab_id)
        if old_tab != tab_id:
            self.post_message(StateChanged())
        self.call_after_refresh(
            lambda: logger.trace("[PERF] action_switch_tab(%s) PAINTED dt=%.3f", tab_id, _t.monotonic() - _sw0)
        )

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        tab_id = event.pane.id or "sessions"
        logger.trace("[PERF] tab_activated(%s) t=%.3f", tab_id, _t.monotonic())
        box_tabs = self.query_one("#box-tab-bar", BoxTabBar)
        box_tabs.active_tab = tab_id
        self._focus_active_view(tab_id)
        self.post_message(StateChanged())

    def on_box_tab_bar_tab_clicked(self, message: BoxTabBar.TabClicked) -> None:
        """Handle click on custom tab bar."""
        self.action_switch_tab(message.tab_id)

    def _focus_active_view(self, tab_id: str) -> None:
        """Focus the view widget inside the active tab so key bindings work."""
        view_map = {
            "sessions": "#sessions-view",
            "preparation": "#preparation-view",
            "jobs": "#jobs-view",
            "config": "#config-view",
        }
        selector = view_map.get(tab_id)
        if selector:
            try:
                view = self.query_one(selector)
                view.focus()
            except Exception:
                pass

    def _apply_app_theme_for_mode(self, pane_theming_mode: str) -> None:
        from teleclaude.cli.tui import theme

        try:
            level = get_pane_theming_mode_level(pane_theming_mode)
        except ValueError:
            level = get_pane_theming_mode_level()
        is_agent = level in (1, 3, 4)
        is_dark = theme.is_dark_mode()
        if is_dark:
            self.theme = "teleclaude-dark-agent" if is_agent else "teleclaude-dark"
        else:
            self.theme = "teleclaude-light-agent" if is_agent else "teleclaude-light"

    # --- Pane theming ---

    def action_cycle_pane_theming(self) -> None:
        from teleclaude.cli.tui import theme
        from teleclaude.cli.tui.widgets.session_row import SessionRow
        from teleclaude.cli.tui.widgets.todo_row import TodoRow

        current_level = theme.get_pane_theming_mode_level()
        next_level = (current_level + 1) % 5
        mode = theme.get_pane_theming_mode_from_level(next_level)
        theme.set_pane_theming_mode(mode)

        # Switch app theme based on new level (Peaceful=0/2 -> Neutral, Agent=1/3/4 -> Warm)
        self._apply_app_theme_for_mode(mode)

        status_bar = self.query_one("#telec-footer", TelecFooter)
        status_bar.pane_theming_mode = mode
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.reapply_colors()
        # Refresh theme-dependent widgets (agent vs peaceful colors)
        for widget in self.query(SessionRow):
            widget.refresh()
        for widget in self.query(TodoRow):
            widget.refresh()

    # --- TTS toggle ---

    @work(exclusive=True, group="settings")
    async def _toggle_tts(self) -> None:
        """Toggle TTS on/off via API."""
        from teleclaude.cli.models import SettingsPatchInfo, TTSSettingsPatchInfo

        new_val = not self.query_one("#telec-footer", TelecFooter).tts_enabled
        try:
            await self.api.patch_settings(SettingsPatchInfo(tts=TTSSettingsPatchInfo(enabled=new_val)))
            status_bar = self.query_one("#telec-footer", TelecFooter)
            status_bar.tts_enabled = new_val
        except Exception as e:
            self.notify(f"Failed to toggle TTS: {e}", severity="error")

    # --- Banner compactness ---

    def _update_banner_compactness(self, num_stickies: int) -> None:
        """Switch between full banner (6-line) and compact logo (3-line).

        Uses sticky count (not preview) to avoid flickering on every click.
        Compact at 4 or 6 total panes (2x2 and 3x2 grids) where the TUI
        pane is small enough that vertical space matters.
        """
        banner_panes = 1 + num_stickies  # TUI + stickies (preview excluded)
        is_compact = banner_panes in (4, 6)
        try:
            self.query_one(Banner).is_compact = is_compact
        except Exception:
            pass

    # --- Animation management ---

    def _start_animation_mode(self, mode: str) -> None:
        """Configure animation engine and triggers for the given mode."""
        self._stop_animation()

        if mode == "off":
            return

        from teleclaude.cli.tui.animation_triggers import ActivityTrigger, PeriodicTrigger

        self._animation_engine.is_enabled = True

        if mode in ("periodic", "party"):
            interval = 10 if mode == "party" else 60
            trigger = PeriodicTrigger(self._animation_engine, interval_sec=interval)
            trigger.task = asyncio.ensure_future(trigger.start())
            self._periodic_trigger = trigger

        if mode == "party":
            self._activity_trigger = ActivityTrigger(self._animation_engine)

        # Start the render tick timer (~150ms)
        self._animation_timer = self.set_interval(0.15, self._animation_tick)

    def _stop_animation(self) -> None:
        """Stop engine, triggers, and render timer."""
        from teleclaude.cli.tui.animation_triggers import PeriodicTrigger

        if isinstance(self._periodic_trigger, PeriodicTrigger):
            self._periodic_trigger.stop()
        self._periodic_trigger = None
        self._activity_trigger = None

        self._animation_engine.stop()
        self._animation_engine.is_enabled = False

        timer = self._animation_timer
        if timer is not None and hasattr(timer, "stop"):
            timer.stop()  # type: ignore[union-attr]
        self._animation_timer = None

        # Clear any lingering animation colors from the banner
        try:
            self.query_one(Banner).refresh()
        except Exception:
            pass

    def _animation_tick(self) -> None:
        """Periodic tick: advance engine and refresh banner if frame changed."""
        if self._animation_engine.update():
            try:
                self.query_one(Banner).refresh()
            except Exception:
                pass

    def _cycle_animation(self, new_mode: str) -> None:
        """Set animation mode, reconfigure engine, and update status bar."""
        self._start_animation_mode(new_mode)
        status_bar = self.query_one("#telec-footer", TelecFooter)
        status_bar.animation_mode = new_mode

    # --- Refresh ---

    def action_refresh(self) -> None:
        self._refresh_data()

    # --- State persistence ---

    def _schedule_state_save(self) -> None:
        timer = self._state_save_timer
        if timer is not None and hasattr(timer, "stop"):
            timer.stop()  # type: ignore[union-attr]
        self._state_save_timer = self.set_timer(0.5, self._flush_state_save)

    def _cancel_state_save_timer(self) -> None:
        timer = self._state_save_timer
        if timer is not None and hasattr(timer, "stop"):
            timer.stop()  # type: ignore[union-attr]
        self._state_save_timer = None

    def _flush_state_save(self) -> None:
        self._state_save_timer = None
        self._save_state_sync()

    def _collect_persisted_state(self) -> dict[str, object]:  # guard: loose-dict - namespaced widget payloads
        state: dict[str, object] = {}  # guard: loose-dict - namespaced widget payloads
        for widget in self.query("*"):
            if not isinstance(widget, Persistable):
                continue
            state[get_persistence_key(widget)] = widget.get_persisted_state()

        tabs = self.query_one("#main-tabs", TabbedContent)
        state["app"] = {"active_tab": tabs.active or "sessions"}
        return state

    def _save_state_sync(self) -> None:
        save_state(self._collect_persisted_state())

    # --- Signal handlers ---

    def _handle_sigusr1(self, _signum: int, _frame: object) -> None:
        """Catch SIGUSR1 (appearance change) and schedule hot theme swap.

        Sent by ~/Sync/dotfiles appearance.py when OS dark/light mode changes.
        Lightweight: re-detects mode, switches Textual theme, refreshes widgets.
        """
        self._reload_loop.call_soon_threadsafe(self._appearance_refresh)

    def _appearance_refresh(self) -> None:
        """Hot-swap dark/light theme without restarting the process."""
        from teleclaude.cli.tui import theme
        from teleclaude.cli.tui.widgets.session_row import SessionRow
        from teleclaude.cli.tui.widgets.todo_row import TodoRow

        theme.refresh_mode()

        level = get_pane_theming_mode_level()
        is_agent = level in (1, 3, 4)
        is_dark = theme.is_dark_mode()
        if is_dark:
            self.theme = "teleclaude-dark-agent" if is_agent else "teleclaude-dark"
        else:
            self.theme = "teleclaude-light-agent" if is_agent else "teleclaude-light"

        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.reapply_colors()
        for widget in self.query(SessionRow):
            widget.refresh()
        for widget in self.query(TodoRow):
            widget.refresh()

    def _handle_sigusr2(self, _signum: int, _frame: object) -> None:
        """Catch SIGUSR2 (code change) and schedule full process restart."""
        self._reload_loop.call_soon_threadsafe(self._sigusr2_reload)

    def _sigusr2_reload(self) -> None:
        """Save state and exit for full process restart.

        Python modules are cached in memory — refreshing CSS and data
        doesn't pick up code changes. The outer _run_tui() loop detects
        RELOAD_EXIT and re-execs the process.
        """
        self._cancel_state_save_timer()
        self._save_state_sync()
        self.exit(result=RELOAD_EXIT)

    # --- Lifecycle ---

    async def action_quit(self) -> None:
        self._stop_animation()
        self._cancel_state_save_timer()
        self._save_state_sync()
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.cleanup()
        await self.api.close()
        self.exit()
