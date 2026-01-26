"""TUI state model and reducer.

Required reads:
- @docs/project/architecture/tui-state-layout.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TypedDict, cast

from teleclaude.cli.tui.types import StickySessionInfo


@dataclass(frozen=True)
class PreviewState:
    """Active preview state for the side pane."""

    session_id: str
    show_child: bool = True


@dataclass
class SessionViewState:
    """State for Sessions view."""

    selected_index: int = 0
    scroll_offset: int = 0
    selection_method: str = "arrow"  # "arrow" | "click"
    collapsed_sessions: set[str] = field(default_factory=set)
    sticky_sessions: list[StickySessionInfo] = field(default_factory=list)
    preview: PreviewState | None = None


@dataclass
class PreparationViewState:
    """State for Preparation view."""

    selected_index: int = 0
    scroll_offset: int = 0
    expanded_todos: set[str] = field(default_factory=set)
    file_pane_id: str | None = None


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
    SYNC_SESSIONS = "sync_sessions"
    SYNC_TODOS = "sync_todos"
    SET_FILE_PANE_ID = "set_file_pane_id"
    CLEAR_FILE_PANE_ID = "clear_file_pane_id"


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
    pane_id: str


def reduce_state(state: TuiState, intent: Intent) -> None:
    """Apply intent to state (pure state mutation only)."""
    t = intent.type
    p = intent.payload

    if t is IntentType.SET_PREVIEW:
        session_id = p.get("session_id")
        show_child = bool(p.get("show_child", True))
        if session_id:
            state.sessions.preview = PreviewState(session_id=session_id, show_child=show_child)
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
            state.sessions.sticky_sessions.append(StickySessionInfo(session_id, show_child))
            if state.sessions.preview and state.sessions.preview.session_id == session_id:
                state.sessions.preview = None
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
        if view == "sessions" and isinstance(idx, int):
            state.sessions.selected_index = idx
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

    if t is IntentType.SYNC_SESSIONS:
        session_ids = set(p.get("session_ids", []))
        if state.sessions.preview and state.sessions.preview.session_id not in session_ids:
            state.sessions.preview = None
        if state.sessions.sticky_sessions:
            state.sessions.sticky_sessions = [s for s in state.sessions.sticky_sessions if s.session_id in session_ids]
        state.sessions.collapsed_sessions.intersection_update(session_ids)
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
