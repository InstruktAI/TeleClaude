"""Regression tests for tab activation and session auto-select behavior."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TypedDict
from unittest.mock import AsyncMock, MagicMock

import pytest
from textual.widgets import TabbedContent, TabPane

from teleclaude.cli.models import ComputerInfo, ProjectWithTodosInfo, SessionInfo
from teleclaude.cli.tui.app import TelecApp
from teleclaude.cli.tui.messages import SessionStarted
from teleclaude.cli.tui.views.sessions import SessionsView


class _PersistedStatusBarState(TypedDict):
    animation_mode: str
    pane_theming_mode: str


class _PersistedAppState(TypedDict):
    active_tab: str


class _PersistedState(TypedDict):
    sessions: dict[str, str]
    preparation: dict[str, str]
    status_bar: _PersistedStatusBarState
    app: _PersistedAppState


def _api_stub(session: SessionInfo) -> SimpleNamespace:
    computer = ComputerInfo(
        name="local",
        status="online",
        user="tester",
        host="localhost",
        is_local=True,
        tmux_binary="tmux",
    )
    project = ProjectWithTodosInfo(
        computer="local",
        name="TeleClaude",
        path="/tmp/project",
        description=None,
        todos=[],
    )
    return SimpleNamespace(
        connect=AsyncMock(),
        start_websocket=MagicMock(),
        list_computers=AsyncMock(return_value=[computer]),
        list_projects_with_todos=AsyncMock(return_value=[project]),
        list_sessions=AsyncMock(return_value=[session]),
        get_agent_availability=AsyncMock(return_value={}),
        list_jobs=AsyncMock(return_value=[]),
        get_settings=AsyncMock(return_value=SimpleNamespace(tts=SimpleNamespace(enabled=False))),
        close=AsyncMock(),
    )


def _persisted_state(active_tab: str) -> _PersistedState:
    return {
        "sessions": {},
        "preparation": {},
        "status_bar": {"animation_mode": "off", "pane_theming_mode": "off"},
        "app": {"active_tab": active_tab},
    }


def _root_session() -> SessionInfo:
    return SessionInfo(
        session_id="sess-root-1",
        title="Root Session",
        status="active",
        computer="local",
        project_path="/tmp/project",
        tmux_session_name="tc_sess-root-1",
        initiator_session_id=None,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_started_skips_auto_select_when_sessions_tab_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _root_session()
    monkeypatch.setattr("teleclaude.cli.tui.app.load_state", lambda: _persisted_state("preparation"))
    app = TelecApp(_api_stub(session))  # type: ignore[arg-type]

    async with app.run_test() as pilot:
        tabs = app.query_one("#main-tabs", TabbedContent)
        assert tabs.active == "preparation"

        sessions_view = app.query_one("#sessions-view", SessionsView)
        calls: list[str] = []
        monkeypatch.setattr(sessions_view, "request_select_session", lambda session_id: calls.append(session_id))

        app.on_session_started(SessionStarted(session))
        await pilot.pause(0.1)

        assert calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_started_auto_selects_when_sessions_tab_active(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _root_session()
    monkeypatch.setattr("teleclaude.cli.tui.app.load_state", lambda: _persisted_state("sessions"))
    app = TelecApp(_api_stub(session))  # type: ignore[arg-type]

    async with app.run_test() as pilot:
        tabs = app.query_one("#main-tabs", TabbedContent)
        assert tabs.active == "sessions"

        sessions_view = app.query_one("#sessions-view", SessionsView)
        calls: list[str] = []
        monkeypatch.setattr(sessions_view, "request_select_session", lambda session_id: calls.append(session_id))

        app.on_session_started(SessionStarted(session))
        await pilot.pause(0.1)

        assert calls == [session.session_id]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stale_tab_activated_event_does_not_switch_tabs(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _root_session()
    monkeypatch.setattr("teleclaude.cli.tui.app.load_state", lambda: _persisted_state("preparation"))
    app = TelecApp(_api_stub(session))  # type: ignore[arg-type]

    async with app.run_test() as pilot:
        tabs = app.query_one("#main-tabs", TabbedContent)
        assert tabs.active == "preparation"

        stale_event = SimpleNamespace(pane=TabPane("Sessions", id="sessions"))
        app.on_tabbed_content_tab_activated(stale_event)  # type: ignore[arg-type]
        await pilot.pause(0.05)

        tabs = app.query_one("#main-tabs", TabbedContent)
        assert tabs.active == "preparation"
