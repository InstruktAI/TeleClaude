"""Snapshot-style tests for TUI view rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.cli.models import ComputerInfo, ProjectWithTodosInfo, SessionInfo, TodoInfo
from teleclaude.cli.tui.controller import TuiController
from teleclaude.cli.tui.state import TuiState
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.core.origins import InputOrigin
from tests.snapshots import assert_snapshot, normalize_lines

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "snapshots" / "tui"


class _MockFocus:
    def __init__(self) -> None:
        self.computer = None
        self.project = None
        self.stack = []


class _MockPaneManager:
    def __init__(self) -> None:
        self.is_available = False


@pytest.fixture
def sessions_view() -> SessionsView:
    state = TuiState()
    pane_manager = _MockPaneManager()
    controller = TuiController(state, pane_manager, lambda _name: None)
    view = SessionsView(
        api=None,  # Not needed for render tests
        agent_availability={},
        focus=_MockFocus(),
        pane_manager=pane_manager,
        state=state,
        controller=controller,
    )
    view.sticky_sessions = []
    return view


@pytest.fixture
def preparation_view() -> PreparationView:
    state = TuiState()
    pane_manager = _MockPaneManager()
    controller = TuiController(state, pane_manager, lambda _name: None)
    return PreparationView(
        api=None,  # Not needed for render tests
        agent_availability={},
        focus=_MockFocus(),
        pane_manager=pane_manager,
        state=state,
        controller=controller,
    )


def _make_computer(name: str, *, is_local: bool) -> ComputerInfo:
    return ComputerInfo(
        name=name,
        status="online",
        user="testuser",
        host="test.local",
        is_local=is_local,
        tmux_binary="tmux",
    )


def _make_project(computer: str, path: str) -> ProjectWithTodosInfo:
    return ProjectWithTodosInfo(
        computer=computer,
        name="TeleClaude",
        path=path,
        description=None,
        todos=[],
    )


def _make_session(
    session_id: str,
    *,
    project_path: str,
    title: str,
    initiator_session_id: str | None = None,
    last_input: str | None = None,
    last_output_summary: str | None = None,
) -> SessionInfo:
    return SessionInfo(
        session_id=session_id,
        last_input_origin=InputOrigin.TELEGRAM.value,
        title=title,
        project_path=project_path,
        thinking_mode="slow",
        active_agent="claude",
        status="active",
        created_at=None,
        last_activity=None,
        last_input=last_input,
        last_input_at=None,
        last_output_summary=last_output_summary,
        last_output_summary_at=None,
        tmux_session_name=None,
        initiator_session_id=initiator_session_id,
        computer="local",
    )


def _make_todo(
    slug: str,
    *,
    status: str,
    has_requirements: bool,
    has_impl_plan: bool,
    build_status: str | None = None,
    review_status: str | None = None,
) -> TodoInfo:
    return TodoInfo(
        slug=slug,
        status=status,
        description=None,
        computer="remote-1",
        project_path="/Users/tester/TeleClaude",
        has_requirements=has_requirements,
        has_impl_plan=has_impl_plan,
        build_status=build_status,
        review_status=review_status,
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sessions_view_snapshot_basic(sessions_view: SessionsView) -> None:
    computers = [_make_computer("local", is_local=True)]
    projects = [_make_project("local", "/Users/tester/TeleClaude")]
    sessions = [
        _make_session(
            "sess-1",
            project_path="/Users/tester/TeleClaude",
            title="Bootstrap",
            last_input="ls",
            last_output_summary="ok",
        )
    ]

    await sessions_view.refresh(computers, projects, sessions)
    lines = sessions_view.get_render_lines(width=80, height=12)

    snapshot = normalize_lines(lines)
    assert_snapshot(snapshot, SNAPSHOT_DIR / "sessions_basic.txt")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sessions_view_snapshot_nested(sessions_view: SessionsView) -> None:
    computers = [_make_computer("local", is_local=True)]
    projects = [_make_project("local", "/Users/tester/TeleClaude")]
    sessions = [
        _make_session(
            "sess-parent",
            project_path="/Users/tester/TeleClaude",
            title="Orchestrator",
        ),
        _make_session(
            "sess-child",
            project_path="/Users/tester/TeleClaude",
            title="Worker",
            initiator_session_id="sess-parent",
        ),
    ]

    await sessions_view.refresh(computers, projects, sessions)
    lines = sessions_view.get_render_lines(width=80, height=12)

    snapshot = normalize_lines(lines)
    assert_snapshot(snapshot, SNAPSHOT_DIR / "sessions_nested.txt")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_sessions_view_snapshot_collapsed(sessions_view: SessionsView) -> None:
    computers = [_make_computer("local", is_local=True)]
    projects = [_make_project("local", "/Users/tester/TeleClaude")]
    sessions = [
        _make_session(
            "sess-1",
            project_path="/Users/tester/TeleClaude",
            title="Collapsed",
            last_input="echo hi",
            last_output_summary="hi",
        )
    ]

    await sessions_view.refresh(computers, projects, sessions)
    sessions_view.collapsed_sessions = {"sess-1"}
    lines = sessions_view.get_render_lines(width=80, height=8)

    snapshot = normalize_lines(lines)
    assert_snapshot(snapshot, SNAPSHOT_DIR / "sessions_collapsed.txt")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_preparation_view_snapshot_basic(preparation_view: PreparationView) -> None:
    computers = [_make_computer("remote-1", is_local=False)]
    todo = _make_todo("bootstrap", status="ready", has_requirements=True, has_impl_plan=False)
    projects = [
        ProjectWithTodosInfo(
            computer="remote-1",
            name="TeleClaude",
            path="/Users/tester/TeleClaude",
            description=None,
            todos=[todo],
        )
    ]

    await preparation_view.refresh(computers, projects, sessions=[])
    lines = preparation_view.get_render_lines(width=80, height=10)

    snapshot = normalize_lines(lines)
    assert_snapshot(snapshot, SNAPSHOT_DIR / "prep_basic.txt")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_preparation_view_snapshot_expanded_files(preparation_view: PreparationView) -> None:
    computers = [_make_computer("remote-1", is_local=False)]
    todo = _make_todo("design", status="pending", has_requirements=True, has_impl_plan=True)
    projects = [
        ProjectWithTodosInfo(
            computer="remote-1",
            name="TeleClaude",
            path="/Users/tester/TeleClaude",
            description=None,
            todos=[todo],
        )
    ]

    await preparation_view.refresh(computers, projects, sessions=[])
    preparation_view.expanded_todos = {"design"}
    preparation_view.rebuild_for_focus()
    lines = preparation_view.get_render_lines(width=80, height=12)

    snapshot = normalize_lines(lines)
    assert_snapshot(snapshot, SNAPSHOT_DIR / "prep_expanded_files.txt")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_preparation_view_snapshot_build_review(preparation_view: PreparationView) -> None:
    computers = [_make_computer("remote-1", is_local=False)]
    todo = _make_todo(
        "release",
        status="in_progress",
        has_requirements=False,
        has_impl_plan=True,
        build_status="pending",
        review_status="approved",
    )
    projects = [
        ProjectWithTodosInfo(
            computer="remote-1",
            name="TeleClaude",
            path="/Users/tester/TeleClaude",
            description=None,
            todos=[todo],
        )
    ]

    await preparation_view.refresh(computers, projects, sessions=[])
    lines = preparation_view.get_render_lines(width=80, height=12)

    snapshot = normalize_lines(lines)
    assert_snapshot(snapshot, SNAPSHOT_DIR / "prep_build_review.txt")
