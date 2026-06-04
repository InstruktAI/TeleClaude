"""Behavioral tests for teleclaude.cli.tui.views.preparation."""

from __future__ import annotations

import shlex
import sys
from unittest.mock import MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion
from textual.app import App, ComposeResult
from textual.binding import Binding

from teleclaude.api_models import ProjectWithTodosDTO, TodoDTO
from teleclaude.cli.tui.messages import DocEditRequest, DocPreviewRequest
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.widgets.computer_header import ComputerHeader
from teleclaude.cli.tui.widgets.project_header import ProjectHeader
from teleclaude.cli.tui.widgets.telec_footer import TelecFooter
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.cli.tui.widgets.todo_row import TodoRow

_FINGERPRINT_SLUG = "todo-1"
_VERSION_BEFORE = 1
_VERSION_AFTER = 2
_READY_SLUG = "ready-todo"
_PREP_SLUG = "prep-todo"


def _binding_objects(view: PreparationView) -> list[Binding]:
    """Return the Binding entries of a view's BINDINGS (Textual allows tuples too)."""
    return [b for b in view.BINDINGS if isinstance(b, Binding)]


class _PreparationHarness(App[None]):
    """Minimal app harness for exercising PreparationView key bindings."""

    def __init__(self) -> None:
        super().__init__()
        self.doc_events: list[tuple[str, str, str, str]] = []

    def compose(self) -> ComposeResult:
        yield PreparationView(id="preparation-view")

    def on_mount(self) -> None:
        self.query_one(PreparationView).focus()

    def on_doc_preview_request(self, message: DocPreviewRequest) -> None:
        self.doc_events.append(("preview", message.doc_id, message.command, message.title))

    def on_doc_edit_request(self, message: DocEditRequest) -> None:
        self.doc_events.append(("edit", message.doc_id, message.command, message.title))


def _build_project(project_path: str) -> ProjectWithTodosDTO:
    """Create a single-project preparation tree with one todo artifact."""
    return ProjectWithTodosDTO(
        computer="local",
        name="Test Project",
        path="/tmp/project",
        description="Preparation test project",
        todos=[
            TodoDTO(
                slug="todo-1",
                status="pending",
                description="Test todo",
                has_requirements=True,
                has_impl_plan=False,
                files=["requirements"],
                project_path=project_path,
            )
        ],
    )


def _fingerprint_project(version_total: int) -> ProjectWithTodosDTO:
    """Build the minimal object graph consumed by _todo_fingerprint."""
    return ProjectWithTodosDTO(
        computer="local",
        name="Test Project",
        path="/tmp/project",
        todos=[
            TodoDTO(
                slug=_FINGERPRINT_SLUG,
                status="pending",
                has_requirements=True,
                has_impl_plan=False,
                files=["requirements"],
                lifecycle_phase="prepared",
                version_total=version_total,
            )
        ],
    )


def _active_project() -> ProjectWithTodosDTO:
    return ProjectWithTodosDTO(
        computer="local",
        name="Test Project",
        path="/tmp/project",
        todos=[
            TodoDTO(
                slug=_READY_SLUG,
                status="ready",
                has_requirements=True,
                has_impl_plan=True,
                ready_since="2026-05-20T00:00:00+00:00",
            ),
            TodoDTO(
                slug=_PREP_SLUG,
                status="in_progress",
                has_requirements=True,
                has_impl_plan=False,
                created_at="2026-05-21T00:00:00+00:00",
            ),
        ],
    )


@pytest.mark.unit
def test_preparation_view_is_importable() -> None:
    assert PreparationView is not None


@pytest.mark.unit
def test_todo_fingerprint_changes_when_only_artifact_version_total_changes() -> None:
    before = PreparationView._todo_fingerprint([_fingerprint_project(_VERSION_BEFORE)])
    after = PreparationView._todo_fingerprint([_fingerprint_project(_VERSION_AFTER)])

    assert before != after


@pytest.mark.unit
def test_todo_fingerprint_changes_when_ready_since_changes() -> None:
    before = PreparationView._todo_fingerprint([_active_project()])
    project = _active_project()
    project.todos[0] = project.todos[0].model_copy(update={"ready_since": "2026-05-25T00:00:00+00:00"})
    after = PreparationView._todo_fingerprint([project])

    assert before != after


@pytest.mark.unit
async def test_preparation_view_renders_active_rows_without_band_separators() -> None:
    app = _PreparationHarness()

    async with app.run_test() as pilot:
        prep = app.query_one("#preparation-view", PreparationView)
        prep.update_data([_active_project()])
        await pilot.pause()

        rows = list(prep.query(TodoRow))

    assert len(rows) == 2


@pytest.mark.unit
async def test_preparation_view_keyboard_preview_and_edit_file_rows() -> None:
    project_path = "/tmp/project"
    expected_doc_id = "artifact:/tmp/project:todo-1:requirements"
    app = _PreparationHarness()

    async with app.run_test() as pilot:
        prep = app.query_one("#preparation-view", PreparationView)
        prep.update_data([_build_project(project_path)])

        await pilot.press("down", "down", "enter")
        await pilot.pause()

        assert isinstance(prep._nav_items[-1], TodoFileRow)

        await pilot.press("down", "space")
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

    assert len(app.doc_events) == 2

    preview_kind, preview_doc_id, preview_command, preview_title = app.doc_events[0]
    assert preview_kind == "preview"
    assert preview_doc_id == expected_doc_id
    assert preview_command.startswith(f"{shlex.quote(sys.executable)} -m teleclaude.cli.editor ")
    assert "--view" in preview_command
    assert "--artifact-slug todo-1" in preview_command
    assert "--artifact-name requirements" in preview_command
    assert "--project-root /tmp/project" in preview_command
    assert preview_title == "requirements"

    edit_kind, edit_doc_id, edit_command, edit_title = app.doc_events[1]
    assert edit_kind == "edit"
    assert edit_doc_id == expected_doc_id
    assert edit_command.startswith(f"{shlex.quote(sys.executable)} -m teleclaude.cli.editor ")
    assert "--view" not in edit_command
    assert "--artifact-slug todo-1" in edit_command
    assert "--artifact-name requirements" in edit_command
    assert "--project-root /tmp/project" in edit_command
    assert edit_title == "Editing: requirements"


def test_preparation_view_toggles_trashed_projects() -> None:
    """x: toggle_trashed must update _trashed_projects set."""
    view = PreparationView()
    project_path = "/path/to/project"

    # Mock _resolve_cursor_context and _rebuild

    with (
        patch.object(view, "_resolve_cursor_context", return_value=("comp", project_path, None)),
        patch.object(view, "_rebuild"),
    ):
        view.action_toggle_trashed()
        assert project_path in view._trashed_projects

        view.action_toggle_trashed()
        assert project_path not in view._trashed_projects


def test_preparation_view_persists_trashed_state() -> None:
    """trashed_projects must be included in persisted state."""
    view = PreparationView()
    view._trashed_projects.add("/path/to/trashed")

    state = view.get_persisted_state()
    trashed_projects = state["trashed_projects"]
    assert isinstance(trashed_projects, list)
    assert "/path/to/trashed" in trashed_projects

    new_view = PreparationView()
    # load_persisted_state expects TUI state dict from storage

    with patch.object(new_view, "_rebuild"):
        new_view.load_persisted_state({"trashed_projects": ["/path/to/trashed"]})
    assert "/path/to/trashed" in new_view._trashed_projects


def _cursor_to(prep: PreparationView, widget_type: type) -> None:
    prep.cursor_index = next(i for i, w in enumerate(prep._nav_items) if isinstance(w, widget_type))


@pytest.mark.unit
async def test_preparation_collapse_project_hides_todos_and_expand_restores() -> None:
    app = _PreparationHarness()
    async with app.run_test() as pilot:
        prep = app.query_one("#preparation-view", PreparationView)
        prep.update_data([_active_project()])
        await pilot.pause()

        _cursor_to(prep, ProjectHeader)
        assert any(isinstance(w, TodoRow) for w in prep._nav_items)

        prep.action_collapse()
        await pilot.pause()
        assert not any(isinstance(w, TodoRow) for w in prep._nav_items)
        assert ("local", "/tmp/project") in prep._collapsed_projects

        prep.action_expand()
        await pilot.pause()
        assert any(isinstance(w, TodoRow) for w in prep._nav_items)
        assert ("local", "/tmp/project") not in prep._collapsed_projects


@pytest.mark.unit
async def test_preparation_collapse_computer_hides_projects_but_keeps_header() -> None:
    app = _PreparationHarness()
    async with app.run_test() as pilot:
        prep = app.query_one("#preparation-view", PreparationView)
        prep.update_data([_active_project()])
        await pilot.pause()

        _cursor_to(prep, ComputerHeader)
        prep.action_collapse()
        await pilot.pause()

        assert any(isinstance(w, ComputerHeader) for w in prep._nav_items)
        assert not any(isinstance(w, ProjectHeader) for w in prep._nav_items)
        assert not any(isinstance(w, TodoRow) for w in prep._nav_items)
        assert "local" in prep._collapsed_computers


@pytest.mark.unit
async def test_preparation_structure_keys_toggle_structure_without_touching_todos() -> None:
    app = _PreparationHarness()
    async with app.run_test() as pilot:
        prep = app.query_one("#preparation-view", PreparationView)
        prep.update_data([_active_project()])
        await pilot.pause()
        prep._expanded_todos.add(_READY_SLUG)

        prep.action_collapse_structure()
        await pilot.pause()
        assert prep._collapsed_computers == {"local"}
        assert prep._collapsed_projects == {("local", "/tmp/project")}
        assert _READY_SLUG in prep._expanded_todos
        assert not any(isinstance(w, (ProjectHeader, TodoRow)) for w in prep._nav_items)

        prep.action_expand_structure()
        await pilot.pause()
        assert prep._collapsed_computers == set()
        assert prep._collapsed_projects == set()
        assert any(isinstance(w, TodoRow) for w in prep._nav_items)


@pytest.mark.unit
def test_preparation_persists_collapsed_structure_round_trip() -> None:
    view = PreparationView()
    view._collapsed_computers.add("local")
    view._collapsed_projects.add(("local", "/tmp/project"))

    state = view.get_persisted_state()
    assert state["collapsed_computers"] == ["local"]
    assert state["collapsed_projects"] == [["local", "/tmp/project"]]

    new_view = PreparationView()
    new_view.load_persisted_state(state)
    assert new_view._collapsed_computers == {"local"}
    assert new_view._collapsed_projects == {("local", "/tmp/project")}


@pytest.mark.unit
def test_preparation_view_footer_bindings_match_shortened_labels() -> None:
    """The PreparationView footer must use the shortened labels from Task 6b."""
    view = PreparationView()
    # Check a few representative bindings
    prep_binding = next(b for b in _binding_objects(view) if b.action == "prepare")
    assert prep_binding.description == "Prep"

    rcncl_binding = next(b for b in _binding_objects(view) if b.action == "reconcile")
    assert rcncl_binding.description == "Rcncl"

    trsh_binding = next(b for b in _binding_objects(view) if b.action == "toggle_trashed")
    assert trsh_binding.description == "Trsh"

    unr_binding = next(b for b in _binding_objects(view) if b.action == "reactivate_selected")
    assert unr_binding.description == "Unr"


@pytest.mark.unit
def test_preparation_view_manual_reorder_bindings_are_removed() -> None:
    """Manual reorder bindings (shift+up/down) must be removed from PreparationView."""
    view = PreparationView()
    actions = {b.action for b in _binding_objects(view)}
    assert "move_todo_up" not in actions
    assert "move_todo_down" not in actions


@pytest.mark.unit
def test_preparation_view_footer_snapshot_at_120_cols(snapshot: SnapshotAssertion) -> None:
    """The PreparationView footer at 120 columns must include all new and shortened bindings."""
    view = PreparationView()
    # Mock enough of the app/screen to satisfy TelecFooter
    mock_app = MagicMock(spec=App)
    mock_app.app_focus = True
    mock_app.get_key_display.side_effect = lambda b: b.key

    mock_screen = MagicMock()
    # Build the set of active bindings from view.BINDINGS
    active_bindings = {}
    for binding in _binding_objects(view):
        # node, binding, enabled, tooltip
        active_bindings[binding.action] = (view, binding, True, "")

    mock_screen.active_bindings = active_bindings

    footer = TelecFooter()
    with (
        patch.object(TelecFooter, "app", mock_app),
        patch.object(TelecFooter, "screen", mock_screen),
        patch.object(TelecFooter, "is_mounted", True),
    ):
        context_items, _ = footer._collect_rows()
        rendered = footer._render_hints_line(context_items, empty_label="none")

    # The snapshot will capture the full plain text.
    assert rendered.plain == snapshot
