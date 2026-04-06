"""Behavioral tests for teleclaude.cli.tui.views.preparation."""
# pylint: disable=missing-function-docstring,protected-access

from __future__ import annotations

import shlex
import sys

import pytest
from textual.app import App, ComposeResult

from teleclaude.api_models import ProjectWithTodosDTO, TodoDTO
from teleclaude.cli.tui.messages import DocEditRequest, DocPreviewRequest
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow


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


@pytest.mark.unit
def test_preparation_view_is_importable() -> None:
    assert PreparationView is not None


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
    assert preview_title == "requirements.md"

    edit_kind, edit_doc_id, edit_command, edit_title = app.doc_events[1]
    assert edit_kind == "edit"
    assert edit_doc_id == expected_doc_id
    assert edit_command.startswith(f"{shlex.quote(sys.executable)} -m teleclaude.cli.editor ")
    assert "--view" not in edit_command
    assert "--artifact-slug todo-1" in edit_command
    assert "--artifact-name requirements" in edit_command
    assert "--project-root /tmp/project" in edit_command
    assert edit_title == "Editing: requirements.md"
