"""Functional TelecApp coverage for preparation artifact preview/edit flow."""

from __future__ import annotations

import asyncio
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import teleclaude.cli.tui.app as app_module
from teleclaude.api import todo_routes
from teleclaude.api_models import (
    AgentAvailabilityDTO,
    ChiptunesStatusDTO,
    ComputerDTO,
    ProjectWithTodosDTO,
    SettingsDTO,
    TodoDTO,
    TTSSettingsDTO,
    TuiBootstrapDataDTO,
    TuiBootstrapDTO,
    TuiBootstrapPillar,
)
from teleclaude.cli import editor as editor_module
from teleclaude.cli.editor import MaterializedArtifact
from teleclaude.cli.tui.app import TelecApp
from teleclaude.cli.tui.pane_bridge import PaneManagerBridge
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.constants import ARTIFACT_REQUIREMENTS, LOCAL_COMPUTER
from teleclaude.core.cache import DaemonCache
from teleclaude.core.todos_db import close_todos_db_instances, get_todos_db, set_todos_mutation_hook

pytestmark = [pytest.mark.functional, pytest.mark.asyncio, pytest.mark.timeout(45)]

_CACHE_REFLECTION_CONTENT = "requirements from editor\n"
_CACHE_REFLECTION_SHA = "cache-reflection-sha"
_CACHE_REFLECTION_SLUG = "editor-cache-reflection"


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

    async def get_tui_bootstrap(self, requested: list[TuiBootstrapPillar]) -> TuiBootstrapDTO:
        return TuiBootstrapDTO(
            requested=requested,
            data=TuiBootstrapDataDTO(
                computers=await self.list_computers(),
                projects_with_todos=await self.list_projects_with_todos(),
                sessions=[],
                availability={},
                jobs=[],
                settings=SettingsDTO(tts=TTSSettingsDTO(enabled=False)),
                chiptunes=ChiptunesStatusDTO(),
            ),
        )


async def _wait_for_preparation_rows(pilot: object, prep: PreparationView) -> None:
    """Wait until app refresh populates the preparation tree."""
    for _ in range(10):
        await pilot.pause()
        if prep._nav_items:
            return
    raise AssertionError("Preparation data did not load")


async def _drain_refresh_tasks(refresh_tasks: list[asyncio.Task[None]]) -> None:
    """Wait for cache refresh work scheduled by the daemon-style mutation hook."""
    pending = list(refresh_tasks)
    refresh_tasks.clear()
    if pending:
        await asyncio.gather(*pending)


def _read_required_body_field(body: object, field_name: str) -> str:
    """Return a required string field from the editor's daemon-request body."""
    if not isinstance(body, dict):
        raise AssertionError("artifact write body must be a JSON object")
    value = body[field_name]
    if not isinstance(value, str):
        raise AssertionError("artifact write body field must be a string")
    return value


@pytest.mark.functional
async def test_editor_artifact_persist_refreshes_cached_todo_without_stale_ttl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persisting through the editor path refreshes cached todo artifact data immediately."""
    project_root = tmp_path / "project"
    state_root = project_root / ".teleclaude"
    state_root.mkdir(parents=True)
    cache = DaemonCache()
    loop = asyncio.get_running_loop()
    refresh_tasks: list[asyncio.Task[None]] = []

    def _register_refresh_hook(instance: object, hook_project_root: str) -> None:
        def _on_mutation(event_hint: str = "todo_updated", event_data: object | None = None) -> None:
            del event_data
            refresh_tasks.append(
                loop.create_task(cache.refresh_local_todos(LOCAL_COMPUTER, hook_project_root, event_hint))
            )

        instance._on_mutation = _on_mutation  # type: ignore[attr-defined] # mirrors daemon hook wiring

    def _extract_referenced_paths(_content: str, _cwd: str) -> list[str]:
        return []

    set_todos_mutation_hook(_register_refresh_hook)
    monkeypatch.setattr(todo_routes, "get_head_commit", lambda _cwd: _CACHE_REFLECTION_SHA)
    monkeypatch.setattr(todo_routes, "extract_referenced_paths", _extract_referenced_paths)

    database = await get_todos_db(project_root)
    materialized: MaterializedArtifact | None = None
    try:
        await database.add_to_roadmap(_CACHE_REFLECTION_SLUG, description="cache reflection")
        await _drain_refresh_tasks(refresh_tasks)
        cache.set_todos(
            LOCAL_COMPUTER,
            str(project_root),
            [
                TodoDTO(
                    slug=_CACHE_REFLECTION_SLUG,
                    status="pending",
                    has_requirements=False,
                    has_impl_plan=False,
                    files=[],
                    version_total=0,
                )
            ],
        )

        async def _write_via_daemon_route(body: object) -> object:
            response = await todo_routes.write_artifact(
                slug=_CACHE_REFLECTION_SLUG,
                name=ARTIFACT_REQUIREMENTS,
                content=_read_required_body_field(body, "content"),
                cwd=_read_required_body_field(body, "cwd"),
                updated_by=_read_required_body_field(body, "updated_by"),
            )
            await _drain_refresh_tasks(refresh_tasks)
            return response.model_dump()

        def _fake_tool_api_request(
            _method: str,
            _path: str,
            *,
            json_body: object = None,
            **_kwargs: object,
        ) -> object:
            future = asyncio.run_coroutine_threadsafe(_write_via_daemon_route(json_body), loop)
            return future.result(timeout=5)

        monkeypatch.setattr(editor_module, "tool_api_request", _fake_tool_api_request)
        materialized = MaterializedArtifact.from_db(
            project_root=project_root,
            slug=_CACHE_REFLECTION_SLUG,
            artifact_name=ARTIFACT_REQUIREMENTS,
        )

        await asyncio.to_thread(materialized.persist, _CACHE_REFLECTION_CONTENT)

        refreshed = cache.get_todos(LOCAL_COMPUTER, str(project_root))
        assert len(refreshed) == 1
        assert refreshed[0].files == [ARTIFACT_REQUIREMENTS]
        assert refreshed[0].version_total == 1
    finally:
        if materialized is not None:
            materialized.cleanup()
        set_todos_mutation_hook(None)
        await close_todos_db_instances()


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
        assert preview.command.startswith(f"{shlex.quote(sys.executable)} -m teleclaude.cli.editor ")
        assert "--view" in preview.command
        assert "--artifact-slug todo-1" in preview.command
        assert "--artifact-name requirements" in preview.command
        assert "--project-root /tmp/project" in preview.command
        assert preview.title == "requirements"

        await pilot.press("enter")
        for _ in range(3):
            await pilot.pause()

        edit_preview = bridge._active_doc_preview
        assert edit_preview is not None
        assert edit_preview.doc_id == expected_doc_id
        assert edit_preview.command.startswith(f"{shlex.quote(sys.executable)} -m teleclaude.cli.editor ")
        assert "--view" not in edit_preview.command
        assert "--artifact-slug todo-1" in edit_preview.command
        assert "--artifact-name requirements" in edit_preview.command
        assert "--project-root /tmp/project" in edit_preview.command
        assert edit_preview.title == "Editing: requirements"

        await app.action_quit()

    api.connect.assert_awaited_once()
    assert len(api.websocket_calls) == 1
