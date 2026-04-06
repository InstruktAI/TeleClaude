"""Functional TelecApp coverage for preparation artifact preview/edit flow."""
# pylint: disable=missing-function-docstring,protected-access

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import teleclaude.cli.tui.app as app_module
from teleclaude.api_models import AgentAvailabilityDTO, ComputerDTO, ProjectWithTodosDTO, TodoDTO
from teleclaude.cli.tui.app import TelecApp
from teleclaude.cli.tui.pane_bridge import PaneManagerBridge
from teleclaude.cli.tui.views.preparation import PreparationView

pytestmark = [pytest.mark.functional, pytest.mark.asyncio, pytest.mark.timeout(5)]


class _StubAPI:
    """Minimal API surface required for TelecApp mount and refresh."""

    def __init__(self) -> None:
        self.connect = AsyncMock(return_value=None)
        self.close = AsyncMock(return_value=None)
        self.websocket_calls: list[tuple[object, object, object]] = []

    def start_websocket(
        self,
        *,
        callback: object,
        subscriptions: object = None,
        on_connect: object = None,
    ) -> None:
        self.websocket_calls.append((callback, subscriptions, on_connect))

    async def list_computers(self) -> list[ComputerDTO]:
        return [ComputerDTO(name="local", status="online", user="test", host="localhost", is_local=True)]

    async def list_projects_with_todos(self) -> list[ProjectWithTodosDTO]:
        return [
            ProjectWithTodosDTO(
                computer="local",
                name="Functional Project",
                path="/tmp/project",
                description="Preparation flow fixture",
                todos=[
                    TodoDTO(
                        slug="todo-1",
                        status="pending",
                        description="Test todo",
                        has_requirements=True,
                        has_impl_plan=False,
                        files=["requirements"],
                        project_path="/tmp/project",
                    )
                ],
            )
        ]

    async def list_sessions(self) -> list[object]:
        return []

    async def get_agent_availability(self) -> dict[str, AgentAvailabilityDTO]:
        return {}

    async def list_jobs(self) -> list[object]:
        return []

    async def get_settings(self) -> object:
        return SimpleNamespace(tts=SimpleNamespace(enabled=False))

    async def get_chiptunes_status(self) -> None:
        return None


async def _wait_for_preparation_rows(pilot: object, prep: PreparationView) -> None:
    """Wait until app refresh populates the preparation tree."""
    for _ in range(10):
        await pilot.pause()
        if prep._nav_items:
            return
    raise AssertionError("Preparation data did not load")


@pytest.mark.functional
async def test_telec_app_preparation_artifact_preview_and_edit_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive the real app through todo expansion plus preview/edit on an artifact."""
    monkeypatch.setattr(app_module, "load_state", lambda: {})
    monkeypatch.setattr(app_module, "save_state", lambda _state: None)
    monkeypatch.setattr(app_module.signal, "signal", lambda *_args, **_kwargs: None)
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)

    api = _StubAPI()
    app = TelecApp(api=api, start_view=2)
    expected_doc_id = "artifact:/tmp/project:todo-1:requirements"

    async with app.run_test() as pilot:
        prep = app.query_one("#preparation-view", PreparationView)
        bridge = app.query_one("#pane-bridge", PaneManagerBridge)

        await _wait_for_preparation_rows(pilot, prep)
        assert [type(widget).__name__ for widget in prep._nav_items] == [
            "ComputerHeader",
            "ProjectHeader",
            "TodoRow",
        ]

        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert [type(widget).__name__ for widget in prep._nav_items] == [
            "ComputerHeader",
            "ProjectHeader",
            "TodoRow",
            "TodoFileRow",
        ]

        await pilot.press("down", "space")
        for _ in range(3):
            await pilot.pause()

        preview = bridge._active_doc_preview
        assert preview is not None
        assert preview.doc_id == expected_doc_id
        assert "--view" in preview.command
        assert "--artifact-slug todo-1" in preview.command
        assert "--artifact-name requirements" in preview.command
        assert "--project-root /tmp/project" in preview.command
        assert preview.title == "requirements.md"

        await pilot.press("enter")
        for _ in range(3):
            await pilot.pause()

        edit_preview = bridge._active_doc_preview
        assert edit_preview is not None
        assert edit_preview.doc_id == expected_doc_id
        assert "--view" not in edit_preview.command
        assert "--artifact-slug todo-1" in edit_preview.command
        assert "--artifact-name requirements" in edit_preview.command
        assert "--project-root /tmp/project" in edit_preview.command
        assert edit_preview.title == "Editing: requirements.md"

        await app.action_quit()

    api.connect.assert_awaited_once()
    assert len(api.websocket_calls) == 1
