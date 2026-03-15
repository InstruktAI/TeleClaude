"""Characterization tests for todo workflow routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import todo_routes


class TestTodoRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_create_uses_default_cwd_when_request_omits_it(self) -> None:
        """Todo creation falls back to the configured default working directory."""
        config_stub = SimpleNamespace(computer=SimpleNamespace(default_working_dir="/repo"))

        with (
            patch("teleclaude.api.todo_routes.config", config_stub),
            patch("teleclaude.api.todo_routes.next_create", new=AsyncMock(return_value="create-next")) as next_create,
        ):
            response = await todo_routes.todo_create(slug="chartest-api-routes", cwd=None, _identity=object())

        assert response == {"result": "create-next"}
        next_create.assert_awaited_once_with(todo_routes.db, "chartest-api-routes", "/repo")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_work_requires_explicit_cwd(self) -> None:
        """Todo work submissions reject requests without a working directory."""
        identity = SimpleNamespace(session_id="sess-1")

        with pytest.raises(HTTPException) as exc_info:
            await todo_routes.todo_work(slug="chartest-api-routes", cwd=None, client_request_id=None, identity=identity)

        assert exc_info.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_mark_phase_rejects_invalid_prepare_status(self) -> None:
        """Prepare-phase updates validate the allowed status vocabulary before mutating state."""
        with pytest.raises(HTTPException) as exc_info:
            await todo_routes.todo_mark_phase(
                slug="chartest-api-routes",
                phase="prepare",
                status="bogus",
                cwd="/repo",
                identity=object(),
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_set_deps_returns_409_for_circular_dependency(self) -> None:
        """Dependency updates reject cycles discovered by the roadmap graph helper."""
        entries = [SimpleNamespace(slug="chartest-api-routes", after=[]), SimpleNamespace(slug="base-task", after=[])]

        with (
            patch("teleclaude.api.todo_routes.load_roadmap", return_value=entries),
            patch("teleclaude.api.todo_routes.load_roadmap_deps", return_value={"chartest-api-routes": []}),
            patch("teleclaude.api.todo_routes.detect_circular_dependency", return_value=["a", "b", "a"]),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.todo_set_deps(
                    slug="chartest-api-routes",
                    after=["base-task"],
                    cwd="/repo",
                    identity=object(),
                )

        assert exc_info.value.status_code == 409

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_set_deps_persists_updated_dependency_list(self) -> None:
        """Successful dependency updates rewrite the roadmap entry and save the roadmap."""
        entries = [SimpleNamespace(slug="chartest-api-routes", after=[]), SimpleNamespace(slug="base-task", after=[])]

        with (
            patch("teleclaude.api.todo_routes.load_roadmap", return_value=entries),
            patch("teleclaude.api.todo_routes.load_roadmap_deps", return_value={"chartest-api-routes": []}),
            patch("teleclaude.api.todo_routes.detect_circular_dependency", return_value=None),
            patch("teleclaude.api.todo_routes.save_roadmap", new=MagicMock()) as save_roadmap,
        ):
            response = await todo_routes.todo_set_deps(
                slug="chartest-api-routes",
                after=["base-task"],
                cwd="/repo",
                identity=object(),
            )

        assert "result" in response
        assert response["result"]  # non-empty result present
        assert entries[0].after == ["base-task"]
        save_roadmap.assert_called_once_with("/repo", entries)
