"""Characterization tests for project listing routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.api import projects_routes
from teleclaude.core.models import ProjectInfo, TodoInfo


class CacheStub:
    def __init__(self, local_projects: list[ProjectInfo], remote_projects: list[ProjectInfo]) -> None:
        self._local_projects = local_projects
        self._remote_projects = remote_projects
        self.apply_projects_snapshot = MagicMock()
        self.apply_todos_snapshot = MagicMock()

    def get_projects(self, computer: str | None = None) -> list[ProjectInfo]:
        if computer == "local-box":
            return self._local_projects
        if computer is None:
            return self._local_projects + self._remote_projects
        return self._remote_projects


class TestProjectsRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_projects_prefers_cached_local_projects_and_appends_remote_cache(self) -> None:
        """Project listing serves cached local projects first and appends remote cache entries."""
        cache = CacheStub(
            local_projects=[ProjectInfo(name="local", path="/work/local", computer="local-box")],
            remote_projects=[ProjectInfo(name="remote", path="/work/remote", computer="raspi")],
        )
        projects_routes.configure(cache)
        config_stub = SimpleNamespace(computer=SimpleNamespace(name="local-box"))

        with (
            patch("teleclaude.api.projects_routes.config", config_stub),
            patch("teleclaude.api.projects_routes.command_handlers.list_projects_with_todos", new=AsyncMock()),
        ):
            response = await projects_routes.list_projects(identity=object())

        assert [project.model_dump() for project in response] == [
            {"computer": "local-box", "name": "local", "path": "/work/local", "description": None},
            {"computer": "raspi", "name": "remote", "path": "/work/remote", "description": None},
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_projects_populates_cache_on_filesystem_fallback(self) -> None:
        """Cache misses fall back to filesystem discovery and refresh the cache snapshots."""
        discovered = [
            ProjectInfo(
                name="local",
                path="/work/local",
                computer="local-box",
                todos=[TodoInfo(slug="chartest-api-routes", status="pending")],
            )
        ]
        cache = CacheStub(local_projects=[], remote_projects=[])
        projects_routes.configure(cache)
        config_stub = SimpleNamespace(computer=SimpleNamespace(name="local-box"))

        with (
            patch("teleclaude.api.projects_routes.config", config_stub),
            patch(
                "teleclaude.api.projects_routes.command_handlers.list_projects_with_todos",
                new=AsyncMock(return_value=discovered),
            ),
        ):
            response = await projects_routes.list_projects(identity=object())

        assert [project.model_dump() for project in response] == [
            {"computer": "local-box", "name": "local", "path": "/work/local", "description": None}
        ]
        cache.apply_projects_snapshot.assert_called_once_with("local-box", discovered)
        cache.apply_todos_snapshot.assert_called_once_with(
            "local-box",
            {"/work/local": [TodoInfo(slug="chartest-api-routes", status="pending")]},
        )
