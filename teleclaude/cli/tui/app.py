"""Main TUI application built on Textual."""

from __future__ import annotations

import asyncio
import os
import signal
import time as _t
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import TabbedContent, TabPane
from textual.widgets._tabbed_content import ContentTabs

from teleclaude.cli.api_client import APIError
from teleclaude.cli.models import (
    ComputerInfo,
    ProjectInfo,
)
from teleclaude.cli.tui import theme
from teleclaude.cli.tui.animation_engine import AnimationEngine
from teleclaude.cli.tui.app_actions import TelecAppActionsMixin
from teleclaude.cli.tui.app_media import TelecAppMediaMixin
from teleclaude.cli.tui.app_ws import TelecAppWsMixin
from teleclaude.cli.tui.messages import (
    DataRefreshed,
    DocEditRequest,
    DocPreviewRequest,
    FocusPaneRequest,
    PreviewChanged,
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
    is_dark_mode,
)
from teleclaude.cli.tui.views.config import ConfigContent, ConfigView
from teleclaude.cli.tui.views.jobs import JobsView
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.banner import Banner
from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar
from teleclaude.cli.tui.widgets.telec_footer import TelecFooter

if TYPE_CHECKING:
    from textual.timer import Timer

    from teleclaude.cli.api_client import TelecAPIClient
    from teleclaude.cli.tui.animations.base import Animation

logger = get_logger(__name__)
APP_QUERY_ERRORS = (AttributeError, LookupError, RuntimeError, TypeError, ValueError)
APP_RUNTIME_ERRORS = (APIError, AttributeError, ImportError, LookupError, OSError, RuntimeError, TypeError, ValueError)
APP_DATA_ERRORS = (APIError, AttributeError, OSError, RuntimeError, TypeError, ValueError)
_APP_STATE_FIELDS = {
    "_persisted": ("_init_state", "persisted"),
    "_start_view": ("_init_state", "start_view"),
    "_config_guided": ("_init_state", "config_guided"),
    "_is_reload": ("_init_state", "is_reload"),
    "_initial_layout_applied": ("_init_state", "initial_layout_applied"),
    "_state_save_timer": ("_runtime_state", "state_save_timer"),
    "_computers": ("_runtime_state", "computers"),
    "_session_agents": ("_runtime_state", "session_agents"),
    "_sky_width_timer": ("_runtime_state", "sky_width_timer"),
    "_reload_loop": ("_runtime_state", "reload_loop"),
    "_animation_engine": ("_media_state", "animation_engine"),
    "_periodic_trigger": ("_media_state", "periodic_trigger"),
    "_activity_trigger": ("_media_state", "activity_trigger"),
    "_animation_timer": ("_media_state", "animation_timer"),
    "_animation_requested_mode": ("_media_state", "animation_requested_mode"),
    "_chiptunes_state_version": ("_media_state", "chiptunes_state_version"),
    "_chiptunes_reconcile_task": ("_media_state", "chiptunes_reconcile_task"),
}


# Legacy stub — old configuration.py imports this via TYPE_CHECKING.
# Remove in Phase 4 cleanup.
FocusContext = object


RELOAD_EXIT = "__RELOAD__"


@dataclass
class _AppInitState:
    start_view: int
    config_guided: bool
    persisted: dict[str, dict[str, object]]
    is_reload: bool
    initial_layout_applied: bool


@dataclass
class _AppRuntimeState:
    state_save_timer: object | None = None
    computers: list[ComputerInfo] = field(default_factory=list)
    session_agents: dict[str, str] = field(default_factory=dict)
    sky_width_timer: Timer | None = None
    reload_loop: asyncio.AbstractEventLoop | None = None


@dataclass
class _AppMediaState:
    animation_engine: AnimationEngine = field(default_factory=AnimationEngine)
    periodic_trigger: object | None = None
    activity_trigger: object | None = None
    animation_timer: object | None = None
    animation_requested_mode: str = "off"
    chiptunes_state_version: int = -1
    chiptunes_reconcile_task: asyncio.Task[None] | None = None


class TelecApp(TelecAppWsMixin, TelecAppActionsMixin, TelecAppMediaMixin, App[str | None]):
    """Main TeleClaude TUI application."""

    api: TelecAPIClient
    _persisted: dict[str, dict[str, object]]
    _start_view: int
    _config_guided: bool
    _is_reload: bool
    _initial_layout_applied: bool
    _state_save_timer: Timer | None
    _computers: list[ComputerInfo]
    _session_agents: dict[str, str]
    _sky_width_timer: Timer | None
    _reload_loop: asyncio.AbstractEventLoop | None
    _animation_engine: AnimationEngine
    _periodic_trigger: object | None
    _activity_trigger: object | None
    _animation_timer: object | None
    _animation_requested_mode: str
    _chiptunes_state_version: int
    _chiptunes_reconcile_task: asyncio.Task[None] | None

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

        persisted = load_state()
        persisted_status = persisted.get("status_bar", {})
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
        is_reload = bool(os.environ.pop("TELEC_RELOAD", ""))
        self._init_state = _AppInitState(
            start_view=start_view,
            config_guided=config_guided,
            persisted=persisted,
            is_reload=is_reload,
            initial_layout_applied=is_reload,
        )
        self._runtime_state = _AppRuntimeState()
        self._media_state = _AppMediaState()
        self._sky_width_timer = None
        self._media_state.animation_engine.on_animation_start = self._show_animation_toast

    def __getattr__(self, name: str) -> object:
        """Keep legacy mixin attribute access working via grouped state."""
        state_info = _APP_STATE_FIELDS.get(name)
        if state_info is None:
            raise AttributeError(name)
        state_name, field_name = state_info
        state = object.__getattribute__(self, state_name)
        return getattr(state, field_name)

    def __setattr__(self, name: str, value: object) -> None:
        """Keep legacy mixin attribute writes working via grouped state."""
        state_info = _APP_STATE_FIELDS.get(name)
        if state_info is not None:
            state_name, field_name = state_info
            try:
                state = object.__getattribute__(self, state_name)
            except AttributeError:
                state = None
            if state is not None:
                setattr(state, field_name, value)
                return
        super().__setattr__(name, value)

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
        theme.set_tui_focused(focus)
        self._refresh_focus_sensitive_widgets()

    def _refresh_focus_sensitive_widgets(self) -> None:
        """Refresh widgets whose colors depend on the current haze state."""
        self.refresh_css(animate=False)

        # Force full Screen repaint so $background change reaches all content
        self.screen.refresh()

        # Refresh Rich-based widgets that use haze-dependent rendering
        for widget in self.query(Banner):
            widget.refresh()
        for widget in self.query(BoxTabBar):
            widget.refresh()
        for widget in self.query("SessionRow"):
            widget.refresh()
        for widget in self.query("TodoRow"):
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
        status_bar = self._restore_persisted_state()
        self._hide_textual_tab_bar()
        self._wire_animation_widgets()
        self._media_state.animation_requested_mode = status_bar.animation_mode
        self._apply_animation_runtime()

        start_tab = self._resolve_start_tab()
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = start_tab
        box_tabs = self.query_one("#box-tab-bar", BoxTabBar)
        box_tabs.active_tab = start_tab
        self._focus_active_view(start_tab)

        try:
            await self.api.connect()
        except APP_RUNTIME_ERRORS:
            logger.exception("Failed to connect API")

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
        self._runtime_state.reload_loop = asyncio.get_running_loop()
        signal.signal(signal.SIGUSR1, self._handle_sigusr1)
        signal.signal(signal.SIGUSR2, self._handle_sigusr2)

    def _restore_persisted_state(self) -> TelecFooter:
        """Restore persisted state into mounted views and footer widgets."""
        sessions_view = self.query_one("#sessions-view", SessionsView)
        prep_view = self.query_one("#preparation-view", PreparationView)
        status_bar = self.query_one("#telec-footer", TelecFooter)
        sessions_view.load_persisted_state(self._persisted.get("sessions", {}))
        prep_view.load_persisted_state(self._persisted.get("preparation", {}))
        status_bar.load_persisted_state(self._persisted.get("status_bar", {}))
        theme.set_pane_theming_mode(status_bar.pane_theming_mode)
        self._apply_app_theme_for_mode(status_bar.pane_theming_mode)
        return status_bar

    def _hide_textual_tab_bar(self) -> None:
        """Hide Textual's built-in tab strip in favor of the custom bar."""
        for content_tabs in self.query(ContentTabs):
            content_tabs.display = False

    def _wire_animation_widgets(self) -> None:
        """Attach the shared animation engine to banner and tab widgets."""
        self.query_one(Banner).animation_engine = self._animation_engine
        try:
            self.query_one(BoxTabBar).animation_engine = self._animation_engine
        except APP_QUERY_ERRORS:
            logger.debug("BoxTabBar unavailable while wiring animations", exc_info=True)

    def _resolve_start_tab(self) -> str:
        """Resolve the initial tab from CLI overrides or persisted state."""
        tab_ids = {1: "sessions", 2: "preparation", 3: "jobs", 4: "config"}
        persisted_tab = self._persisted.get("app", {}).get("active_tab")
        if self._start_view != 1:
            return tab_ids.get(self._start_view, "sessions")
        if isinstance(persisted_tab, str) and persisted_tab in tab_ids.values():
            return persisted_tab
        return "sessions"

    @work(exclusive=True, group="computers")
    async def _reload_computers(self) -> None:
        """Re-fetch computer list on computer_updated event."""
        try:
            self._runtime_state.computers = await self.api.list_computers()
        except APP_DATA_ERRORS:
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
            payload = await self._build_data_refresh_message(_r0)
            self.post_message(payload)
        except APP_DATA_ERRORS:
            logger.exception("Data refresh failed")

    async def _build_data_refresh_message(self, start_time: float) -> DataRefreshed:
        """Build the aggregate `DataRefreshed` message from API calls."""
        computers, projects_with_todos, sessions, availability, jobs, settings = await asyncio.gather(
            self.api.list_computers(),
            self.api.list_projects_with_todos(),
            self.api.list_sessions(),
            self.api.get_agent_availability(),
            self.api.list_jobs(),
            self.api.get_settings(),
        )
        logger.trace("[PERF] _refresh_data gather done dt=%.3f", _t.monotonic() - start_time)
        self._runtime_state.computers = computers
        chiptunes_status = await self._load_chiptunes_status()
        return DataRefreshed(
            computers=computers,
            projects=[
                ProjectInfo(
                    computer=project.computer,
                    name=project.name,
                    path=project.path,
                    description=project.description,
                )
                for project in projects_with_todos
            ],
            projects_with_todos=projects_with_todos,
            sessions=sessions,
            availability=availability,
            jobs=jobs,
            tts_enabled=self._extract_tts_enabled(settings),
            chiptunes_loaded=bool(getattr(chiptunes_status, "loaded", False)) if chiptunes_status else False,
            chiptunes_playback=str(getattr(chiptunes_status, "playback", "cold")) if chiptunes_status else "cold",
            chiptunes_state_version=int(getattr(chiptunes_status, "state_version", 0)) if chiptunes_status else 0,
            chiptunes_playing=bool(getattr(chiptunes_status, "playing", False)) if chiptunes_status else False,
            chiptunes_track=str(getattr(chiptunes_status, "track", "")) if chiptunes_status else "",
            chiptunes_sid_path=str(getattr(chiptunes_status, "sid_path", "")) if chiptunes_status else "",
            chiptunes_pending_command_id=(
                str(getattr(chiptunes_status, "pending_command_id", "")) if chiptunes_status else ""
            ),
            chiptunes_pending_action=str(getattr(chiptunes_status, "pending_action", "")) if chiptunes_status else "",
        )

    @staticmethod
    def _extract_tts_enabled(settings: object) -> bool:
        """Best-effort extraction of TTS enabled state from settings payloads."""
        try:
            return bool(getattr(getattr(settings, "tts", None), "enabled", False))
        except (AttributeError, TypeError, ValueError):
            return False

    async def _load_chiptunes_status(self) -> object | None:
        """Best-effort fetch of the current chiptunes runtime state."""
        try:
            return await self.api.get_chiptunes_status()
        except APP_DATA_ERRORS:
            logger.debug("ChipTunes status refresh failed", exc_info=True)
            return None

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
            pane_bridge.sync_layout_state(
                preview_session_id=sessions_view.preview_session_id,
                sticky_session_ids=list(getattr(sessions_view, "_sticky_session_ids", [])),
            )
        pane_bridge.on_data_refreshed(message)

        # On first data load, apply layout with persisted preview/sticky state.
        # After that, layout changes are driven only by user actions
        # (PreviewChanged/StickyChanged messages) to prevent focus hijacking.
        # On reload, _initial_layout_applied is already True — panes survive
        # via seed_for_reload() called from bridge.on_data_refreshed().
        if not self._initial_layout_applied:
            self._init_state.initial_layout_applied = True
            sticky_session_ids = list(getattr(sessions_view, "_sticky_session_ids", []))
            if sessions_view.preview_session_id or sticky_session_ids:
                pane_bridge.on_preview_changed(PreviewChanged(sessions_view.preview_session_id))
                if sticky_session_ids:
                    pane_bridge.on_sticky_changed(StickyChanged(sticky_session_ids))
            self._update_banner_compactness(len(sticky_session_ids))

    # --- Pane manager message forwarding ---
    # Textual messages bubble UP through ancestors, not sideways to siblings.
    # PaneManagerBridge is a sibling of TabbedContent, so it never receives
    # messages posted by SessionsView. We forward them here.

    def on_preview_changed(self, message: PreviewChanged) -> None:
        """Forward preview changes to the pane bridge."""
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.on_preview_changed(message)
        self._schedule_sky_width_invalidation()

    def on_sticky_changed(self, message: StickyChanged) -> None:
        """Forward sticky-session changes to the pane bridge."""
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.on_sticky_changed(message)
        self._update_banner_compactness(len(message.session_ids))
        self._schedule_sky_width_invalidation()

    def on_state_changed(self, _message: StateChanged) -> None:
        """Schedule persistence when child state changes."""
        self._schedule_state_save()

    def on_focus_pane_request(self, message: FocusPaneRequest) -> None:
        """Forward explicit pane focus requests to the bridge."""
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.on_focus_pane_request(message)

    def on_doc_preview_request(self, message: DocPreviewRequest) -> None:
        """Forward document preview requests to the bridge."""
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.on_doc_preview_request(message)

    def on_doc_edit_request(self, message: DocEditRequest) -> None:
        """Forward document edit requests to the bridge."""
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.on_doc_edit_request(message)

    def _handle_exception(self, error: Exception) -> None:
        """Log unhandled exceptions BEFORE Rich's traceback renderer can crash on them."""
        logger.error(
            "Unhandled Textual exception",
            error=repr(error),
            traceback="".join(traceback.format_exception(type(error), error, error.__traceback__)),
        )
        try:
            super()._handle_exception(error)
        except APP_QUERY_ERRORS:
            logger.exception("Textual _handle_exception crashed (Rich traceback failure) — forcing exit")
            self.exit(1)

    def _activate_config_guided_mode(self) -> None:
        """Start guided mode in ConfigView after initial mount and data load."""
        try:
            config_view = self.query_one("#config-view", ConfigView)
            config_view.action_toggle_guided_mode()
            config_view.focus()
        except APP_QUERY_ERRORS:
            logger.exception("Failed to activate config guided mode")

    # --- State persistence ---

    def _schedule_state_save(self) -> None:
        timer = self._runtime_state.state_save_timer
        if timer is not None and hasattr(timer, "stop"):
            timer.stop()  # type: ignore[union-attr]
        self._runtime_state.state_save_timer = self.set_timer(0.5, self._flush_state_save)

    def _cancel_state_save_timer(self) -> None:
        timer = self._runtime_state.state_save_timer
        if timer is not None and hasattr(timer, "stop"):
            timer.stop()  # type: ignore[union-attr]
        self._runtime_state.state_save_timer = None

    def _flush_state_save(self) -> None:
        self._runtime_state.state_save_timer = None
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
        if self._runtime_state.reload_loop is not None:
            self._runtime_state.reload_loop.call_soon_threadsafe(self._appearance_refresh)

    def _appearance_refresh(self) -> None:
        """Hot-swap dark/light theme without restarting the process."""
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
        for widget in self.query("SessionRow"):
            widget.refresh()
        for widget in self.query("TodoRow"):
            widget.refresh()

        # Refresh animation engine theme (push dark_mode to running animations)
        self._animation_engine.refresh_theme()

        # Refresh Rich-based header widgets (not CSS-driven)
        for widget in self.query(Banner):
            widget.refresh()
        for widget in self.query(BoxTabBar):
            widget.refresh()

        # Refresh config content — its Rich styles depend on dark/light mode
        for widget in self.query(ConfigContent):
            widget.refresh()

    def on_resize(self, event: object) -> None:
        """Force sky animation to reposition celestials on terminal resize."""
        width = getattr(getattr(event, "size", None), "width", None)
        self._animation_engine.invalidate_term_width(width)

    def _schedule_sky_width_invalidation(self) -> None:
        """Debounce sky width refresh — cancel any pending timer and schedule a fresh one."""
        timer = self._sky_width_timer
        if timer is not None:
            timer.stop()
        self._sky_width_timer = self.set_timer(0.5, self._invalidate_sky_width)

    def _cancel_sky_width_timer(self) -> None:
        """Cancel pending sky width invalidation timer."""
        timer = self._sky_width_timer
        if timer is not None:
            timer.stop()
        self._sky_width_timer = None

    def _invalidate_sky_width(self) -> None:
        """Delayed sky width refresh after pane layout changes."""
        self._sky_width_timer = None
        self._animation_engine.invalidate_term_width()

    def _handle_sigusr2(self, _signum: int, _frame: object) -> None:
        """Catch SIGUSR2 (code change) and schedule full process restart."""
        if self._runtime_state.reload_loop is not None:
            self._runtime_state.reload_loop.call_soon_threadsafe(self._sigusr2_reload)

    def _sigusr2_reload(self) -> None:
        """Save state and exit for full process restart.

        Python modules are cached in memory — refreshing CSS and data
        doesn't pick up code changes. The outer _run_tui() loop detects
        RELOAD_EXIT and re-execs the process.
        """
        self._cancel_state_save_timer()
        self._stop_animation()
        self._cancel_chiptunes_reconcile()
        self._cancel_sky_width_timer()
        self._save_state_sync()
        self.exit(result=RELOAD_EXIT)

    # --- Lifecycle ---

    def _show_animation_toast(self, _target: str, _animation: Animation) -> None:
        """No-op — animation toasts disabled."""

    async def action_quit(self) -> None:
        self._stop_animation()
        self._cancel_chiptunes_reconcile()
        self._cancel_state_save_timer()
        self._cancel_sky_width_timer()
        self._save_state_sync()
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
        pane_bridge.cleanup()
        await self.api.close()
        self.exit()
