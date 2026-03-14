"""TUI state model and reducer.

Required reads:
- @docs/project/design/tui-state-layout.md
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, cast

from instrukt_ai_logging import get_logger
from typing_extensions import TypedDict

from teleclaude.cli.tui.types import StickySessionInfo

logger = get_logger(__name__)


@dataclass(frozen=True)
class PreviewState:
    """Active preview state for the side pane."""

    session_id: str


@dataclass(frozen=True)
class DocPreviewState:
    """Active document preview state for the side pane."""

    doc_id: str
    command: str
    title: str


@dataclass
class SessionViewState:
    """State for Sessions view."""

    selected_index: int = 0
    selected_session_id: str | None = None
    last_selection_source: str = "system"  # "user" | "pane" | "system"
    last_selection_session_id: str | None = None
    scroll_offset: int = 0
    selection_method: str = "arrow"  # "arrow" | "click" | "pane"
    collapsed_sessions: set[str] = field(default_factory=set)
    sticky_sessions: list[StickySessionInfo] = field(default_factory=list)
    preview: PreviewState | None = None
    # Highlight state: sessions with active input/output highlights
    input_highlights: set[str] = field(default_factory=set)
    output_highlights: set[str] = field(default_factory=set)
    temp_output_highlights: set[str] = field(default_factory=set)  # For streaming safety timer
    active_tool: dict[str, str] = field(default_factory=dict)  # session_id -> tool preview text
    activity_timer_reset: set[str] = field(default_factory=set)  # Sessions needing timer reset
    last_output_summary: dict[str, str] = field(default_factory=dict)  # session_id -> output summary from agent_stop
    last_output_summary_at: dict[str, str] = field(default_factory=dict)  # session_id -> ISO timestamp of last summary
    last_activity_at: dict[str, str] = field(
        default_factory=dict
    )  # session_id -> ISO timestamp of latest activity event


@dataclass
class PreparationViewState:
    """State for Preparation view."""

    selected_index: int = 0
    scroll_offset: int = 0
    expanded_todos: set[str] = field(default_factory=set)
    file_pane_id: str | None = None
    preview: DocPreviewState | None = None


@dataclass
class ConfigViewState:
    """State for Configuration view."""

    active_subtab: Literal["adapters", "people", "notifications", "environment", "validate"] = "adapters"
    guided_mode: bool = False


@dataclass
class TuiState:
    """Shared state for all TUI views."""

    sessions: SessionViewState = field(default_factory=SessionViewState)
    preparation: PreparationViewState = field(default_factory=PreparationViewState)
    config: ConfigViewState = field(default_factory=ConfigViewState)
    animation_mode: Literal["off", "periodic", "party"] = "off"  # "off", "periodic", "party"


class IntentType(str, Enum):
    """Intent identifiers for reducer-driven state updates."""

    SET_PREVIEW = "set_preview"
    CLEAR_PREVIEW = "clear_preview"
    TOGGLE_STICKY = "toggle_sticky"
    SET_PREP_PREVIEW = "set_prep_preview"
    CLEAR_PREP_PREVIEW = "clear_prep_preview"
    COLLAPSE_SESSION = "collapse_session"
    EXPAND_SESSION = "expand_session"
    EXPAND_ALL_SESSIONS = "expand_all_sessions"
    COLLAPSE_ALL_SESSIONS = "collapse_all_sessions"
    EXPAND_TODO = "expand_todo"
    COLLAPSE_TODO = "collapse_todo"
    EXPAND_ALL_TODOS = "expand_all_todos"
    COLLAPSE_ALL_TODOS = "collapse_all_todos"
    SET_SELECTION = "set_selection"
    SET_SCROLL_OFFSET = "set_scroll_offset"
    SET_SELECTION_METHOD = "set_selection_method"
    SESSION_ACTIVITY = "session_activity"
    AGENT_ACTIVITY = "agent_activity"
    SYNC_SESSIONS = "sync_sessions"
    SYNC_TODOS = "sync_todos"
    SET_FILE_PANE_ID = "set_file_pane_id"
    CLEAR_FILE_PANE_ID = "clear_file_pane_id"
    CLEAR_TEMP_HIGHLIGHT = "clear_temp_highlight"
    SET_ANIMATION_MODE = "set_animation_mode"
    SET_CONFIG_SUBTAB = "set_config_subtab"
    SET_CONFIG_GUIDED_MODE = "set_config_guided_mode"


@dataclass(frozen=True)
class Intent:
    """State transition request."""

    type: IntentType
    payload: IntentPayload = field(default_factory=lambda: cast(IntentPayload, {}))


class IntentPayload(TypedDict, total=False):
    session_id: str
    session_ids: list[str]
    todo_id: str
    todo_ids: list[str]
    view: str
    index: int
    offset: int
    method: str
    source: str
    active_agent: str | None
    pane_id: str
    doc_id: str
    command: str
    title: str
    focus_preview: bool
    reason: str  # Legacy field, no longer populated - use event_type in AGENT_ACTIVITY intents instead
    event_type: str  # AgentHookEventType: "user_prompt_submit", "tool_use", "tool_done", "agent_stop"
    tool_name: str | None  # Tool name for tool_use events
    tool_preview: str | None  # Optional tool preview text for tool_use events
    summary: str | None  # Output summary from agent_stop events
    mode: str  # Animation mode ("off", "periodic", "party")
    subtab: str  # Config subtab name
    enabled: bool  # Guided mode enabled state


MAX_STICKY_PANES = 5


def _sticky_count(state: TuiState) -> int:
    return len(state.sessions.sticky_sessions)


def _preserve_output_highlight_on_select(active_agent: str | None) -> bool:
    """Keep output highlight on selection-driven view actions for Codex only."""
    return (active_agent or "").strip().lower() == "codex"


def _handle_set_preview(state: TuiState, payload: IntentPayload) -> None:
    session_id = payload.get("session_id")
    active_agent = payload.get("active_agent")
    if not session_id or _sticky_count(state) >= MAX_STICKY_PANES:
        return
    state.sessions.preview = PreviewState(session_id=session_id)
    state.preparation.preview = None
    if not _preserve_output_highlight_on_select(active_agent):
        state.sessions.output_highlights.discard(session_id)


def _handle_clear_preview(state: TuiState, _payload: IntentPayload) -> None:
    state.sessions.preview = None


def _sticky_index(state: TuiState, session_id: str) -> int | None:
    for idx, sticky in enumerate(state.sessions.sticky_sessions):
        if sticky.session_id == session_id:
            return idx
    return None


def _handle_toggle_sticky(state: TuiState, payload: IntentPayload) -> None:
    session_id = payload.get("session_id")
    active_agent = payload.get("active_agent")
    if not session_id:
        return
    existing_idx = _sticky_index(state, session_id)
    if existing_idx is not None:
        state.sessions.sticky_sessions.pop(existing_idx)
        state.sessions.preview = PreviewState(session_id=session_id)
        return
    if _sticky_count(state) >= MAX_STICKY_PANES:
        return
    state.sessions.sticky_sessions.append(StickySessionInfo(session_id))
    if state.sessions.preview and state.sessions.preview.session_id == session_id:
        state.sessions.preview = None
    if not _preserve_output_highlight_on_select(active_agent):
        state.sessions.output_highlights.discard(session_id)


def _handle_set_prep_preview(state: TuiState, payload: IntentPayload) -> None:
    doc_id = payload.get("doc_id")
    command = payload.get("command")
    title = payload.get("title") or ""
    if not doc_id or not command or _sticky_count(state) >= MAX_STICKY_PANES:
        return
    state.preparation.preview = DocPreviewState(doc_id=doc_id, command=command, title=title)
    state.sessions.preview = None


def _handle_clear_prep_preview(state: TuiState, _payload: IntentPayload) -> None:
    state.preparation.preview = None


def _handle_session_collapse(state: TuiState, payload: IntentPayload, *, collapsed: bool) -> None:
    session_id = payload.get("session_id")
    if not session_id:
        return
    if collapsed:
        state.sessions.collapsed_sessions.add(session_id)
        return
    state.sessions.collapsed_sessions.discard(session_id)


def _handle_todo_expand(state: TuiState, payload: IntentPayload, *, expanded: bool) -> None:
    todo_id = payload.get("todo_id")
    if not todo_id:
        return
    if expanded:
        state.preparation.expanded_todos.add(todo_id)
        return
    state.preparation.expanded_todos.discard(todo_id)


def _handle_set_selection(state: TuiState, payload: IntentPayload) -> None:
    view = payload.get("view")
    idx = payload.get("index")
    if not isinstance(idx, int):
        return
    if view == "sessions":
        _set_session_selection(state, payload, idx)
        return
    if view == "preparation":
        state.preparation.selected_index = idx


def _set_session_selection(state: TuiState, payload: IntentPayload, idx: int) -> None:
    session_id = payload.get("session_id")
    source = payload.get("source")
    active_agent = payload.get("active_agent")
    prev_session_id = state.sessions.selected_session_id
    state.sessions.selected_index = idx
    if not isinstance(session_id, str):
        return
    state.sessions.selected_session_id = session_id
    state.sessions.last_selection_session_id = session_id
    if source in ("user", "pane", "system"):
        state.sessions.last_selection_source = source
    if (
        source in ("user", "pane")
        and prev_session_id
        and session_id != prev_session_id
        and not _preserve_output_highlight_on_select(active_agent)
    ):
        if session_id in state.sessions.output_highlights:
            logger.debug(
                "SET_SELECTION clearing output_highlight for %s (source=%s, prev=%s)",
                session_id,
                source,
                prev_session_id if prev_session_id else None,
            )
        state.sessions.output_highlights.discard(session_id)


def _handle_set_scroll_offset(state: TuiState, payload: IntentPayload) -> None:
    view = payload.get("view")
    offset = payload.get("offset")
    if not isinstance(offset, int):
        return
    if view == "sessions":
        state.sessions.scroll_offset = offset
    if view == "preparation":
        state.preparation.scroll_offset = offset


def _handle_set_selection_method(state: TuiState, payload: IntentPayload) -> None:
    method = payload.get("method")
    if method in ("arrow", "click", "pane"):
        state.sessions.selection_method = method


def _handle_session_activity(state: TuiState, payload: IntentPayload) -> None:
    session_id = payload.get("session_id")
    reason = payload.get("reason")
    if not session_id:
        return
    if reason == "user_input":
        state.sessions.input_highlights.add(session_id)
        state.sessions.output_highlights.discard(session_id)
        state.sessions.temp_output_highlights.discard(session_id)
        logger.debug("input_highlight ADDED for %s (reason=user_input)", session_id)
        return
    if reason == "tool_done":
        state.sessions.input_highlights.discard(session_id)
        state.sessions.output_highlights.discard(session_id)
        state.sessions.temp_output_highlights.add(session_id)
        logger.debug("temp_output_highlight ADDED for %s (tool_done)", session_id)
        return
    if reason == "agent_stopped":
        state.sessions.input_highlights.discard(session_id)
        state.sessions.temp_output_highlights.discard(session_id)
        state.sessions.output_highlights.add(session_id)
        logger.debug("output_highlight ADDED for %s (agent_stopped)", session_id)


def _handle_agent_activity(state: TuiState, payload: IntentPayload) -> None:
    session_id = payload.get("session_id")
    event_type = payload.get("event_type")
    if not session_id or not event_type:
        return
    timestamp = payload.get("timestamp")
    if isinstance(timestamp, str) and timestamp:
        state.sessions.last_activity_at[session_id] = timestamp
    if event_type == "user_prompt_submit":
        state.sessions.input_highlights.add(session_id)
        state.sessions.output_highlights.discard(session_id)
        state.sessions.temp_output_highlights.discard(session_id)
        logger.debug("input_highlight ADDED for %s (event=user_prompt_submit)", session_id)
        return
    if event_type == "tool_use":
        _handle_agent_tool_use(state, payload, session_id)
        return
    if event_type == "tool_done":
        state.sessions.input_highlights.discard(session_id)
        state.sessions.temp_output_highlights.add(session_id)
        state.sessions.activity_timer_reset.add(session_id)
        state.sessions.active_tool.pop(session_id, None)
        logger.debug("input_highlight CLEARED, active_tool CLEARED for %s (event=tool_done)", session_id)
        return
    if event_type == "agent_stop":
        _handle_agent_stop(state, payload, session_id)


def _handle_agent_tool_use(state: TuiState, payload: IntentPayload, session_id: str) -> None:
    tool_name = payload.get("tool_name")
    tool_preview = payload.get("tool_preview")
    state.sessions.input_highlights.discard(session_id)
    state.sessions.temp_output_highlights.add(session_id)
    state.sessions.activity_timer_reset.add(session_id)
    tool_label = None
    if isinstance(tool_preview, str) and tool_preview:
        tool_label = tool_preview
    elif isinstance(tool_name, str) and tool_name:
        tool_label = tool_name
    if tool_label:
        state.sessions.active_tool[session_id] = tool_label
    logger.debug(
        "input CLEARED, temp_output + active_tool ADDED for %s (event=tool_use, tool=%s)",
        session_id,
        tool_label,
    )


def _handle_agent_stop(state: TuiState, payload: IntentPayload, session_id: str) -> None:
    state.sessions.input_highlights.discard(session_id)
    state.sessions.temp_output_highlights.discard(session_id)
    state.sessions.active_tool.pop(session_id, None)
    state.sessions.output_highlights.add(session_id)
    summary = payload.get("summary")
    if isinstance(summary, str) and summary:
        state.sessions.last_output_summary[session_id] = summary
    timestamp = payload.get("timestamp")
    if isinstance(timestamp, str) and timestamp:
        state.sessions.last_output_summary_at[session_id] = timestamp
    logger.debug("output_highlight ADDED for %s (event=agent_stop)", session_id)


def _handle_clear_temp_highlight(state: TuiState, payload: IntentPayload) -> None:
    session_id = payload.get("session_id")
    if not session_id:
        return
    state.sessions.temp_output_highlights.discard(session_id)
    state.sessions.active_tool.pop(session_id, None)
    state.sessions.output_highlights.add(session_id)
    logger.debug(
        "temp_output_highlight CLEARED + output_highlight ADDED for %s (timer expired safety-net)",
        session_id,
    )


def _prune_mapping(mapping: dict[str, str], session_ids: set[str]) -> None:
    stale_ids = set(mapping) - session_ids
    for session_id in stale_ids:
        del mapping[session_id]


def _handle_sync_sessions(state: TuiState, payload: IntentPayload) -> None:
    session_ids = set(payload.get("session_ids", []))
    if state.sessions.preview and state.sessions.preview.session_id not in session_ids:
        state.sessions.preview = None
    if state.sessions.sticky_sessions:
        state.sessions.sticky_sessions = [s for s in state.sessions.sticky_sessions if s.session_id in session_ids]
    state.sessions.collapsed_sessions.intersection_update(session_ids)
    pruned_input = state.sessions.input_highlights - session_ids
    if pruned_input:
        logger.info("input_highlights PRUNED by SYNC_SESSIONS: %s", pruned_input)
    state.sessions.input_highlights.intersection_update(session_ids)
    state.sessions.output_highlights.intersection_update(session_ids)
    state.sessions.temp_output_highlights.intersection_update(session_ids)
    state.sessions.activity_timer_reset.intersection_update(session_ids)
    _prune_mapping(state.sessions.last_output_summary, session_ids)
    _prune_mapping(state.sessions.last_output_summary_at, session_ids)
    _prune_mapping(state.sessions.last_activity_at, session_ids)


def _handle_set_file_pane_id(state: TuiState, payload: IntentPayload) -> None:
    pane_id = payload.get("pane_id")
    if isinstance(pane_id, str):
        state.preparation.file_pane_id = pane_id


def _handle_set_animation_mode(state: TuiState, payload: IntentPayload) -> None:
    mode = payload.get("mode")
    if mode in ("off", "periodic", "party"):
        state.animation_mode = mode  # type: ignore


def _handle_set_config_subtab(state: TuiState, payload: IntentPayload) -> None:
    subtab = payload.get("subtab")
    if subtab in ("adapters", "people", "notifications", "environment", "validate"):
        state.config.active_subtab = subtab  # type: ignore


def _handle_set_config_guided_mode(state: TuiState, payload: IntentPayload) -> None:
    enabled = payload.get("enabled")
    if isinstance(enabled, bool):
        state.config.guided_mode = enabled


def _handle_expand_session(state: TuiState, payload: IntentPayload) -> None:
    _handle_session_collapse(state, payload, collapsed=False)


def _handle_expand_all_sessions(state: TuiState, _payload: IntentPayload) -> None:
    state.sessions.collapsed_sessions.clear()


def _handle_collapse_all_sessions(state: TuiState, payload: IntentPayload) -> None:
    state.sessions.collapsed_sessions = set(payload.get("session_ids", []))


def _handle_expand_todo(state: TuiState, payload: IntentPayload) -> None:
    _handle_todo_expand(state, payload, expanded=True)


def _handle_collapse_todo(state: TuiState, payload: IntentPayload) -> None:
    _handle_todo_expand(state, payload, expanded=False)


def _handle_expand_all_todos(state: TuiState, payload: IntentPayload) -> None:
    state.preparation.expanded_todos.update(payload.get("todo_ids", []))


def _handle_collapse_all_todos(state: TuiState, _payload: IntentPayload) -> None:
    state.preparation.expanded_todos.clear()


def _handle_sync_expanded_todos(state: TuiState, payload: IntentPayload) -> None:
    state.preparation.expanded_todos.intersection_update(set(payload.get("todo_ids", [])))


def _handle_clear_file_pane_id(state: TuiState, _payload: IntentPayload) -> None:
    state.preparation.file_pane_id = None


def reduce_state(state: TuiState, intent: Intent) -> None:
    """Apply intent to state (pure state mutation only)."""
    handlers: dict[IntentType, Callable[[TuiState, IntentPayload], None]] = {
        IntentType.SET_PREVIEW: _handle_set_preview,
        IntentType.CLEAR_PREVIEW: _handle_clear_preview,
        IntentType.TOGGLE_STICKY: _handle_toggle_sticky,
        IntentType.SET_PREP_PREVIEW: _handle_set_prep_preview,
        IntentType.CLEAR_PREP_PREVIEW: _handle_clear_prep_preview,
        IntentType.COLLAPSE_SESSION: lambda s, p: _handle_session_collapse(s, p, collapsed=True),
        IntentType.EXPAND_SESSION: _handle_expand_session,
        IntentType.EXPAND_ALL_SESSIONS: _handle_expand_all_sessions,
        IntentType.COLLAPSE_ALL_SESSIONS: _handle_collapse_all_sessions,
        IntentType.EXPAND_TODO: _handle_expand_todo,
        IntentType.COLLAPSE_TODO: _handle_collapse_todo,
        IntentType.EXPAND_ALL_TODOS: _handle_expand_all_todos,
        IntentType.COLLAPSE_ALL_TODOS: _handle_collapse_all_todos,
        IntentType.SET_SELECTION: _handle_set_selection,
        IntentType.SET_SCROLL_OFFSET: _handle_set_scroll_offset,
        IntentType.SET_SELECTION_METHOD: _handle_set_selection_method,
        IntentType.SESSION_ACTIVITY: _handle_session_activity,
        IntentType.AGENT_ACTIVITY: _handle_agent_activity,
        IntentType.SYNC_SESSIONS: _handle_sync_sessions,
        IntentType.SYNC_TODOS: _handle_sync_expanded_todos,
        IntentType.SET_FILE_PANE_ID: _handle_set_file_pane_id,
        IntentType.CLEAR_FILE_PANE_ID: _handle_clear_file_pane_id,
        IntentType.CLEAR_TEMP_HIGHLIGHT: _handle_clear_temp_highlight,
        IntentType.SET_ANIMATION_MODE: _handle_set_animation_mode,
        IntentType.SET_CONFIG_SUBTAB: _handle_set_config_subtab,
        IntentType.SET_CONFIG_GUIDED_MODE: _handle_set_config_guided_mode,
    }
    handler = handlers.get(intent.type)
    if handler:
        handler(state, intent.payload)
