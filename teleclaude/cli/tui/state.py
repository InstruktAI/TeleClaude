"""TUI state model and reducer.

Required reads:
- @docs/project/design/tui-state-layout.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TypedDict, cast

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui.types import StickySessionInfo

logger = get_logger(__name__)


@dataclass(frozen=True)
class PreviewState:
    """Active preview state for the side pane."""

    session_id: str
    show_child: bool = True


@dataclass(frozen=True)
class DocPreviewState:
    """Active document preview state for the side pane."""

    doc_id: str
    command: str
    title: str


@dataclass(frozen=True)
class DocStickyInfo:
    """Sticky document preview entry."""

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
    selection_method: str = "arrow"  # "arrow" | "click"
    collapsed_sessions: set[str] = field(default_factory=set)
    sticky_sessions: list[StickySessionInfo] = field(default_factory=list)
    preview: PreviewState | None = None
    # Highlight state: sessions with active input/output highlights
    input_highlights: set[str] = field(default_factory=set)
    output_highlights: set[str] = field(default_factory=set)
    temp_output_highlights: set[str] = field(default_factory=set)  # For 3s streaming timer


@dataclass
class PreparationViewState:
    """State for Preparation view."""

    selected_index: int = 0
    scroll_offset: int = 0
    expanded_todos: set[str] = field(default_factory=set)
    file_pane_id: str | None = None
    preview: DocPreviewState | None = None
    sticky_previews: list[DocStickyInfo] = field(default_factory=list)


@dataclass
class TuiState:
    """Shared state for all TUI views."""

    sessions: SessionViewState = field(default_factory=SessionViewState)
    preparation: PreparationViewState = field(default_factory=PreparationViewState)


class IntentType(str, Enum):
    """Intent identifiers for reducer-driven state updates."""

    SET_PREVIEW = "set_preview"
    CLEAR_PREVIEW = "clear_preview"
    TOGGLE_STICKY = "toggle_sticky"
    SET_PREP_PREVIEW = "set_prep_preview"
    CLEAR_PREP_PREVIEW = "clear_prep_preview"
    TOGGLE_PREP_STICKY = "toggle_prep_sticky"
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
    SYNC_SESSIONS = "sync_sessions"
    SYNC_TODOS = "sync_todos"
    SET_FILE_PANE_ID = "set_file_pane_id"
    CLEAR_FILE_PANE_ID = "clear_file_pane_id"
    CLEAR_TEMP_HIGHLIGHT = "clear_temp_highlight"


@dataclass(frozen=True)
class Intent:
    """State transition request."""

    type: IntentType
    payload: "IntentPayload" = field(default_factory=lambda: cast(IntentPayload, {}))


class IntentPayload(TypedDict, total=False):
    session_id: str
    show_child: bool
    session_ids: list[str]
    todo_id: str
    todo_ids: list[str]
    view: str
    index: int
    offset: int
    method: str
    source: str
    pane_id: str
    doc_id: str
    command: str
    title: str
    reason: str  # SessionUpdateReason: "user_input", "agent_output", "agent_stopped", "state_change"


MAX_STICKY_PANES = 5


def _sticky_count(state: TuiState) -> int:
    return len(state.sessions.sticky_sessions) + len(state.preparation.sticky_previews)


def reduce_state(state: TuiState, intent: Intent) -> None:
    """Apply intent to state (pure state mutation only)."""
    t = intent.type
    p = intent.payload

    if t is IntentType.SET_PREVIEW:
        session_id = p.get("session_id")
        show_child = bool(p.get("show_child", True))
        if session_id:
            if _sticky_count(state) >= MAX_STICKY_PANES:
                return
            state.sessions.preview = PreviewState(session_id=session_id, show_child=show_child)
            state.preparation.preview = None
            # User viewed session: clear output highlight
            state.sessions.output_highlights.discard(session_id)
        return

    if t is IntentType.CLEAR_PREVIEW:
        state.sessions.preview = None
        return

    if t is IntentType.TOGGLE_STICKY:
        session_id = p.get("session_id")
        show_child = bool(p.get("show_child", True))
        if not session_id:
            return
        existing_idx = None
        for idx, sticky in enumerate(state.sessions.sticky_sessions):
            if sticky.session_id == session_id:
                existing_idx = idx
                break
        if existing_idx is not None:
            state.sessions.sticky_sessions.pop(existing_idx)
        else:
            if _sticky_count(state) >= MAX_STICKY_PANES:
                return
            state.sessions.sticky_sessions.append(StickySessionInfo(session_id, show_child))
            if state.sessions.preview and state.sessions.preview.session_id == session_id:
                state.sessions.preview = None
            # User viewed session: clear output highlight
            state.sessions.output_highlights.discard(session_id)
        return

    if t is IntentType.SET_PREP_PREVIEW:
        doc_id = p.get("doc_id")
        command = p.get("command")
        title = p.get("title") or ""
        if doc_id and command:
            if _sticky_count(state) >= MAX_STICKY_PANES:
                return
            state.preparation.preview = DocPreviewState(doc_id=doc_id, command=command, title=title)
            state.sessions.preview = None
        return

    if t is IntentType.CLEAR_PREP_PREVIEW:
        state.preparation.preview = None
        return

    if t is IntentType.TOGGLE_PREP_STICKY:
        doc_id = p.get("doc_id")
        command = p.get("command")
        title = p.get("title") or ""
        if not doc_id or not command:
            return
        existing_idx = None
        for idx, sticky in enumerate(state.preparation.sticky_previews):
            if sticky.doc_id == doc_id:
                existing_idx = idx
                break
        if existing_idx is not None:
            state.preparation.sticky_previews.pop(existing_idx)
        else:
            if _sticky_count(state) >= MAX_STICKY_PANES:
                return
            state.preparation.sticky_previews.append(DocStickyInfo(doc_id, command, title))
            if state.preparation.preview and state.preparation.preview.doc_id == doc_id:
                state.preparation.preview = None
        return

    if t is IntentType.COLLAPSE_SESSION:
        session_id = p.get("session_id")
        if session_id:
            state.sessions.collapsed_sessions.add(session_id)
        return

    if t is IntentType.EXPAND_SESSION:
        session_id = p.get("session_id")
        if session_id and session_id in state.sessions.collapsed_sessions:
            state.sessions.collapsed_sessions.discard(session_id)
        return

    if t is IntentType.EXPAND_ALL_SESSIONS:
        state.sessions.collapsed_sessions.clear()
        return

    if t is IntentType.COLLAPSE_ALL_SESSIONS:
        state.sessions.collapsed_sessions = set(p.get("session_ids", []))
        return

    if t is IntentType.EXPAND_TODO:
        todo_id = p.get("todo_id")
        if todo_id:
            state.preparation.expanded_todos.add(todo_id)
        return

    if t is IntentType.COLLAPSE_TODO:
        todo_id = p.get("todo_id")
        if todo_id:
            state.preparation.expanded_todos.discard(todo_id)
        return

    if t is IntentType.EXPAND_ALL_TODOS:
        todo_ids = p.get("todo_ids", [])
        state.preparation.expanded_todos.update(todo_ids)
        return

    if t is IntentType.COLLAPSE_ALL_TODOS:
        state.preparation.expanded_todos.clear()
        return

    if t is IntentType.SET_SELECTION:
        view = p.get("view")
        idx = p.get("index")
        session_id = p.get("session_id")
        source = p.get("source")
        if view == "sessions" and isinstance(idx, int):
            prev_session_id = state.sessions.selected_session_id
            state.sessions.selected_index = idx
            if isinstance(session_id, str):
                state.sessions.selected_session_id = session_id
                state.sessions.last_selection_session_id = session_id
                if source in ("user", "pane", "system"):
                    state.sessions.last_selection_source = source
                # User actively switched to a DIFFERENT session: clear output highlight
                # Skip if no previous selection (startup) or if same session (no real change)
                if source in ("user", "pane") and prev_session_id and session_id != prev_session_id:
                    if session_id in state.sessions.output_highlights:
                        logger.debug(
                            "SET_SELECTION clearing output_highlight for %s (source=%s, prev=%s)",
                            session_id[:8],
                            source,
                            prev_session_id[:8] if prev_session_id else None,
                        )
                    state.sessions.output_highlights.discard(session_id)
        if view == "preparation" and isinstance(idx, int):
            state.preparation.selected_index = idx
        return

    if t is IntentType.SET_SCROLL_OFFSET:
        view = p.get("view")
        offset = p.get("offset")
        if view == "sessions" and isinstance(offset, int):
            state.sessions.scroll_offset = offset
        if view == "preparation" and isinstance(offset, int):
            state.preparation.scroll_offset = offset
        return

    if t is IntentType.SET_SELECTION_METHOD:
        method = p.get("method")
        if method in ("arrow", "click"):
            state.sessions.selection_method = method
        return

    if t is IntentType.SESSION_ACTIVITY:
        session_id = p.get("session_id")
        reason = p.get("reason")
        if not session_id:
            return
        if reason == "user_input":
            # User sent input: highlight input, clear output highlight (user is waiting)
            state.sessions.input_highlights.add(session_id)
            state.sessions.output_highlights.discard(session_id)
            state.sessions.temp_output_highlights.discard(session_id)
            logger.debug("input_highlight ADDED for %s (reason=user_input)", session_id[:8])
        elif reason == "agent_output":
            # Streaming: just flicker temp, don't touch input/output
            state.sessions.temp_output_highlights.add(session_id)
            logger.debug("temp_output_highlight ADDED for %s (streaming)", session_id[:8])
        elif reason == "agent_stopped":
            # Agent finished: clear input, set output based on whether user is watching
            state.sessions.input_highlights.discard(session_id)

            # Check if user is watching this session
            is_selected = session_id == state.sessions.selected_session_id
            is_sticky = any(s.session_id == session_id for s in state.sessions.sticky_sessions)
            is_preview = state.sessions.preview and state.sessions.preview.session_id == session_id
            is_watching = is_selected or is_sticky or is_preview

            if is_watching:
                # Ephemeral 3-sec highlight
                state.sessions.output_highlights.discard(session_id)
                state.sessions.temp_output_highlights.add(session_id)
                logger.debug("temp_output_highlight ADDED for %s (agent_stopped, watching)", session_id[:8])
            else:
                # Permanent highlight
                state.sessions.temp_output_highlights.discard(session_id)
                state.sessions.output_highlights.add(session_id)
                logger.debug("output_highlight ADDED for %s (agent_stopped, not watching)", session_id[:8])
        # "state_change" reason: no highlight changes (status, title, etc.)
        return

    if t is IntentType.CLEAR_TEMP_HIGHLIGHT:
        session_id = p.get("session_id")
        if session_id:
            state.sessions.temp_output_highlights.discard(session_id)
            logger.debug("temp_output_highlight CLEARED for %s (timer expired)", session_id[:8])
        return

    if t is IntentType.SYNC_SESSIONS:
        session_ids = set(p.get("session_ids", []))
        if state.sessions.preview and state.sessions.preview.session_id not in session_ids:
            state.sessions.preview = None
        if state.sessions.sticky_sessions:
            state.sessions.sticky_sessions = [s for s in state.sessions.sticky_sessions if s.session_id in session_ids]
        state.sessions.collapsed_sessions.intersection_update(session_ids)
        # Log any input highlights that will be pruned
        pruned_input = state.sessions.input_highlights - session_ids
        if pruned_input:
            logger.info("input_highlights PRUNED by SYNC_SESSIONS: %s", [s[:8] for s in pruned_input])
        state.sessions.input_highlights.intersection_update(session_ids)
        state.sessions.output_highlights.intersection_update(session_ids)
        state.sessions.temp_output_highlights.intersection_update(session_ids)
        return

    if t is IntentType.SYNC_TODOS:
        todo_ids = set(p.get("todo_ids", []))
        state.preparation.expanded_todos.intersection_update(todo_ids)
        return

    if t is IntentType.SET_FILE_PANE_ID:
        pane_id = p.get("pane_id")
        if isinstance(pane_id, str):
            state.preparation.file_pane_id = pane_id
        return

    if t is IntentType.CLEAR_FILE_PANE_ID:
        state.preparation.file_pane_id = None
        return
