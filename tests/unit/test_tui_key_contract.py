"""Tests for tui-footer-key-contract-restoration behavioral coverage.

Covers:
- SessionsView.check_action() per node type (Task 4.1)
- PreparationView.check_action() including computer tier (Task 4.1)
- Hidden-but-active keys contract (Task 4.1)
- _default_footer_action() per node type (Task 4.1)
- StartSessionModal path_mode validation (Task 4.2)
- NewProjectModal validation (Task 4.2)
- Preparation tree computer grouping structure (Task 4.3)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.cli.models import ComputerInfo, ProjectInfo, ProjectWithTodosInfo, SessionInfo
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.tree import ComputerDisplayInfo
from teleclaude.cli.tui.types import TodoStatus
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.modals import NewProjectModal, StartSessionModal
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.session_row import SessionRow
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow

# --- Helpers ---


def _computer_header(name: str = "local") -> ComputerHeader:
    return ComputerHeader(
        data=ComputerDisplayInfo(
            computer=ComputerInfo(
                name=name,
                status="online",
                user="tester",
                host="localhost",
                is_local=(name == "local"),
                tmux_binary="tmux",
            ),
            session_count=1,
            recent_activity=False,
        )
    )


def _project_header(path: str = "/tmp/project", computer: str = "local") -> ProjectHeader:
    return ProjectHeader(
        project=ProjectInfo(computer=computer, name="project", path=path, description=None),
        session_count=0,
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


def _todo_row(*, slug: str = "todo-1", dor: int = 9) -> TodoRow:
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


def _project_with_todos(
    *,
    computer: str = "local",
    name: str = "project",
    path: str = "/tmp/project",
    slugs: list[str] | None = None,
) -> ProjectWithTodosInfo:
    from teleclaude.api_models import ProjectWithTodosDTO, TodoDTO

    todos = [
        TodoDTO(
            slug=s,
            status="pending",
            has_requirements=True,
            has_impl_plan=False,
        )
        for s in (slugs or [])
    ]
    return ProjectWithTodosDTO(
        computer=computer,
        name=name,
        path=path,
        todos=todos,
    )


# ============================================================
# Task 4.1: SessionsView.check_action() per node type
# ============================================================


@pytest.mark.unit
def test_sessions_check_action_computer_node() -> None:
    view = SessionsView()
    computer = _computer_header()
    view._nav_items = [computer]
    view.cursor_index = 0

    # Computer enables focus_pane (Enter → path-mode modal), new_project, restart_all
    assert view.check_action("focus_pane", ()) is True
    assert view.check_action("new_project", ()) is True
    assert view.check_action("restart_all", ()) is True
    # Computer disables session-specific and project-specific actions
    assert view.check_action("new_session", ()) is False
    assert view.check_action("kill_session", ()) is False
    assert view.check_action("restart_session", ()) is False
    assert view.check_action("toggle_preview", ()) is False
    assert view.check_action("restart_project", ()) is False


@pytest.mark.unit
def test_sessions_check_action_project_node() -> None:
    view = SessionsView()
    project = _project_header()
    view._nav_items = [project]
    view.cursor_index = 0

    assert view.check_action("new_session", ()) is True
    assert view.check_action("focus_pane", ()) is True
    assert view.check_action("restart_project", ()) is True
    # Project disables session and computer actions
    assert view.check_action("kill_session", ()) is False
    assert view.check_action("restart_session", ()) is False
    assert view.check_action("toggle_preview", ()) is False
    assert view.check_action("restart_all", ()) is False
    assert view.check_action("new_project", ()) is False


@pytest.mark.unit
def test_sessions_check_action_session_node() -> None:
    view = SessionsView()
    session = _session_row()
    view._nav_items = [session]
    view.cursor_index = 0

    assert view.check_action("kill_session", ()) is True
    assert view.check_action("restart_session", ()) is True
    assert view.check_action("toggle_preview", ()) is True
    assert view.check_action("focus_pane", ()) is True
    # Session disables non-session actions
    assert view.check_action("new_session", ()) is False
    assert view.check_action("restart_all", ()) is False
    assert view.check_action("restart_project", ()) is False
    assert view.check_action("new_project", ()) is False


@pytest.mark.unit
def test_sessions_default_action_per_node() -> None:
    view = SessionsView()
    computer = _computer_header()
    project = _project_header()
    session = _session_row()
    view._nav_items = [computer, project, session]

    view.cursor_index = 0
    assert view._default_footer_action() == "focus_pane"

    view.cursor_index = 1
    assert view._default_footer_action() == "new_session"

    view.cursor_index = 2
    assert view._default_footer_action() == "focus_pane"


@pytest.mark.unit
def test_sessions_default_action_is_always_enabled() -> None:
    """Default action must be enabled for its node type."""
    view = SessionsView()
    view._nav_items = [_computer_header(), _project_header(), _session_row()]

    for idx in (0, 1, 2):
        view.cursor_index = idx
        default = view._default_footer_action()
        assert default is not None
        assert view.check_action(default, ()) is True


# ============================================================
# Task 4.1: PreparationView.check_action() including computer tier
# ============================================================


@pytest.mark.unit
def test_preparation_check_action_computer_node() -> None:
    view = PreparationView()
    computer = _computer_header()
    view._nav_items = [computer]
    view.cursor_index = 0

    # Computer enables new_project and fold actions
    assert view.check_action("new_project", ()) is True
    assert view.check_action("expand_all", ()) is True
    assert view.check_action("collapse_all", ()) is True
    # Computer disables todo-specific actions
    assert view.check_action("new_todo", ()) is False
    assert view.check_action("new_bug", ()) is False
    assert view.check_action("remove_todo", ()) is False
    assert view.check_action("activate", ()) is False
    assert view.check_action("preview_file", ()) is False
    assert view.check_action("prepare", ()) is False
    assert view.check_action("start_work", ()) is False


@pytest.mark.unit
def test_preparation_check_action_project_node() -> None:
    view = PreparationView()
    project = _project_header()
    view._nav_items = [project]
    view.cursor_index = 0

    assert view.check_action("new_todo", ()) is True
    assert view.check_action("new_bug", ()) is True
    # Project disables new_project (only for computer nodes)
    assert view.check_action("new_project", ()) is False
    assert view.check_action("remove_todo", ()) is False
    assert view.check_action("activate", ()) is False
    assert view.check_action("preview_file", ()) is False


@pytest.mark.unit
def test_preparation_check_action_todo_node() -> None:
    view = PreparationView()
    todo = _todo_row()
    view._nav_items = [todo]
    view.cursor_index = 0

    assert view.check_action("prepare", ()) is True
    assert view.check_action("start_work", ()) is True
    assert view.check_action("remove_todo", ()) is True
    assert view.check_action("new_todo", ()) is True
    assert view.check_action("preview_file", ()) is False
    assert view.check_action("new_project", ()) is False


@pytest.mark.unit
def test_preparation_check_action_file_node() -> None:
    view = PreparationView()
    file_row = _todo_file_row()
    view._nav_items = [file_row]
    view.cursor_index = 0

    assert view.check_action("preview_file", ()) is True
    assert view.check_action("activate", ()) is True
    assert view.check_action("new_todo", ()) is False
    assert view.check_action("new_bug", ()) is False
    assert view.check_action("new_project", ()) is False


@pytest.mark.unit
def test_preparation_default_action_computer_node() -> None:
    view = PreparationView()
    computer = _computer_header()
    view._nav_items = [computer]
    view.cursor_index = 0
    assert view._default_footer_action() == "new_project"


# ============================================================
# Task 4.1: Hidden-but-active bindings
# ============================================================


@pytest.mark.unit
def test_sessions_view_bindings_have_hidden_nav() -> None:
    """Arrow keys are bound but have show=False."""
    from textual.binding import Binding

    hidden_keys = {b.key for b in SessionsView.BINDINGS if isinstance(b, Binding) and not b.show}
    assert "up" in hidden_keys
    assert "down" in hidden_keys


@pytest.mark.unit
def test_preparation_view_activate_hidden_on_todo_by_check_action() -> None:
    """Enter (activate) on todo nodes toggles — show=True but check_action gates visibility."""
    view = PreparationView()
    todo = _todo_row()
    view._nav_items = [todo]
    view.cursor_index = 0
    # activate is enabled on todo (returns True, not False)
    assert view.check_action("activate", ()) is not False


# ============================================================
# Task 4.2: StartSessionModal path_mode validation
# ============================================================


@pytest.mark.unit
def test_start_session_modal_path_mode_resolves_tilde(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """~ in path input resolves to real path when directory exists."""
    monkeypatch.setattr("teleclaude.core.agents.get_enabled_agents", lambda: ("claude",))

    modal = StartSessionModal(
        computer="local",
        project_path="/tmp/project",
        path_mode=True,
    )

    modal._path_mode = True

    with patch.object(modal, "query_one") as mock_query_one, patch.object(modal, "dismiss") as mock_dismiss:
        home_path = str(tmp_path)

        class MockInput:
            def __init__(self, value: str):
                self.value = value

        class MockLabel:
            def __init__(self):
                self.value = ""

            def update(self, text: str) -> None:
                self.value = text

        class MockAgentSel:
            selected_agent = "claude"

        class MockModeSel:
            selected_mode = "slow"

        path_input = MockInput(f"~/{tmp_path.name}")
        path_error = MockLabel()
        title_input = MockInput("")
        message_input = MockInput("")

        def _query_one(selector: str, cls: type | None = None) -> object:  # type: ignore[return]
            mapping = {
                "#path-input": path_input,
                "#path-error": path_error,
                "#agent-selector": MockAgentSel(),
                "#mode-selector": MockModeSel(),
                "#title-input": title_input,
                "#message-input": message_input,
            }
            return mapping.get(selector)

        mock_query_one.side_effect = _query_one
        modal._agents = ("claude",)

        # Patch expanduser to use tmp_path
        with patch("os.path.expanduser", return_value=home_path), patch("os.path.isdir", return_value=True):
            modal._do_create()

        mock_dismiss.assert_called_once()
        result = mock_dismiss.call_args[0][0]
        assert result is not None
        assert result.project_path == home_path


@pytest.mark.unit
def test_start_session_modal_path_mode_rejects_invalid_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid path keeps modal open with inline error."""
    monkeypatch.setattr("teleclaude.core.agents.get_enabled_agents", lambda: ("claude",))

    modal = StartSessionModal(
        computer="local",
        project_path="/tmp/project",
        path_mode=True,
    )
    modal._agents = ("claude",)

    with patch.object(modal, "query_one") as mock_query_one, patch.object(modal, "dismiss") as mock_dismiss:

        class MockInput:
            def __init__(self, value: str):
                self.value = value

        class MockLabel:
            def __init__(self):
                self.value = ""

            def update(self, text: str) -> None:
                self.value = text

        path_input = MockInput("~/nonexistent-path-xyz")
        path_error = MockLabel()

        def _query_one(selector: str, cls: type | None = None) -> object:  # type: ignore[return]
            if selector == "#path-input":
                return path_input
            if selector == "#path-error":
                return path_error

        mock_query_one.side_effect = _query_one

        with (
            patch("os.path.expanduser", return_value="/home/user/nonexistent-path-xyz"),
            patch("os.path.isdir", return_value=False),
        ):
            modal._do_create()

        # Should NOT dismiss — error shown instead
        mock_dismiss.assert_not_called()
        assert "not a directory" in path_error.value.lower() or "not exist" in path_error.value.lower()


@pytest.mark.unit
def test_start_session_modal_no_path_mode_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without path_mode, behavior is unchanged — no path validation."""
    monkeypatch.setattr("teleclaude.core.agents.get_enabled_agents", lambda: ("claude",))

    modal = StartSessionModal(
        computer="local",
        project_path="/tmp/project",
        path_mode=False,
    )
    modal._agents = ("claude",)
    assert modal._path_mode is False


# ============================================================
# Task 4.2: NewProjectModal validation
# ============================================================


@pytest.mark.unit
def test_new_project_modal_rejects_duplicate_name(tmp_path) -> None:
    """Duplicate project name is rejected with inline error."""
    existing_names = {"my-project"}
    modal = NewProjectModal(existing_names=existing_names, existing_paths=set())

    with patch.object(modal, "query_one") as mock_query_one, patch.object(modal, "dismiss") as mock_dismiss:

        class MockInput:
            def __init__(self, value: str):
                self.value = value

        class MockLabel:
            def __init__(self):
                self.value = ""

            def update(self, text: str) -> None:
                self.value = text

        name_input = MockInput("my-project")
        name_error = MockLabel()
        path_input = MockInput(str(tmp_path))
        path_error = MockLabel()
        desc_input = MockInput("")

        def _query_one(selector: str, cls: type | None = None) -> object:  # type: ignore[return]
            mapping = {
                "#name-input": name_input,
                "#name-error": name_error,
                "#path-input": path_input,
                "#path-error": path_error,
                "#desc-input": desc_input,
            }
            return mapping.get(selector)

        mock_query_one.side_effect = _query_one

        with patch("os.path.expanduser", side_effect=lambda p: p), patch("os.path.isdir", return_value=True):
            modal._do_create()

        mock_dismiss.assert_not_called()
        assert "already exists" in name_error.value.lower()


@pytest.mark.unit
def test_new_project_modal_rejects_duplicate_path(tmp_path) -> None:
    """Duplicate project path is rejected with inline error."""
    existing_paths = {str(tmp_path)}
    modal = NewProjectModal(existing_names=set(), existing_paths=existing_paths)

    with patch.object(modal, "query_one") as mock_query_one, patch.object(modal, "dismiss") as mock_dismiss:

        class MockInput:
            def __init__(self, value: str):
                self.value = value

        class MockLabel:
            def __init__(self):
                self.value = ""

            def update(self, text: str) -> None:
                self.value = text

        name_input = MockInput("unique-name")
        name_error = MockLabel()
        path_input = MockInput(str(tmp_path))
        path_error = MockLabel()
        desc_input = MockInput("")

        def _query_one(selector: str, cls: type | None = None) -> object:  # type: ignore[return]
            mapping = {
                "#name-input": name_input,
                "#name-error": name_error,
                "#path-input": path_input,
                "#path-error": path_error,
                "#desc-input": desc_input,
            }
            return mapping.get(selector)

        mock_query_one.side_effect = _query_one

        with patch("os.path.expanduser", side_effect=lambda p: p), patch("os.path.isdir", return_value=True):
            modal._do_create()

        mock_dismiss.assert_not_called()
        assert "already exists" in path_error.value.lower()


@pytest.mark.unit
def test_new_project_modal_rejects_invalid_path() -> None:
    """Non-directory path is rejected."""
    modal = NewProjectModal(existing_names=set(), existing_paths=set())

    with patch.object(modal, "query_one") as mock_query_one, patch.object(modal, "dismiss") as mock_dismiss:

        class MockInput:
            def __init__(self, value: str):
                self.value = value

        class MockLabel:
            def __init__(self):
                self.value = ""

            def update(self, text: str) -> None:
                self.value = text

        name_input = MockInput("new-project")
        name_error = MockLabel()
        path_input = MockInput("~/nonexistent-xyz")
        path_error = MockLabel()
        desc_input = MockInput("")

        def _query_one(selector: str, cls: type | None = None) -> object:  # type: ignore[return]
            mapping = {
                "#name-input": name_input,
                "#name-error": name_error,
                "#path-input": path_input,
                "#path-error": path_error,
                "#desc-input": desc_input,
            }
            return mapping.get(selector)

        mock_query_one.side_effect = _query_one

        with (
            patch("os.path.expanduser", return_value="/home/user/nonexistent-xyz"),
            patch("os.path.isdir", return_value=False),
        ):
            modal._do_create()

        mock_dismiss.assert_not_called()
        assert path_error.value != ""


@pytest.mark.unit
def test_new_project_modal_valid_returns_result(tmp_path) -> None:
    """Valid input returns NewProjectResult."""
    from teleclaude.cli.tui.widgets.modals import NewProjectResult

    modal = NewProjectModal(existing_names=set(), existing_paths=set())

    with patch.object(modal, "query_one") as mock_query_one, patch.object(modal, "dismiss") as mock_dismiss:

        class MockInput:
            def __init__(self, value: str):
                self.value = value

        class MockLabel:
            def __init__(self):
                self.value = ""

            def update(self, text: str) -> None:
                self.value = text

        name_input = MockInput("my-new-project")
        name_error = MockLabel()
        path_input = MockInput(str(tmp_path))
        path_error = MockLabel()
        desc_input = MockInput("A cool project")

        def _query_one(selector: str, cls: type | None = None) -> object:  # type: ignore[return]
            mapping = {
                "#name-input": name_input,
                "#name-error": name_error,
                "#path-input": path_input,
                "#path-error": path_error,
                "#desc-input": desc_input,
            }
            return mapping.get(selector)

        mock_query_one.side_effect = _query_one

        with patch("os.path.expanduser", side_effect=lambda p: p), patch("os.path.isdir", return_value=True):
            modal._do_create()

        mock_dismiss.assert_called_once()
        result = mock_dismiss.call_args[0][0]
        assert isinstance(result, NewProjectResult)
        assert result.name == "my-new-project"
        assert result.description == "A cool project"
        assert result.path == str(tmp_path)


# ============================================================
# Task 4.3: Preparation tree computer grouping
# ============================================================


def _run_rebuild_with_mock(view: PreparationView) -> None:
    """Run view._rebuild() with a mock Textual container to avoid NoMatches."""

    # Collect widgets passed to mount() calls
    mounted: list[object] = []

    class MockContainer:
        def remove_children(self) -> None:
            pass

        def mount(self, *widgets: object) -> None:
            mounted.extend(widgets)

    mock_container = MockContainer()
    with patch.object(view, "query_one", return_value=mock_container):
        view._rebuild()


@pytest.mark.unit
def test_preparation_tree_groups_by_computer() -> None:
    """nav_items must include ComputerHeader before each ProjectHeader."""
    view = PreparationView()

    # Two projects on different computers (intentionally unsorted to test sort)
    pw1 = _project_with_todos(computer="alpha", name="alpha-project", path="/alpha", slugs=["todo-a"])
    pw2 = _project_with_todos(computer="beta", name="beta-project", path="/beta", slugs=["todo-b"])
    view._projects_with_todos = [pw2, pw1]

    _run_rebuild_with_mock(view)

    types = [type(w).__name__ for w in view._nav_items]

    # ComputerHeader must appear before ProjectHeader
    assert "ComputerHeader" in types
    assert "ProjectHeader" in types
    assert types.index("ComputerHeader") < types.index("ProjectHeader")

    # Computers sorted alphabetically: alpha before beta
    comp_names = [w.data.computer.name for w in view._nav_items if isinstance(w, ComputerHeader)]
    assert comp_names == sorted(comp_names)


@pytest.mark.unit
def test_preparation_tree_preserves_project_under_computer() -> None:
    """Each project appears immediately after its computer node."""
    view = PreparationView()

    pw_local = _project_with_todos(computer="local", name="local-proj", path="/local")
    pw_remote = _project_with_todos(computer="remote", name="remote-proj", path="/remote")
    view._projects_with_todos = [pw_local, pw_remote]

    _run_rebuild_with_mock(view)

    last_computer: str | None = None
    computer_project_map: dict[str, list[str]] = {}
    for widget in view._nav_items:
        if isinstance(widget, ComputerHeader):
            last_computer = widget.data.computer.name
            computer_project_map[last_computer] = []
        elif isinstance(widget, ProjectHeader) and last_computer is not None:
            computer_project_map[last_computer].append(widget.project.path)

    assert "/local" in computer_project_map.get("local", [])
    assert "/remote" in computer_project_map.get("remote", [])


@pytest.mark.unit
def test_preparation_tree_single_computer_still_has_header() -> None:
    """Even with one computer, a ComputerHeader is rendered."""
    view = PreparationView()
    pw = _project_with_todos(computer="local", name="proj", path="/proj")
    view._projects_with_todos = [pw]

    _run_rebuild_with_mock(view)

    computer_headers = [w for w in view._nav_items if isinstance(w, ComputerHeader)]
    assert len(computer_headers) == 1
    assert computer_headers[0].data.computer.name == "local"
