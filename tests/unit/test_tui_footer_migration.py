"""Coverage for Textual footer migration behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from textual.widgets import Footer

from teleclaude.cli.models import ComputerInfo, ProjectInfo, SessionInfo
from teleclaude.cli.tui.app import TelecApp
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.tree import ComputerDisplayInfo
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.session_row import SessionRow
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow
from teleclaude.core.next_machine.core import DOR_READY_THRESHOLD


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telec_app_uses_compact_textual_footer() -> None:
    api = SimpleNamespace(
        connect=AsyncMock(),
        start_websocket=MagicMock(),
        list_computers=AsyncMock(return_value=[]),
        list_projects_with_todos=AsyncMock(return_value=[]),
        list_sessions=AsyncMock(return_value=[]),
        get_agent_availability=AsyncMock(return_value={}),
        list_jobs=AsyncMock(return_value=[]),
        get_settings=AsyncMock(return_value=SimpleNamespace(tts=SimpleNamespace(enabled=False))),
    )
    app = TelecApp(api)  # type: ignore[arg-type]

    async with app.run_test():
        footer = app.query_one(Footer)
        assert footer.compact is True
        assert footer.show_command_palette is False
        assert not app.query("#action-bar")


def _computer_header() -> ComputerHeader:
    return ComputerHeader(
        data=ComputerDisplayInfo(
            computer=ComputerInfo(
                name="local",
                status="online",
                user="tester",
                host="localhost",
                is_local=True,
                tmux_binary="tmux",
            ),
            session_count=1,
            recent_activity=False,
        )
    )


def _project_header(path: str = "/tmp/project") -> ProjectHeader:
    return ProjectHeader(
        project=ProjectInfo(computer="local", name="project", path=path, description=None),
        session_count=1,
    )


def _session_row() -> SessionRow:
    return SessionRow(
        session=SessionInfo(
            session_id="sess-1",
            title="Session One",
            status="active",
            computer="local",
            project_path="/tmp/project",
            tmux_session_name="tc_sess_1",
        ),
        display_index="1",
        depth=2,
    )


def _todo_row(*, slug: str = "todo-1", dor: int = DOR_READY_THRESHOLD) -> TodoRow:
    return TodoRow(
        todo=TodoItem(
            slug=slug,
            status=TodoStatus.READY,
            description="todo",
            has_requirements=True,
            has_impl_plan=True,
            dor_score=dor,
            files=["requirements.md"],
        )
    )


def _todo_file_row(*, slug: str = "todo-1") -> TodoFileRow:
    return TodoFileRow(
        filepath=f"/tmp/project/todos/{slug}/requirements.md",
        filename="requirements.md",
        slug=slug,
    )


@pytest.mark.unit
def test_sessions_check_action_is_context_sensitive() -> None:
    view = SessionsView()
    computer = _computer_header()
    project = _project_header()
    session = _session_row()
    view._nav_items = [computer, project, session]

    view.cursor_index = 0
    assert view.check_action("restart_all", ()) is True
    assert view.check_action("new_session", ()) is False
    assert view.check_action("focus_pane", ()) is True
    assert view.check_action("kill_session", ()) is False
    assert view.check_action("restart_session", ()) is False

    view.cursor_index = 1
    assert view.check_action("new_session", ()) is True
    assert view.check_action("restart_all", ()) is False
    assert view.check_action("focus_pane", ()) is True
    assert view.check_action("kill_session", ()) is False
    assert view.check_action("restart_session", ()) is False

    view.cursor_index = 2
    assert view.check_action("kill_session", ()) is True
    assert view.check_action("restart_session", ()) is True
    assert view.check_action("focus_pane", ()) is True
    assert view.check_action("new_session", ()) is False
    assert view.check_action("restart_all", ()) is False


@pytest.mark.unit
def test_sessions_focus_pane_routes_to_header_default_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    view = SessionsView()
    view._nav_items = [_computer_header(), _project_header(), _session_row()]
    called: list[str] = []

    monkeypatch.setattr(view, "action_restart_all", lambda: called.append("restart_all"))
    monkeypatch.setattr(view, "action_new_session", lambda: called.append("new_session"))

    view.cursor_index = 0
    view.action_focus_pane()
    assert called == ["restart_all"]

    view.cursor_index = 1
    view.action_focus_pane()
    assert called == ["restart_all", "new_session"]


@pytest.mark.unit
def test_sessions_default_action_tracks_cursor_context() -> None:
    view = SessionsView()
    view._nav_items = [_computer_header(), _project_header(), _session_row()]

    view.cursor_index = 0
    assert view._default_footer_action() == "restart_all"
    view.cursor_index = 1
    assert view._default_footer_action() == "new_session"
    view.cursor_index = 2
    assert view._default_footer_action() == "focus_pane"


@pytest.mark.unit
def test_preparation_check_action_is_context_sensitive() -> None:
    view = PreparationView()
    project = _project_header()
    todo = _todo_row()
    file_row = _todo_file_row()
    view._nav_items = [project, todo, file_row]

    view.cursor_index = 0
    assert view.check_action("new_todo", ()) is True
    assert view.check_action("remove_todo", ()) is False
    assert view.check_action("activate", ()) is False
    assert view.check_action("preview_file", ()) is False

    view.cursor_index = 1
    assert view.check_action("prepare", ()) is True
    assert view.check_action("start_work", ()) is True
    assert view.check_action("remove_todo", ()) is True
    assert view.check_action("preview_file", ()) is False

    view.cursor_index = 2
    assert view.check_action("prepare", ()) is True
    assert view.check_action("start_work", ()) is True
    assert view.check_action("remove_todo", ()) is True
    assert view.check_action("activate", ()) is True
    assert view.check_action("preview_file", ()) is True
    assert view.check_action("new_todo", ()) is False
    assert view.check_action("new_bug", ()) is False


@pytest.mark.unit
def test_preparation_default_action_tracks_cursor_context() -> None:
    view = PreparationView()
    view._nav_items = [_project_header(), _todo_row(), _todo_file_row()]

    view.cursor_index = 0
    assert view._default_footer_action() == "new_todo"
    view.cursor_index = 1
    assert view._default_footer_action() == "activate"
    view.cursor_index = 2
    assert view._default_footer_action() == "activate"


@pytest.mark.unit
def test_prepare_on_project_opens_modal_without_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    view = PreparationView()
    view._nav_items = [_project_header("/tmp/project")]
    view.cursor_index = 0

    captured: dict[str, str] = {}
    monkeypatch.setattr(view, "_open_session_modal", lambda **kwargs: captured.update(kwargs))

    view.action_prepare()

    assert captured["computer"] == "local"
    assert captured["project_path"] == "/tmp/project"
    assert captured["default_message"] == "/next-prepare"


@pytest.mark.unit
def test_start_work_on_project_opens_modal_without_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    view = PreparationView()
    view._nav_items = [_project_header("/tmp/project")]
    view.cursor_index = 0

    captured: dict[str, str] = {}
    monkeypatch.setattr(view, "_open_session_modal", lambda **kwargs: captured.update(kwargs))

    view.action_start_work()

    assert captured["computer"] == "local"
    assert captured["project_path"] == "/tmp/project"
    assert captured["default_message"] == "/next-work"


@pytest.mark.unit
def test_start_work_on_file_row_uses_parent_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    view = PreparationView()
    project = _project_header("/tmp/project")
    todo = _todo_row(slug="todo-2")
    file_row = _todo_file_row(slug="todo-2")
    view._nav_items = [project, todo, file_row]
    view.cursor_index = 2
    view._slug_to_project_path["todo-2"] = "/tmp/project"
    view._slug_to_computer["todo-2"] = "local"

    captured: dict[str, str] = {}
    monkeypatch.setattr(view, "_open_session_modal", lambda **kwargs: captured.update(kwargs))

    view.action_start_work()

    assert captured["computer"] == "local"
    assert captured["project_path"] == "/tmp/project"
    assert captured["default_message"] == "/next-work todo-2"
