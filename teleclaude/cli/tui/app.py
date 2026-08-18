"""Main TUI application built on Textual."""

from __future__ import annotations

import asyncio
import os
import signal
import time as _t
import traceback
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from instrukt_ai_logging import get_logger
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, TabbedContent, TabPane
from textual.widgets._tabbed_content import ContentTabs

from teleclaude.api_models import (
    AgentAvailabilityDTO,
    ComputerDTO,
    JobDTO,
    ModelAvailabilityDTO,
    ProjectWithTodosDTO,
    SessionDTO,
    TuiBootstrapDTO,
    TuiBootstrapPillar,
)
from teleclaude.cli.api_client import APIError
from teleclaude.cli.tui import theme
from teleclaude.cli.tui.animation_engine import AnimationEngine
from teleclaude.cli.tui.animation_observability import AnimationPerfTracker
from teleclaude.cli.tui.app_actions import TelecAppActionsMixin
from teleclaude.cli.tui.app_cross_nav import TelecAppCrossNavMixin
from teleclaude.cli.tui.app_media import TelecAppMediaMixin
from teleclaude.cli.tui.app_ws import TelecAppWsMixin
from teleclaude.cli.tui.bootstrap import (
    BOOTSTRAP_PILLARS,
    BootstrapRetryState,
    failed_bootstrap_pillars,
    projects_from_projects_with_todos,
)
from teleclaude.cli.tui.creator_session import CreatorSessionInfo, CreatorSessionLookup
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
from teleclaude.cli.tui.paste_guard import (
    PASTE_IGNORED_NOTIFICATION as _PASTE_IGNORED_NOTIFICATION,
)
from teleclaude.cli.tui.paste_guard import (
    POST_PASTE_KEY_SUPPRESSION_SECONDS as _POST_PASTE_KEY_SUPPRESSION_SECONDS,
)
from teleclaude.cli.tui.paste_guard import (
    RAW_KEY_BURST_QUIET_SECONDS as _RAW_KEY_BURST_QUIET_SECONDS,
)
from teleclaude.cli.tui.paste_guard import (
    RAW_KEY_BURST_THRESHOLD as _RAW_KEY_BURST_THRESHOLD,
)
from teleclaude.cli.tui.paste_guard import (
    RAW_KEY_BURST_WINDOW_SECONDS as _RAW_KEY_BURST_WINDOW_SECONDS,
)
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
from teleclaude.cli.tui.widgets.agent_status import AgentRenderStatus, classify_agent_render_status
from teleclaude.cli.tui.widgets.banner import Banner
from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar
from teleclaude.cli.tui.widgets.telec_footer import TelecFooter
from teleclaude.core.agents import get_enabled_agents

if TYPE_CHECKING:
    from textual.timer import Timer

    from teleclaude.cli.api_client import TelecAPIClient
    from teleclaude.cli.tui.animations.base import Animation

logger = get_logger(__name__)
APP_QUERY_ERRORS = (AttributeError, LookupError, RuntimeError, TypeError, ValueError)
APP_RUNTIME_ERRORS = (APIError, AttributeError, ImportError, LookupError, OSError, RuntimeError, TypeError, ValueError)
APP_DATA_ERRORS = (APIError, AttributeError, OSError, RuntimeError, TypeError, ValueError)
_GUARD_RELEASED_EVENT_ATTR = "_telec_guard_released"
_AVAILABILITY_INGRESS_EVENT = "tui.availability.ingress"
_AVAILABILITY_COMMIT_EVENT = "tui.availability.commit"
_AVAILABILITY_PILLAR: TuiBootstrapPillar = "availability"
_AVAILABILITY_PILLARS: tuple[TuiBootstrapPillar, ...] = (_AVAILABILITY_PILLAR,)
_SAFE_INPUT_AGENT = "agent"
_SAFE_INPUT_AVAILABLE = "available"
_SAFE_INPUT_STATUS = "status"
_APP_STATE_FIELDS = {
    "_persisted": ("_init_state", "persisted"),
    "_start_view": ("_init_state", "start_view"),
    "_config_guided": ("_init_state", "config_guided"),
    "_is_reload": ("_init_state", "is_reload"),
    "_initial_layout_applied": ("_init_state", "initial_layout_applied"),
    "_state_save_timer": ("_runtime_state", "state_save_timer"),
    "_computers": ("_runtime_state", "computers"),
    "_session_agents": ("_runtime_state", "session_agents"),
    "_tui_initiated_sessions": ("_runtime_state", "tui_initiated_sessions"),
    "_sky_width_timer": ("_runtime_state", "sky_width_timer"),
    "_reload_loop": ("_runtime_state", "reload_loop"),
    "_bootstrap_retry": ("_runtime_state", "bootstrap_retry"),
    "_bootstrap_retry_timer": ("_runtime_state", "bootstrap_retry_timer"),
    "_bootstrap_pending_pillars": ("_runtime_state", "bootstrap_pending_pillars"),
    "_availability": ("_runtime_state", "availability"),
    "_animation_engine": ("_media_state", "animation_engine"),
    "_animation_perf": ("_media_state", "animation_perf"),
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


class AvailabilityObservationSource(StrEnum):
    """Closed source vocabulary for TUI availability observations."""

    COLD_START = "cold_start"
    REFRESH = "refresh"
    DELTA = "delta"
    WEBSOCKET_CONNECT = "websocket_connect"
    RETRY = "retry"


class AvailabilityObservationOutcome(StrEnum):
    """Closed outcome vocabulary for TUI availability observations."""

    ACCEPTED = "accepted"
    REQUESTED = "requested"
    SCHEDULED = "scheduled"
    PROJECTED = "projected"
    PRESERVED = "preserved"
    FAILED = "failed"


class AvailabilityObservationReason(StrEnum):
    """Closed reason vocabulary for TUI availability observations."""

    APP_MOUNTED = "app_mounted"
    BOOTSTRAP_REQUEST = "bootstrap_request"
    RECONNECT = "reconnect"
    RETRY = "retry"
    CONNECTED = "connected"
    EVENT_RECEIVED = "event_received"
    SNAPSHOT_RECEIVED = "snapshot_received"
    SNAPSHOT_APPLIED = "snapshot_applied"
    FIELD_OMITTED = "field_omitted"
    PILLAR_MISSING = "pillar_missing"
    DELTA_MERGED = "delta_merged"
    NO_SNAPSHOT = "no_snapshot"
    API_ERROR = "api_error"
    RETRY_SCHEDULED = "retry_scheduled"


@dataclass
class _AppInitState:
    start_view: int
    config_guided: bool
    persisted: dict[str, dict[str, object]]  # guard: loose-dict - dynamic payload
    is_reload: bool
    initial_layout_applied: bool


@dataclass
class _AppRuntimeState:
    state_save_timer: object | None = None
    computers: list[ComputerDTO] = field(default_factory=list)
    session_agents: dict[str, str] = field(default_factory=dict)
    tui_initiated_sessions: set[str] = field(default_factory=set)
    sky_width_timer: Timer | None = None
    reload_loop: asyncio.AbstractEventLoop | None = None
    bootstrap_retry: BootstrapRetryState = field(default_factory=BootstrapRetryState)
    bootstrap_retry_timer: Timer | None = None
    bootstrap_pending_pillars: set[TuiBootstrapPillar] = field(default_factory=set)
    bootstrap_retry_parents: dict[TuiBootstrapPillar, str] = field(default_factory=dict)
    availability: dict[str, AgentAvailabilityDTO] = field(default_factory=dict)
    app_instance_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class _AppMediaState:
    animation_engine: AnimationEngine = field(default_factory=AnimationEngine)
    animation_perf: AnimationPerfTracker = field(default_factory=AnimationPerfTracker)
    periodic_trigger: object | None = None
    activity_trigger: object | None = None
    animation_timer: object | None = None
    animation_requested_mode: str = "off"
    chiptunes_state_version: int = -1
    chiptunes_reconcile_task: asyncio.Task[None] | None = None


@dataclass(frozen=True)
class _RefreshStateSnapshot:
    computers: list[ComputerDTO]
    projects_with_todos: list[ProjectWithTodosDTO]
    sessions: list[SessionDTO]
    jobs: list[JobDTO]
    tts_enabled: bool
    creator_session_lookup: CreatorSessionLookup
    chiptunes_loaded: bool
    chiptunes_playback: str
    chiptunes_state_version: int
    chiptunes_playing: bool
    chiptunes_track: str
    chiptunes_sid_path: str
    chiptunes_pending_command_id: str
    chiptunes_pending_action: str


class TelecApp(TelecAppWsMixin, TelecAppActionsMixin, TelecAppCrossNavMixin, TelecAppMediaMixin, App[str | None]):
    """Main TeleClaude TUI application."""

    api: TelecAPIClient
    _persisted: dict[str, dict[str, object]]  # guard: loose-dict - dynamic payload
    _start_view: int
    _config_guided: bool
    _is_reload: bool
    _initial_layout_applied: bool
    _state_save_timer: Timer | None
    _computers: list[ComputerDTO]
    _session_agents: dict[str, str]
    _tui_initiated_sessions: set[str]
    _sky_width_timer: Timer | None
    _reload_loop: asyncio.AbstractEventLoop | None
    _bootstrap_retry: BootstrapRetryState
    _bootstrap_retry_timer: Timer | None
    _bootstrap_pending_pillars: set[TuiBootstrapPillar]
    _availability: dict[str, AgentAvailabilityDTO]
    _animation_engine: AnimationEngine
    _periodic_trigger: object | None
    _activity_trigger: object | None
    _animation_timer: object | None
    _animation_requested_mode: str
    _chiptunes_state_version: int
    _chiptunes_reconcile_task: asyncio.Task[None] | None
    _paste_guard_keys: deque[tuple[str, str | None]]
    _paste_guard_flush_timer: Timer | None
    _paste_guard_window_started_at: float | None
    _paste_guard_quiet_until: float
    _last_paste_at: float

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
            "switch_tab('config')",
            "Config",
            key_display="③",
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
        self._paste_guard_keys = deque(maxlen=_RAW_KEY_BURST_THRESHOLD + 1)
        self._paste_guard_flush_timer = None
        self._paste_guard_window_started_at = None
        self._paste_guard_quiet_until = float("-inf")
        self._last_paste_at = float("-inf")
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

    def on_paste(self, event: events.Paste) -> None:
        """Discard bracketed-paste events that reach the TUI control surface."""
        if self._input_surface_active():
            return
        self._last_paste_at = _t.monotonic()
        event.prevent_default()
        event.stop()
        self.notify(_PASTE_IGNORED_NOTIFICATION, severity="warning")

    def on_key(self, event: events.Key) -> None:
        """Coalesce control-surface keys before binding dispatch."""
        if self._input_surface_active():
            return
        if getattr(event, _GUARD_RELEASED_EVENT_ATTR, False):
            return

        event.prevent_default()
        event.stop()

        now = _t.monotonic()
        if now - self._last_paste_at <= _POST_PASTE_KEY_SUPPRESSION_SECONDS or now < self._paste_guard_quiet_until:
            return

        if (
            self._paste_guard_window_started_at is not None
            and now - self._paste_guard_window_started_at > _RAW_KEY_BURST_WINDOW_SECONDS
        ):
            if self._paste_guard_flush_timer is not None:
                self._paste_guard_flush_timer.stop()
            self._flush_guarded_keys()

        if self._paste_guard_window_started_at is None:
            self._paste_guard_window_started_at = now

        self._paste_guard_keys.append((event.key, event.character))
        if len(self._paste_guard_keys) > _RAW_KEY_BURST_THRESHOLD:
            self._discard_guarded_keys(now)
            return

        self._schedule_guarded_key_flush()

    def _input_surface_active(self) -> bool:
        """True when an input surface is active, so control-surface guards stand down.

        Bindings must only fire on the bare control surface — when no popup is open
        and no text field is active. A pushed ModalScreen counts as a popup; the
        focused-widget walk covers text fields (Textual ``Input``, any ``paste_safe``
        widget, the config inline editor).
        """
        if isinstance(self.screen, ModalScreen):
            return True
        return self._focused_widget_is_paste_safe()

    def _focused_widget_is_paste_safe(self) -> bool:
        """Return whether the focused widget explicitly accepts paste or key bursts."""
        widget = self.focused
        while isinstance(widget, Widget):
            if getattr(widget, "paste_safe", False) or isinstance(widget, Input):
                return True
            widget = widget.parent
        return False

    def _schedule_guarded_key_flush(self) -> None:
        """Schedule quiet manual keys for release after the burst window."""
        if self._paste_guard_flush_timer is not None:
            return
        self._paste_guard_flush_timer = self.set_timer(_RAW_KEY_BURST_WINDOW_SECONDS, self._flush_guarded_keys)

    def _flush_guarded_keys(self) -> None:
        """Release buffered keys that did not cross the burst threshold."""
        guarded_keys = list(self._paste_guard_keys)
        self._paste_guard_keys.clear()
        self._paste_guard_flush_timer = None
        self._paste_guard_window_started_at = None
        if self._input_surface_active():
            return
        for key, character in guarded_keys:
            event = events.Key(key, character)
            setattr(event, _GUARD_RELEASED_EVENT_ATTR, True)
            event.set_sender(self)
            if self._driver is not None:
                self._driver.send_message(event)
            else:
                self.post_message(event)

    def _discard_guarded_keys(self, now: float | None = None) -> None:
        """Drop buffered injected keys and surface one warning."""
        if self._paste_guard_flush_timer is not None:
            self._paste_guard_flush_timer.stop()
        self._paste_guard_keys.clear()
        self._paste_guard_flush_timer = None
        self._paste_guard_window_started_at = None
        self._paste_guard_quiet_until = (now if now is not None else _t.monotonic()) + _RAW_KEY_BURST_QUIET_SECONDS
        self.notify(_PASTE_IGNORED_NOTIFICATION, severity="warning")

    def compose(self) -> ComposeResult:
        logger.trace("[PERF] compose START t=%.3f", _t.monotonic())
        yield Banner()
        yield BoxTabBar(id="box-tab-bar")
        with TabbedContent(id="main-tabs"):
            with TabPane("Sessions", id="sessions"):
                yield SessionsView(id="sessions-view")
            with TabPane("Preparation", id="preparation"):
                yield PreparationView(id="preparation-view")
            with TabPane("Config", id="config"):
                yield ConfigView(id="config-view")
        yield JobsView(id="jobs-view")
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
        self._project_cold_start_availability()

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
            include_removed=True,
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
        self.restore_human_filter(self._persisted.get("app", {}))
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
        tab_ids = {1: "sessions", 2: "preparation", 3: "config"}
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

    @work(group="refresh")
    async def _refresh_data(
        self,
        pillars: list[TuiBootstrapPillar] | None = None,
        *,
        parent_operation_id: str | None = None,
        observation_reason: AvailabilityObservationReason = AvailabilityObservationReason.BOOTSTRAP_REQUEST,
    ) -> None:
        """Fetch requested bootstrap data and post DataRefreshed.

        The daemon returns partial pillar success. This method merges present
        fields into the mounted UI state and retries only unresolved pillars.
        """
        _r0 = _t.monotonic()
        logger.trace("[PERF] _refresh_data START t=%.3f", _r0)
        requested = pillars or list(BOOTSTRAP_PILLARS)
        operation_id = str(uuid4())
        self._observe_availability_ingress(
            source=AvailabilityObservationSource.REFRESH,
            outcome=AvailabilityObservationOutcome.REQUESTED,
            reason=observation_reason,
            operation_id=operation_id,
            parent_operation_id=parent_operation_id,
            requested_pillars=requested,
            before_projection=self._classified_availability_projection(),
        )
        try:
            payload = await self._build_data_refresh_message(
                _r0,
                requested,
                operation_id=operation_id,
                parent_operation_id=parent_operation_id,
            )
            self._observe_refresh_availability_ingress(payload)
            self.post_message(payload)
        except APP_DATA_ERRORS:
            logger.exception("Data refresh failed")
            projection = self._classified_availability_projection()
            self._observe_availability_commit(
                source=AvailabilityObservationSource.REFRESH,
                outcome=AvailabilityObservationOutcome.FAILED,
                reason=AvailabilityObservationReason.API_ERROR,
                operation_id=operation_id,
                parent_operation_id=parent_operation_id,
                before_projection=projection,
                after_projection=projection,
            )
            self._schedule_bootstrap_retry(requested, parent_operation_id=operation_id)

    async def _build_data_refresh_message(
        self,
        start_time: float,
        requested: list[TuiBootstrapPillar],
        *,
        operation_id: str,
        parent_operation_id: str | None,
    ) -> DataRefreshed:
        """Build the aggregate `DataRefreshed` message from TUI bootstrap data."""
        bootstrap = await self.api.get_tui_bootstrap(requested, include_removed=True)
        missing = failed_bootstrap_pillars(bootstrap, requested=requested)
        creator_session_lookup = (
            await self._fetch_creator_session_lookup() if set(requested) == set(BOOTSTRAP_PILLARS) else None
        )
        logger.trace("[PERF] _refresh_data bootstrap done dt=%.3f", _t.monotonic() - start_time)
        return self._merge_bootstrap_message(
            bootstrap,
            creator_session_lookup,
            requested=requested,
            missing=missing,
            operation_id=operation_id,
            parent_operation_id=parent_operation_id,
        )

    async def _fetch_creator_session_lookup(self) -> CreatorSessionLookup | None:
        """Fetch every session, including retained-closed ones, for the creator-session row lookup.

        A separate round trip from the bootstrap `sessions` pillar (which never
        includes closed sessions) — the creator-session row needs to classify a
        lineage's acting session id as live, retained-closed, or absent.

        Returns None on fetch failure so `_merge_bootstrap_message` retains the
        last successfully fetched lookup instead of blanking every creator row
        to inert — a transient daemon hiccup must not read as "session purged."
        """
        try:
            sessions = await self.api.list_sessions(include_closed=True)
        except APP_DATA_ERRORS:
            logger.exception("Creator-session lookup fetch failed")
            return None
        return {
            session.session_id: CreatorSessionInfo(
                status="closed" if session.closed_at else "live",
                computer=session.computer,
            )
            for session in sessions
        }

    def _merge_bootstrap_message(
        self,
        bootstrap: TuiBootstrapDTO,
        creator_session_lookup: CreatorSessionLookup | None,
        *,
        requested: list[TuiBootstrapPillar],
        missing: list[TuiBootstrapPillar],
        operation_id: str,
        parent_operation_id: str | None,
    ) -> DataRefreshed:
        """Merge successful bootstrap fields with currently mounted UI state."""
        current = self._current_refresh_state()
        data = bootstrap.data

        computers = data.computers if data.computers is not None else current.computers
        projects_with_todos = (
            data.projects_with_todos if data.projects_with_todos is not None else current.projects_with_todos
        )
        sessions = data.sessions if data.sessions is not None else current.sessions
        jobs = data.jobs if data.jobs is not None else current.jobs
        settings = data.settings
        chiptunes_status = data.chiptunes
        lookup = creator_session_lookup if creator_session_lookup is not None else current.creator_session_lookup

        self._runtime_state.computers = computers
        return DataRefreshed(
            computers,
            projects_from_projects_with_todos(projects_with_todos),
            projects_with_todos,
            sessions,
            data.availability,
            jobs,
            self._extract_tts_enabled(settings) if settings is not None else current.tts_enabled,
            lookup,
            requested_pillars=list(requested),
            missing_pillars=list(missing),
            operation_id=operation_id,
            parent_operation_id=parent_operation_id,
            chiptunes_loaded=(
                bool(getattr(chiptunes_status, "loaded", False)) if chiptunes_status else current.chiptunes_loaded
            ),
            chiptunes_playback=(
                str(getattr(chiptunes_status, "playback", "cold")) if chiptunes_status else current.chiptunes_playback
            ),
            chiptunes_state_version=(
                int(getattr(chiptunes_status, "state_version", 0))
                if chiptunes_status
                else current.chiptunes_state_version
            ),
            chiptunes_playing=(
                bool(getattr(chiptunes_status, "playing", False)) if chiptunes_status else current.chiptunes_playing
            ),
            chiptunes_track=(
                str(getattr(chiptunes_status, "track", "")) if chiptunes_status else current.chiptunes_track
            ),
            chiptunes_sid_path=(
                str(getattr(chiptunes_status, "sid_path", "")) if chiptunes_status else current.chiptunes_sid_path
            ),
            chiptunes_pending_command_id=(
                str(getattr(chiptunes_status, "pending_command_id", ""))
                if chiptunes_status
                else current.chiptunes_pending_command_id
            ),
            chiptunes_pending_action=(
                str(getattr(chiptunes_status, "pending_action", ""))
                if chiptunes_status
                else current.chiptunes_pending_action
            ),
        )

    def _reconcile_bootstrap_retry_state(
        self,
        *,
        requested: list[TuiBootstrapPillar],
        missing: list[TuiBootstrapPillar],
        operation_id: str,
    ) -> None:
        """Update retry state after a bootstrap response."""
        missing_set = set(missing)
        succeeded: set[TuiBootstrapPillar] = {pillar for pillar in requested if pillar not in missing_set}
        self._runtime_state.bootstrap_pending_pillars.difference_update(succeeded)
        for pillar in succeeded:
            self._runtime_state.bootstrap_retry_parents.pop(pillar, None)

        if missing:
            self._schedule_bootstrap_retry(missing, parent_operation_id=operation_id)
            return
        if self._runtime_state.bootstrap_pending_pillars:
            self._ensure_bootstrap_retry_timer()
            return
        self._clear_bootstrap_retry()

    def _schedule_bootstrap_retry(
        self,
        pillars: list[TuiBootstrapPillar],
        *,
        parent_operation_id: str,
    ) -> None:
        """Retry unresolved bootstrap pillars with capped exponential backoff."""
        if not pillars:
            self._clear_bootstrap_retry()
            return
        self._runtime_state.bootstrap_pending_pillars.update(pillars)
        for pillar in pillars:
            self._runtime_state.bootstrap_retry_parents[pillar] = parent_operation_id
        self._arm_bootstrap_retry_timer(reset_existing=True)

    def _ensure_bootstrap_retry_timer(self) -> None:
        """Ensure pending pillars still have a retry timer."""
        self._arm_bootstrap_retry_timer(reset_existing=False)

    def _arm_bootstrap_retry_timer(self, *, reset_existing: bool) -> None:
        """Arm the pending-pillar retry timer."""
        timer = self._runtime_state.bootstrap_retry_timer
        if timer is not None and not reset_existing:
            return
        if timer is not None:
            timer.stop()
        delay = self._runtime_state.bootstrap_retry.consume_delay()
        pending = self._pending_bootstrap_pillars()
        logger.info("Scheduling TUI bootstrap retry", pillars=pending, delay_s=delay)
        for operation_id, operation_pillars in self._pending_bootstrap_pillars_by_parent().items():
            self._observe_availability_ingress(
                source=AvailabilityObservationSource.RETRY,
                outcome=AvailabilityObservationOutcome.SCHEDULED,
                reason=AvailabilityObservationReason.RETRY_SCHEDULED,
                operation_id=operation_id,
                parent_operation_id=None,
                requested_pillars=operation_pillars,
                before_projection=self._classified_availability_projection(),
                delay_s=delay,
            )
        self._runtime_state.bootstrap_retry_timer = self.set_timer(
            delay,
            self._retry_pending_bootstrap_pillars,
        )

    def _retry_pending_bootstrap_pillars(self) -> None:
        """Retry whichever pillars are still pending when the timer fires."""
        self._runtime_state.bootstrap_retry_timer = None
        for parent_operation_id, pillars in self._pending_bootstrap_pillars_by_parent().items():
            self._refresh_data(
                pillars,
                parent_operation_id=parent_operation_id,
                observation_reason=AvailabilityObservationReason.RETRY,
            )

    def _pending_bootstrap_pillars(self) -> list[TuiBootstrapPillar]:
        """Return pending pillars in canonical bootstrap order."""
        pending = self._runtime_state.bootstrap_pending_pillars
        return [pillar for pillar in BOOTSTRAP_PILLARS if pillar in pending]

    def _pending_bootstrap_pillars_by_parent(self) -> dict[str, list[TuiBootstrapPillar]]:
        """Group pending retry pillars by the operation that scheduled them."""
        grouped: dict[str, list[TuiBootstrapPillar]] = {}
        for pillar in self._pending_bootstrap_pillars():
            parent_operation_id = self._runtime_state.bootstrap_retry_parents[pillar]
            grouped.setdefault(parent_operation_id, []).append(pillar)
        return grouped

    def _clear_bootstrap_retry(self) -> None:
        """Clear any pending bootstrap retry after success."""
        timer = self._runtime_state.bootstrap_retry_timer
        if timer is not None:
            timer.stop()
        self._runtime_state.bootstrap_retry_timer = None
        self._runtime_state.bootstrap_pending_pillars.clear()
        self._runtime_state.bootstrap_retry_parents.clear()
        self._runtime_state.bootstrap_retry.reset()

    def _current_refresh_state(self) -> _RefreshStateSnapshot:
        """Read current mounted UI state for merge-only bootstrap updates."""
        sessions_view = self.query_one("#sessions-view", SessionsView)
        prep_view = self.query_one("#preparation-view", PreparationView)
        jobs_view = self.query_one("#jobs-view", JobsView)
        status_bar = self.query_one("#telec-footer", TelecFooter)

        projects_with_todos = list(getattr(prep_view, "_projects_with_todos", []))
        if not projects_with_todos:
            projects_with_todos = [
                ProjectWithTodosDTO(
                    computer=project.computer,
                    name=project.name,
                    path=project.path,
                    description=project.description,
                    todos=[],
                )
                for project in getattr(sessions_view, "_projects", [])
            ]

        return _RefreshStateSnapshot(
            computers=list(getattr(sessions_view, "_computers", self._runtime_state.computers)),
            projects_with_todos=projects_with_todos,
            sessions=list(getattr(sessions_view, "_sessions", [])),
            jobs=list(getattr(jobs_view, "_jobs", [])),
            tts_enabled=bool(getattr(status_bar, "tts_enabled", False)),
            creator_session_lookup=dict(getattr(prep_view, "_creator_session_lookup", {})),
            chiptunes_loaded=bool(getattr(status_bar, "chiptunes_loaded", False)),
            chiptunes_playback=str(getattr(status_bar, "chiptunes_playback", "cold")),
            chiptunes_state_version=int(getattr(self, "_chiptunes_state_version", 0)),
            chiptunes_playing=bool(getattr(status_bar, "chiptunes_playing", False)),
            chiptunes_track=str(getattr(status_bar, "chiptunes_track", "")),
            chiptunes_sid_path=str(getattr(status_bar, "chiptunes_sid_path", "")),
            chiptunes_pending_command_id=str(getattr(status_bar, "chiptunes_pending_command_id", "")),
            chiptunes_pending_action=str(getattr(status_bar, "chiptunes_pending_action", "")),
        )

    @staticmethod
    def _extract_tts_enabled(settings: object) -> bool:
        """Best-effort extraction of TTS enabled state from settings payloads."""
        try:
            return bool(getattr(getattr(settings, "tts", None), "enabled", False))
        except (AttributeError, TypeError, ValueError):
            return False

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
        )
        prep_view.update_data(
            message.projects_with_todos,
            creator_session_lookup=message.creator_session_lookup,
        )
        jobs_view.update_data(message.jobs)
        if message.availability is not None:
            self._replace_agent_availability(
                message.availability,
                operation_id=message.operation_id,
                parent_operation_id=message.parent_operation_id,
            )
        else:
            reason = (
                AvailabilityObservationReason.PILLAR_MISSING
                if _AVAILABILITY_PILLAR in message.requested_pillars
                else AvailabilityObservationReason.FIELD_OMITTED
            )
            projection = self._classified_availability_projection()
            self._observe_availability_commit(
                source=AvailabilityObservationSource.REFRESH,
                outcome=AvailabilityObservationOutcome.PRESERVED,
                reason=reason,
                operation_id=message.operation_id,
                parent_operation_id=message.parent_operation_id,
                before_projection=projection,
                after_projection=projection,
            )
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
        self._reconcile_bootstrap_retry_state(
            requested=message.requested_pillars,
            missing=message.missing_pillars,
            operation_id=message.operation_id,
        )

        logger.trace("[PERF] on_data_refreshed views updated dt=%.3f", _t.monotonic() - _d0)

        # Forward to pane bridge (sibling — messages don't reach it via bubbling).
        # Re-sync the bridge's preview/sticky mirror from the canonical Sessions
        # view state on every refresh. sync_layout_state only updates the mirror
        # (no layout/focus side effects), so it cannot steal focus; it just keeps
        # the bridge from drifting and lets seed_for_reload() see correct ids.
        pane_bridge = self.query_one("#pane-bridge", PaneManagerBridge)
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

    def _replace_agent_availability(
        self,
        availability: dict[str, AgentAvailabilityDTO],
        *,
        operation_id: str,
        parent_operation_id: str | None,
    ) -> None:
        """Replace the authoritative availability snapshot and project it."""
        before_projection = self._classified_availability_projection()
        self._runtime_state.availability = dict(availability)
        self._project_agent_availability()
        self._observe_availability_commit(
            source=AvailabilityObservationSource.REFRESH,
            outcome=AvailabilityObservationOutcome.PROJECTED,
            reason=AvailabilityObservationReason.SNAPSHOT_APPLIED,
            operation_id=operation_id,
            parent_operation_id=parent_operation_id,
            before_projection=before_projection,
            after_projection=self._classified_availability_projection(),
        )

    def _accept_agent_availability_event(self, availability: AgentAvailabilityDTO) -> None:
        """Observe and apply one validated live availability event."""
        operation_id = str(uuid4())
        before_projection = self._classified_availability_projection()
        self._observe_availability_ingress(
            source=AvailabilityObservationSource.DELTA,
            outcome=AvailabilityObservationOutcome.ACCEPTED,
            reason=AvailabilityObservationReason.EVENT_RECEIVED,
            operation_id=operation_id,
            parent_operation_id=None,
            agent=availability.agent,
            safe_input=self._safe_availability_input(availability),
            before_projection=before_projection,
        )
        self._merge_agent_availability(
            availability,
            operation_id=operation_id,
            before_projection=before_projection,
        )

    def _merge_agent_availability(
        self,
        availability: AgentAvailabilityDTO,
        *,
        operation_id: str,
        before_projection: dict[str, AgentRenderStatus],
    ) -> None:
        """Merge one live agent availability delta and project it."""
        merged = dict(self._runtime_state.availability)
        prior = merged.get(availability.agent)
        if availability.model_delta is not None:
            delta = availability.model_delta
            prior_models = prior.models if prior is not None else []
            retained_models = [model for model in prior_models if model.model != delta.model]
            if delta.active and delta.unavailable_until is not None and delta.reason is not None:
                retained_models.append(
                    ModelAvailabilityDTO(
                        model=delta.model,
                        unavailable_until=delta.unavailable_until,
                        reason=delta.reason,
                    )
                )
            elif delta.active:
                logger.error("Ignoring incomplete active model availability delta", model=delta.model)
            merged[availability.agent] = availability.model_copy(update={"models": retained_models})
        else:
            merged[availability.agent] = availability
        self._runtime_state.availability = merged
        self._project_agent_availability()
        self._observe_availability_commit(
            source=AvailabilityObservationSource.DELTA,
            outcome=AvailabilityObservationOutcome.PROJECTED,
            reason=AvailabilityObservationReason.DELTA_MERGED,
            operation_id=operation_id,
            parent_operation_id=None,
            agent=availability.agent,
            before_projection=before_projection,
            after_projection=self._classified_availability_projection(),
        )

    def _hydrate_agent_availability(self) -> None:
        """Anchor websocket reconnect and request authoritative availability."""
        operation_id = str(uuid4())
        self._observe_availability_ingress(
            source=AvailabilityObservationSource.WEBSOCKET_CONNECT,
            outcome=AvailabilityObservationOutcome.ACCEPTED,
            reason=AvailabilityObservationReason.CONNECTED,
            operation_id=operation_id,
            parent_operation_id=None,
            before_projection=self._classified_availability_projection(),
        )
        self._refresh_data(
            list(_AVAILABILITY_PILLARS),
            parent_operation_id=operation_id,
            observation_reason=AvailabilityObservationReason.RECONNECT,
        )

    def _project_cold_start_availability(self) -> None:
        """Project an honest unknown state before the first snapshot arrives."""
        operation_id = str(uuid4())
        before_projection = self._classified_availability_projection()
        self._observe_availability_ingress(
            source=AvailabilityObservationSource.COLD_START,
            outcome=AvailabilityObservationOutcome.ACCEPTED,
            reason=AvailabilityObservationReason.APP_MOUNTED,
            operation_id=operation_id,
            parent_operation_id=None,
            before_projection=before_projection,
        )
        self._project_agent_availability()
        self._observe_availability_commit(
            source=AvailabilityObservationSource.COLD_START,
            outcome=AvailabilityObservationOutcome.PROJECTED,
            reason=AvailabilityObservationReason.NO_SNAPSHOT,
            operation_id=operation_id,
            parent_operation_id=None,
            before_projection=before_projection,
            after_projection=self._classified_availability_projection(),
        )

    def _project_agent_availability(self) -> None:
        """Project the App-owned availability cache to read-only UI copies."""
        availability = dict(self._runtime_state.availability)
        self.query_one(TelecFooter).update_availability(availability)
        self.query_one(SessionsView).set_availability(availability)
        self.query_one(PreparationView).set_availability(availability)

    def _observe_refresh_availability_ingress(self, message: DataRefreshed) -> None:
        """Record decoded availability presence or omission before App mutation."""
        if message.availability is not None:
            reason = AvailabilityObservationReason.SNAPSHOT_RECEIVED
            safe_input: object | None = {
                agent: self._safe_availability_input(availability)
                for agent, availability in message.availability.items()
            }
        else:
            reason = (
                AvailabilityObservationReason.PILLAR_MISSING
                if _AVAILABILITY_PILLAR in message.requested_pillars
                else AvailabilityObservationReason.FIELD_OMITTED
            )
            safe_input = None
        self._observe_availability_ingress(
            source=AvailabilityObservationSource.REFRESH,
            outcome=AvailabilityObservationOutcome.ACCEPTED,
            reason=reason,
            operation_id=message.operation_id,
            parent_operation_id=message.parent_operation_id,
            safe_input=safe_input,
            before_projection=self._classified_availability_projection(),
        )

    @staticmethod
    def _safe_availability_input(availability: AgentAvailabilityDTO) -> dict[str, str | bool | None]:
        """Project only published typed fields into availability observations."""
        return {
            _SAFE_INPUT_AGENT: availability.agent,
            _SAFE_INPUT_AVAILABLE: availability.available,
            _SAFE_INPUT_STATUS: availability.status,
        }

    def _classified_availability_projection(self) -> dict[str, AgentRenderStatus]:
        """Return the complete configured-agent presentation projection."""
        return {
            agent: classify_agent_render_status(self._runtime_state.availability.get(agent))
            for agent in get_enabled_agents()
        }

    def _observe_availability_ingress(
        self,
        *,
        source: AvailabilityObservationSource,
        outcome: AvailabilityObservationOutcome,
        reason: AvailabilityObservationReason,
        operation_id: str,
        parent_operation_id: str | None,
        agent: str | None = None,
        requested_pillars: list[TuiBootstrapPillar] | None = None,
        safe_input: object | None = None,
        before_projection: dict[str, AgentRenderStatus] | None = None,
        delay_s: float | None = None,
    ) -> None:
        """Emit one safe, correlated availability ingress record."""
        logger.info(
            _AVAILABILITY_INGRESS_EVENT,
            app_instance_id=self._runtime_state.app_instance_id,
            operation_id=operation_id,
            parent_operation_id=parent_operation_id,
            source=source,
            outcome=outcome,
            reason=reason,
            agent=agent,
            requested_pillars=requested_pillars,
            safe_input=safe_input,
            before_projection=before_projection,
            delay_s=delay_s,
        )

    def _observe_availability_commit(
        self,
        *,
        source: AvailabilityObservationSource,
        outcome: AvailabilityObservationOutcome,
        reason: AvailabilityObservationReason,
        operation_id: str,
        parent_operation_id: str | None,
        before_projection: dict[str, AgentRenderStatus],
        after_projection: dict[str, AgentRenderStatus],
        agent: str | None = None,
    ) -> None:
        """Emit one safe, correlated availability terminal record."""
        logger.info(
            _AVAILABILITY_COMMIT_EVENT,
            app_instance_id=self._runtime_state.app_instance_id,
            operation_id=operation_id,
            parent_operation_id=parent_operation_id,
            source=source,
            outcome=outcome,
            reason=reason,
            agent=agent,
            before_projection=before_projection,
            after_projection=after_projection,
        )

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
        state["app"] = {"active_tab": tabs.active or "sessions", "human_filter": self.collect_human_filter()}
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
            widget.clear_cached_render()
            widget.refresh()
        for widget in self.query(BoxTabBar):
            widget.clear_cached_render()
            widget.refresh()

        # Refresh config content — its Rich styles depend on dark/light mode
        for widget in self.query(ConfigContent):
            widget.refresh()

        # Footer colors (agent pills, pane-theming cells, binding-key highlights)
        # are baked into child Static widgets — rebuild them for the new mode.
        for widget in self.query(TelecFooter):
            widget.refresh_theme()

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

    async def _shutdown(self) -> None:
        """Cancel the state-save timer before Textual prunes #main-tabs."""
        self._cancel_state_save_timer()
        await super()._shutdown()

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
