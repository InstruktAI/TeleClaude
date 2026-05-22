"""Behavioral tests for teleclaude.cli.tui.views.preparation."""

from __future__ import annotations

import shlex
import sys

import pytest
from textual.app import App, ComposeResult

from teleclaude.api_models import ProjectWithTodosDTO, TodoDTO
from teleclaude.cli.tui.messages import DocEditRequest, DocPreviewRequest
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.widgets.todo_band_separator import TodoBandSeparator
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
from teleclaude.core.roadmap import IN_PREP_BAND, READY_BAND

_FINGERPRINT_SLUG = "todo-1"
_VERSION_BEFORE = 1
_VERSION_AFTER = 2
_READY_SLUG = "ready-todo"
_PREP_SLUG = "prep-todo"


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


def _band_project() -> ProjectWithTodosDTO:
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
                band=READY_BAND,
                ready_since="2026-05-20T00:00:00+00:00",
            ),
            TodoDTO(
                slug=_PREP_SLUG,
                status="in_progress",
                has_requirements=True,
                has_impl_plan=False,
                band=IN_PREP_BAND,
                updated_at="2026-05-21T00:00:00+00:00",
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
def test_todo_fingerprint_changes_when_band_changes() -> None:
    before = PreparationView._todo_fingerprint([_band_project()])
    project = _band_project()
    project.todos[0] = project.todos[0].model_copy(update={"band": IN_PREP_BAND})
    after = PreparationView._todo_fingerprint([project])

    assert before != after


@pytest.mark.unit
@pytest.mark.timeout(60)
async def test_preparation_view_renders_active_band_separators() -> None:
    app = _PreparationHarness()

    async with app.run_test() as pilot:
        prep = app.query_one("#preparation-view", PreparationView)
        prep.update_data([_band_project()])
        await pilot.pause()

        separators = list(prep.query(TodoBandSeparator))

    assert [separator.band for separator in separators] == [READY_BAND, IN_PREP_BAND]


@pytest.mark.unit
@pytest.mark.timeout(60)
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
