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
    ChiptunesStateEvent,
    ChiptunesStatusInfo,
    ChiptunesTrackEvent,
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
    get_terminal_background,
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
    from teleclaude.cli.tui.animations.base import Animation

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
        Binding("q", "quit", "Quit", key_display="q"),
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
        Binding("t", "cycle_pane_theming", "Cycle Theme", key_display="t"),
        Binding("a", "cycle_animation", "Cycle Anim", key_display="a"),
        Binding("u", "spawn_ufo", "UFO", key_display="u", show=False),
        Binding("c", "spawn_car", "Car", key_display="c", show=False),
        Binding("v", "toggle_tts", "Voice", key_display="v"),
        Binding("m", "chiptunes_play_pause", "Music", key_display="m"),
        Binding("escape", "clear_layout", "Clear", key_display="Esc"),
    ]

    def __init__(
        self,
        api: TelecAPIClient,
        start_view: int = 1,
        config_guided: bool = False,
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
        self._config_guided = config_guided
        self._state_save_timer: object | None = None
        self._computers: list[ComputerInfo] = []
        self._session_agents: dict[str, str] = {}
        self._chiptunes_state_version: int = -1
        # On SIGUSR2 reload, panes already exist — the bridge's on_data_refreshed
        # will call seed_for_reload() to map them.  Skip layout re-application
        # on the first data refresh to avoid killing and recreating panes.
        self._is_reload = bool(os.environ.pop("TELEC_RELOAD", ""))
        self._initial_layout_applied = self._is_reload
        # Animation engine and triggers
        from teleclaude.cli.tui.animation_engine import AnimationEngine

        self._animation_engine = AnimationEngine()
        self._animation_engine.on_animation_start = self._show_animation_toast
        self._periodic_trigger: object | None = None
        self._activity_trigger: object | None = None
        self._animation_timer: object | None = None
        self._animation_requested_mode: str = "off"

    def get_css_variables(self) -> dict[str, str]:
        """Override CSS variables to inject the correct background for focus state.

        Textual emits explicit ANSI backgrounds for every cell, so tmux's
        window-style cannot apply its inactive haze. We swap $background
        at the CSS variable level so ALL widgets pick up the correct color.

        We also bypass the frozen Theme.background (baked at import time) so
        that dark/light mode switches via SIGUSR1 correctly re-read the fresh
        terminal background after refresh_mode() clears the cache.
        """
        variables = super().get_css_variables()
        if self.app_focus:
            bg = get_terminal_background()
            variables["background"] = bg
            variables["scrollbar-background"] = bg
        else:
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
        from teleclaude.cli.tui import theme
        from teleclaude.cli.tui.widgets.session_row import SessionRow
        from teleclaude.cli.tui.widgets.todo_row import TodoRow

        theme.set_tui_focused(focus)
        self._refresh_focus_sensitive_widgets(SessionRow, TodoRow)

    def _refresh_focus_sensitive_widgets(self, SessionRow: type[object], TodoRow: type[object]) -> None:
        """Refresh widgets whose colors depend on the current haze state."""
        self.refresh_css(animate=False)

        # Force full Screen repaint so $background change reaches all content
        self.screen.refresh()

        # Refresh Rich-based widgets that use haze-dependent rendering
        for widget in self.query(Banner):
            widget.refresh()
        for widget in self.query(BoxTabBar):
            widget.refresh()
        for widget in self.query(SessionRow):
            widget.refresh()
        for widget in self.query(TodoRow):
            widget.refresh()

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

        # Remove Textual's internal tab bar (ContentTabs) — we use BoxTabBar instead.
        # CSS `display: none` on Tabs doesn't fully suppress the docked ContentTabs
        # in TabbedContent's DEFAULT_CSS (`dock: top`), leaving a 1-row gap.
        from textual.widgets._tabbed_content import ContentTabs

        for ct in self.query(ContentTabs):
            ct.display = False

        # Wire animation engine to banner and tabs
        banner = self.query_one(Banner)
        banner.animation_engine = self._animation_engine
        try:
            tabs = self.query_one(BoxTabBar)
            tabs.animation_engine = self._animation_engine
        except Exception:
            pass  # Tab bar might not be mounted in some modes

        self._animation_requested_mode = status_bar.animation_mode
        self._apply_animation_runtime()

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
            on_connect=self._on_ws_connected,
        )

        logger.trace("[PERF] on_mount api+ws done dt=%.3f", _t.monotonic() - _m0)

        # Initial data load (computers loaded in parallel inside _refresh_data)
        self._refresh_data()
        self.call_after_refresh(lambda: logger.trace("[PERF] on_mount FIRST_PAINT dt=%.3f", _t.monotonic() - _m0))

        # Activate guided mode if launched as config wizard
        if self._config_guided:
            self.call_after_refresh(self._activate_config_guided_mode)

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

            try:
                chiptunes_status = await self.api.get_chiptunes_status()
            except Exception:
                logger.debug("ChipTunes status refresh failed", exc_info=True)
                chiptunes_status = None

            self.post_message(
                DataRefreshed(
                    computers=computers,
                    projects=projects,
                    projects_with_todos=projects_with_todos,
                    sessions=sessions,
                    availability=availability,
                    jobs=jobs,
                    tts_enabled=tts_enabled,
                    chiptunes_loaded=bool(getattr(chiptunes_status, "loaded", False)) if chiptunes_status else False,
                    chiptunes_playback=str(getattr(chiptunes_status, "playback", "cold"))
                    if chiptunes_status
                    else "cold",
                    chiptunes_state_version=int(getattr(chiptunes_status, "state_version", 0))
                    if chiptunes_status
                    else 0,
                    chiptunes_playing=chiptunes_status.playing if chiptunes_status else False,
                    chiptunes_track=chiptunes_status.track if chiptunes_status else "",
                    chiptunes_sid_path=chiptunes_status.sid_path if chiptunes_status else "",
                    chiptunes_pending_command_id=str(getattr(chiptunes_status, "pending_command_id", ""))
                    if chiptunes_status
                    else "",
                    chiptunes_pending_action=str(getattr(chiptunes_status, "pending_action", ""))
                    if chiptunes_status
                    else "",
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
        self._apply_chiptunes_footer_state(
            loaded=message.chiptunes_loaded,
            playback=message.chiptunes_playback,
            state_version=message.chiptunes_state_version,
            playing=message.chiptunes_playing,
            track=message.chiptunes_track,
            sid_path=message.chiptunes_sid_path,
            pending_command_id=message.chiptunes_pending_command_id,
            pending_action=message.chiptunes_pending_action,
        )

        logger.trace("[PERF] on_data_refreshed views updated dt=%.3f", _t.monotonic() - _d0)

        # Forward to pane bridge (sibling — messages don't reach it via bubbling).
        # Sync bridge state from sessions view on initial load so seed_for_reload()
        # has correct IDs before _apply() has been called.  After the first load,
        # layout state is owned exclusively by StickyChanged/PreviewChanged messages;
        # writing directly here would bypass _apply() and diverge pane_manager state.
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        if not self._initial_layout_applied:
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
        # Pane layout change → tmux split → celestials need repositioning
        self.set_timer(0.5, self._invalidate_sky_width)

    def on_sticky_changed(self, message: StickyChanged) -> None:
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.on_sticky_changed(message)
        self._update_banner_compactness(len(message.session_ids))
        # Pane layout change → tmux split → celestials need repositioning
        self.set_timer(0.5, self._invalidate_sky_width)

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

    def action_clear_layout(self) -> None:
        """Global ESC: tear down all preview, sticky, and doc panes."""
        sessions_view = self.query_one("#sessions-view", SessionsView)
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        had_preview = sessions_view.preview_session_id is not None
        had_sticky = bool(sessions_view._sticky_session_ids)
        had_doc = pane_bridge._active_doc_preview is not None
        if not had_preview and not had_sticky and not had_doc:
            return
        if had_preview:
            sessions_view.preview_session_id = None
            self.post_message(PreviewChanged(None, request_focus=False))
        if had_sticky:
            from teleclaude.cli.tui.views.sessions import SessionRow

            sessions_view._sticky_session_ids.clear()
            for widget in sessions_view._nav_items:
                if isinstance(widget, SessionRow):
                    widget.is_sticky = False
            self.post_message(StickyChanged([]))
        if had_doc:
            pane_bridge._set_preview(focus=False)
        sessions_view._notify_state_changed()

    # --- WebSocket event handling ---

    def _on_ws_event(self, event: WsEvent) -> None:
        """Handle WebSocket event from background thread — safe handoff to Textual."""
        self.call_from_thread(self._handle_ws_event, event)

    def _on_ws_connected(self) -> None:
        """Handle websocket reconnect from the background thread."""
        self.call_from_thread(self._handle_ws_connected)

    def _handle_ws_connected(self) -> None:
        """Refresh authoritative state after websocket (re)connect."""
        self._refresh_data()

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

        elif isinstance(event, SessionUpdatedEvent):
            session = event.data
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

        elif isinstance(event, SessionLifecycleStatusEvent):
            # Surface stall and error transitions as TUI notifications.
            if event.status in ("stalled", "error"):
                if event.reason == "close_failed":
                    self.notify(f"Session {event.session_id} failed to close", severity="error")
                    self._refresh_data()
                else:
                    self.notify(f"Session {event.session_id}: {event.status}", severity="warning")

        elif isinstance(event, ErrorEvent):
            self.notify(event.data.message, severity="error")

        elif isinstance(event, ChiptunesTrackEvent):
            self._apply_chiptunes_footer_state(
                loaded=True,
                playback="playing",
                state_version=None,
                playing=True,
                track=event.track,
                sid_path=event.sid_path,
                pending_command_id="",
                pending_action="",
            )
            if event.track:
                self.notify(f"♪ Now Playing: {event.track}", timeout=4)

        elif isinstance(event, ChiptunesStateEvent):
            self._apply_chiptunes_footer_state(
                loaded=event.loaded,
                playback=event.playback,
                state_version=event.state_version,
                playing=event.playing,
                track=event.track,
                sid_path=event.sid_path,
                pending_command_id=event.pending_command_id,
                pending_action=event.pending_action,
            )

        else:
            if event.event == "computer_updated":
                self._reload_computers()
            self._refresh_data()

    # --- Message handlers for WS-generated messages ---

    def on_session_started(self, message: SessionStarted) -> None:
        session = message.session
        if session.active_agent:
            self._session_agents[session.session_id] = session.active_agent
        # Auto-select new user-initiated sessions only while Sessions tab is active.
        # Otherwise this steals focus from Preparation/other tabs.
        if not session.initiator_session_id:
            tabs = self.query_one("#main-tabs", TabbedContent)
            if tabs.active == "sessions":
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
        sessions_view = self.query_one("#sessions-view", SessionsView)
        sessions_view.confirm_session_closed(message.session_id)
        self._refresh_data()

    def on_agent_activity(self, message: AgentActivity) -> None:
        sessions_view = self.query_one("#sessions-view", SessionsView)
        hook = message.activity_type
        logger.debug(
            "tui lane: on_agent_activity lane=tui hook=%s session=%s",
            hook,
            message.session_id if message.session_id else "",
            extra={"lane": "tui", "hook": hook, "session_id": message.session_id},
        )
        if message.canonical_type is None:
            logger.warning(
                "tui lane: AgentActivity missing canonical_type lane=tui hook_type=%s session=%s",
                hook,
                message.session_id if message.session_id else "",
                extra={"lane": "tui", "canonical_type": None, "session_id": message.session_id},
            )
            return

        sid = message.session_id

        if hook == "user_prompt_submit":
            sessions_view.update_activity(sid, "user_prompt_submit")
            sessions_view.set_input_highlight(sid)

        elif hook == "tool_use":
            tool_info = ""
            if message.tool_name:
                preview = message.tool_preview or ""
                if preview.startswith(message.tool_name):
                    preview = preview[len(message.tool_name) :].lstrip()
                tool_info = f"{message.tool_name}: {preview}" if preview else message.tool_name
            sessions_view.update_activity(sid, "tool_use", tool_info)

        elif hook == "tool_done":
            sessions_view.update_activity(sid, "tool_done")

        elif hook == "agent_stop":
            sessions_view.update_activity(sid, "agent_stop", message.summary or "")
            sessions_view.set_output_highlight(sid, message.summary or "")
            # Animation trigger
            if self._activity_trigger is not None:
                from teleclaude.cli.tui.animation_triggers import ActivityTrigger

                if isinstance(self._activity_trigger, ActivityTrigger):
                    agent = self._session_agents.get(sid)
                    if agent:
                        self._activity_trigger.on_agent_activity(agent, is_big=True)
                        self._activity_trigger.on_agent_activity(agent, is_big=False)

        else:
            logger.debug("tui lane: unhandled hook %r", hook)

    # --- Action handlers for user-initiated actions ---

    @work(exclusive=True, group="session-action")
    async def on_create_session_request(self, message: CreateSessionRequest) -> None:
        # Revive by TeleClaude session ID
        if message.revive_session_id:
            try:
                result = await self.api.revive_session(message.revive_session_id)
                if result.status == "success":
                    self.notify(f"Revived session {message.revive_session_id}...")
                else:
                    self.notify(result.error or "Revive failed", severity="error")
            except Exception as e:
                self.notify(f"Failed to revive session: {e}", severity="error")
            return

        if not message.agent:
            self.notify("CreateSessionRequest has no agent", severity="error")
            return

        # Resume by native session ID
        if message.native_session_id:
            auto_command = f"agent_resume {message.agent} {message.native_session_id}"
            try:
                await self.api.create_session(
                    computer=message.computer,
                    project_path=message.project_path,
                    agent=message.agent,
                    thinking_mode=message.thinking_mode or "slow",
                    auto_command=auto_command,
                )
                self.notify("Resuming session...")
            except Exception as e:
                self.notify(f"Failed to resume session: {e}", severity="error")
            return

        # Normal new session
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
            ended = await self.api.end_session(message.session_id, message.computer)
            if ended:
                sessions_view = self.query_one("#sessions-view", SessionsView)
                sessions_view.optimistically_hide_session(message.session_id)
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
        elif key == "chiptunes_play_pause":
            self._chiptunes_play_pause()
        elif key == "chiptunes_next":
            self._chiptunes_next()
        elif key == "chiptunes_prev":
            self._chiptunes_prev()
        elif key == "chiptunes_favorite":
            self._chiptunes_favorite()
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
        # Ignore stale activations (e.g. initial default-tab activation arriving
        # after we've already switched tabs).
        tabs = self.query_one("#main-tabs", TabbedContent)
        if tabs.active != tab_id:
            return
        try:
            box_tabs = self.query_one("#box-tab-bar", BoxTabBar)
        except Exception:
            # Late activation can arrive while the app is tearing down.
            return
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

    # --- Animation and TTS keyboard actions ---

    def action_cycle_animation(self) -> None:
        """a: cycle animation mode (off → periodic → party → off)."""
        cycle = ["off", "periodic", "party"]
        status_bar = self.query_one("#telec-footer", TelecFooter)
        idx = cycle.index(status_bar.animation_mode) if status_bar.animation_mode in cycle else 0
        new_mode = cycle[(idx + 1) % len(cycle)]
        self._cycle_animation(new_mode)

    def _force_spawn_sky(self, sprite: object | None = None) -> None:
        """Force-spawn a sky entity (or random if sprite is None)."""
        from teleclaude.cli.tui.animations.general import GlobalSky

        slot = self._animation_engine._targets.get("header")
        if slot and isinstance(slot.animation, GlobalSky):
            slot.animation.force_spawn(sprite)

    def action_spawn_ufo(self) -> None:
        """u: force a UFO to spawn in the sky animation."""
        from teleclaude.cli.tui.animations.sprites.ufo import UFO_SPRITE

        self._force_spawn_sky(UFO_SPRITE)

    def action_spawn_car(self) -> None:
        """c: force a car to spawn in the sky animation."""
        from teleclaude.cli.tui.animations.sprites.cars import CAR_SPRITE

        self._force_spawn_sky(CAR_SPRITE)

    def action_toggle_tts(self) -> None:
        """v: toggle TTS on/off.

        Key choice: 's' was considered but conflicts irreconcilably with
        PreparationView's 'start_work' binding enabled on all todo/project/file
        nodes. 'v' (Voice) is used instead.
        """
        self._toggle_tts()

    def action_chiptunes_play_pause(self) -> None:
        """m: play/pause ChipTunes."""
        self._chiptunes_play_pause()

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

    # --- ChipTunes player controls ---

    @work(exclusive=False, group="settings")
    async def _chiptunes_play_pause(self) -> None:
        """Play/pause toggle: enable if cold, else pause/resume.

        Uses optimistic local updates for instant visual feedback.
        ChiptunesStateEvent WS broadcasts correct state eventually.
        """
        footer = self.query_one("#telec-footer", TelecFooter)

        if not footer.chiptunes_loaded:
            # Cold start — enable chiptunes via settings patch
            from teleclaude.cli.models import ChiptunesSettingsPatchInfo, SettingsPatchInfo

            try:
                footer.chiptunes_playing = True
                await self.api.patch_settings(SettingsPatchInfo(chiptunes=ChiptunesSettingsPatchInfo(enabled=True)))
            except Exception as e:
                footer.chiptunes_playing = False
                self.notify(f"Failed to enable ChipTunes: {e}", severity="error")
            return

        # Sync fresh state from daemon before deciding pause vs resume
        try:
            await self._sync_chiptunes_footer_state()
        except Exception:
            pass  # proceed with cached state if sync fails
        try:
            if footer.chiptunes_playing:
                footer.chiptunes_playing = False
                receipt = await self.api.chiptunes_pause()
            else:
                footer.chiptunes_playing = True
                receipt = await self.api.chiptunes_resume()
            self._apply_chiptunes_receipt(receipt.command_id, receipt.action)
            self._schedule_chiptunes_reconcile()
        except Exception as e:
            self.notify(f"Failed to pause/resume: {e}", severity="error")

    @work(exclusive=False, group="settings")
    async def _chiptunes_next(self) -> None:
        """Skip to the next chiptunes track."""
        footer = self.query_one("#telec-footer", TelecFooter)
        if not footer.chiptunes_loaded:
            return
        try:
            receipt = await self.api.chiptunes_next()
            self._apply_chiptunes_receipt(receipt.command_id, receipt.action)
            self._schedule_chiptunes_reconcile()
        except Exception as e:
            self.notify(f"Failed to skip track: {e}", severity="error")

    @work(exclusive=False, group="settings")
    async def _chiptunes_prev(self) -> None:
        """Go back to the previous chiptunes track."""
        footer = self.query_one("#telec-footer", TelecFooter)
        if not footer.chiptunes_loaded:
            return
        try:
            receipt = await self.api.chiptunes_prev()
            self._apply_chiptunes_receipt(receipt.command_id, receipt.action)
            self._schedule_chiptunes_reconcile()
        except Exception as e:
            self.notify(f"Failed to go to previous track: {e}", severity="error")

    def _apply_chiptunes_footer_state(
        self,
        *,
        loaded: bool,
        playback: str,
        state_version: int | None,
        playing: bool,
        track: str,
        sid_path: str,
        pending_command_id: str,
        pending_action: str,
    ) -> None:
        from teleclaude.chiptunes.favorites import is_favorited

        if state_version is not None and state_version < self._chiptunes_state_version:
            return
        if state_version is not None:
            self._chiptunes_state_version = state_version

        footer = self.query_one("#telec-footer", TelecFooter)
        footer.chiptunes_loaded = loaded
        footer.chiptunes_playback = playback
        footer.chiptunes_playing = playing
        footer.chiptunes_track = track
        footer.chiptunes_sid_path = sid_path
        footer.chiptunes_pending_command_id = pending_command_id
        footer.chiptunes_pending_action = pending_action
        footer.chiptunes_favorited = is_favorited(sid_path) if sid_path else False

    def _apply_chiptunes_status(self, status: ChiptunesStatusInfo) -> None:
        self._apply_chiptunes_footer_state(
            loaded=bool(getattr(status, "loaded", False)),
            playback=str(getattr(status, "playback", "cold")),
            state_version=int(getattr(status, "state_version", 0)),
            playing=bool(getattr(status, "playing", False)),
            track=str(getattr(status, "track", "")),
            sid_path=str(getattr(status, "sid_path", "")),
            pending_command_id=str(getattr(status, "pending_command_id", "")),
            pending_action=str(getattr(status, "pending_action", "")),
        )

    def _apply_chiptunes_receipt(self, command_id: str, action: str) -> None:
        footer = self.query_one("#telec-footer", TelecFooter)
        footer.chiptunes_pending_command_id = command_id
        footer.chiptunes_pending_action = action
        if action in {"resume", "next", "prev"}:
            footer.chiptunes_playback = "loading"

    def _schedule_chiptunes_reconcile(self) -> None:
        async def _reconcile() -> None:
            await asyncio.sleep(0.2)
            try:
                await self._sync_chiptunes_footer_state()
            except Exception:
                logger.debug("ChipTunes reconcile sync failed", exc_info=True)

        asyncio.create_task(_reconcile())

    async def _sync_chiptunes_footer_state(self) -> None:
        status = await self.api.get_chiptunes_status()
        self._apply_chiptunes_status(status)

    @work(exclusive=False, group="settings")
    async def _chiptunes_favorite(self) -> None:
        """Toggle the current track in favorites."""
        footer = self.query_one("#telec-footer", TelecFooter)
        if not footer.chiptunes_loaded:
            return
        if not footer.chiptunes_sid_path:
            return
        from teleclaude.chiptunes.favorites import is_favorited, remove_favorite, save_favorite

        sid_path = footer.chiptunes_sid_path
        track = footer.chiptunes_track

        already_favorited = await asyncio.to_thread(is_favorited, sid_path)
        if already_favorited:
            try:
                removed = await asyncio.to_thread(remove_favorite, sid_path)
            except OSError as e:
                self.notify(f"Failed to remove favorite: {e}", severity="error")
                return

            if removed:
                footer.chiptunes_favorited = False
                self.notify("Removed from favorites")
            return

        try:
            await asyncio.to_thread(save_favorite, track, sid_path)
        except OSError as e:
            self.notify(f"Failed to save favorite: {e}", severity="error")
            return

        footer.chiptunes_favorited = True
        self.notify("⭐ Added to favorites")

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
        """Configure ambient sky and banner cadence for the given mode."""
        from teleclaude.cli.tui.animation_triggers import ActivityTrigger, PeriodicTrigger

        self._stop_banner_animation()

        self._animation_engine.is_enabled = True
        self._animation_engine.animation_mode = mode

        self._ensure_header_sky(show_extra_motion=mode != "off")

        if mode in ("periodic", "party"):
            interval = 10 if mode == "party" else 60
            trigger = PeriodicTrigger(self._animation_engine, interval_sec=interval)
            trigger.task = asyncio.ensure_future(trigger.start())
            self._periodic_trigger = trigger

        if mode == "party":
            self._activity_trigger = ActivityTrigger(self._animation_engine)

        if self._animation_timer is None:
            # Start the render tick timer (~250ms — balances smoothness vs terminal output volume)
            self._animation_timer = self.set_interval(0.25, self._animation_tick)

    def _ensure_header_sky(
        self,
        *,
        show_extra_motion: bool,
    ) -> None:
        from teleclaude.cli.tui.animation_colors import palette_registry
        from teleclaude.cli.tui.animation_engine import AnimationPriority
        from teleclaude.cli.tui.animations.general import GlobalSky

        header_slot = self._animation_engine._targets.get("header")
        existing = header_slot.animation if header_slot is not None else None
        if isinstance(existing, GlobalSky):
            existing.set_extra_motion(show_extra_motion)
            existing.animation_mode = self._animation_engine.animation_mode
            self._animation_engine.set_looping("header", True)
            return

        sky = GlobalSky(
            palette=palette_registry.get("spectrum"),
            is_big=True,
            duration_seconds=3600,
            show_extra_motion=show_extra_motion,
        )
        self._animation_engine.play(sky, priority=AnimationPriority.PERIODIC, target="header")
        self._animation_engine.set_looping("header", True)

    def _stop_banner_animation(self) -> None:
        """Stop banner/logo effects while leaving the ambient sky scene intact."""
        from teleclaude.cli.tui.animation_triggers import PeriodicTrigger

        if isinstance(self._periodic_trigger, PeriodicTrigger):
            self._periodic_trigger.stop()
        self._periodic_trigger = None
        self._activity_trigger = None

        self._animation_engine.stop_target("banner")
        self._animation_engine.stop_target("logo")

    def _stop_animation(self) -> None:
        """Stop all animation output, including the ambient sky scene."""
        self._stop_banner_animation()

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

    def _apply_animation_runtime(self) -> None:
        """Apply the selected mode without focus-based or idle-based pausing."""
        self._start_animation_mode(self._animation_requested_mode)

    def _handle_exception(self, error: Exception) -> None:
        """Log unhandled exceptions BEFORE Rich's traceback renderer can crash on them."""
        import traceback as _tb

        logger.error(
            "Unhandled Textual exception",
            error=repr(error),
            traceback="".join(_tb.format_exception(type(error), error, error.__traceback__)),
        )
        try:
            super()._handle_exception(error)
        except Exception:
            logger.exception("Textual _handle_exception crashed (Rich traceback failure) — forcing exit")
            self.exit(1)

    def _animation_tick(self) -> None:
        """Periodic tick: advance engine and refresh banner if frame changed."""
        try:
            changed = self._animation_engine.update()
        except Exception:
            logger.exception("Animation engine tick crashed")
            return
        if changed:
            try:
                self.query_one(Banner).refresh()
                self.query_one(BoxTabBar).refresh()
            except Exception:
                logger.exception("Header refresh failed after animation tick")

    def _cycle_animation(self, new_mode: str) -> None:
        """Set animation mode, reconfigure engine, and update status bar."""
        self._animation_requested_mode = new_mode
        self._apply_animation_runtime()
        status_bar = self.query_one("#telec-footer", TelecFooter)
        status_bar.animation_mode = new_mode

    def _activate_config_guided_mode(self) -> None:
        """Start guided mode in ConfigView after initial mount and data load."""
        from teleclaude.cli.tui.views.config import ConfigView

        try:
            config_view = self.query_one("#config-view", ConfigView)
            config_view.action_toggle_guided_mode()
            config_view.focus()
        except Exception:
            logger.exception("Failed to activate config guided mode")

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

        # Refresh animation engine theme (push dark_mode to running animations)
        if self._animation_engine:
            self._animation_engine.refresh_theme()

        # Refresh Rich-based header widgets (not CSS-driven)
        for widget in self.query(Banner):
            widget.refresh()
        for widget in self.query(BoxTabBar):
            widget.refresh()

        # Refresh config content — its Rich styles depend on dark/light mode
        from teleclaude.cli.tui.views.config import ConfigContent

        for widget in self.query(ConfigContent):
            widget.refresh()

    def on_resize(self, event: object) -> None:
        """Force sky animation to reposition celestials on terminal resize."""
        if self._animation_engine:
            width = getattr(getattr(event, "size", None), "width", None)
            self._animation_engine.invalidate_term_width(width)

    def _invalidate_sky_width(self) -> None:
        """Delayed sky width refresh after pane layout changes."""
        if self._animation_engine:
            self._animation_engine.invalidate_term_width()

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

    def _show_animation_toast(self, target: str, animation: Animation) -> None:
        """No-op — animation toasts disabled."""

    async def action_quit(self) -> None:
        self._stop_animation()
        self._cancel_state_save_timer()
        self._save_state_sync()
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.cleanup()
        await self.api.close()
        self.exit()
