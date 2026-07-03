"""Functional coverage for list command computer filters."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from teleclaude.api import projects_routes
from teleclaude.api_models import ProjectDTO
from teleclaude.config import config
from teleclaude.core.cache import DaemonCache
from teleclaude.core.models import ProjectInfo


@pytest.mark.functional
@pytest.mark.asyncio
async def test_projects_list_honors_computer(api: AsyncClient) -> None:
    """Drive the projects route through HTTP and verify computer scoping."""
    cache = DaemonCache()
    local_name = config.computer.name
    remote_name = "MozMini"
    cache.apply_projects_snapshot(
        local_name,
        [ProjectInfo(name="local-project", path="/local/project", computer=local_name)],
    )
    cache.apply_projects_snapshot(
        remote_name,
        [ProjectInfo(name="remote-project", path="/remote/project", computer=remote_name)],
    )

    projects_routes.configure(cache)
    try:
        remote_response = await api.get("/projects", params={"computer": remote_name})
        local_response = await api.get("/projects", params={"computer": local_name})
        all_response = await api.get("/projects")
    finally:
        projects_routes.configure(None)

    assert remote_response.status_code == 200
    assert local_response.status_code == 200
    assert all_response.status_code == 200
    assert _project_keys(remote_response.json()) == {("remote-project", remote_name)}
    assert _project_keys(local_response.json()) == {("local-project", local_name)}
    assert _project_keys(all_response.json()) == {
        ("local-project", local_name),
        ("remote-project", remote_name),
    }


def _project_keys(projects: object) -> set[tuple[str, str]]:
    assert isinstance(projects, list)
    return {(project.name, project.computer) for project in (ProjectDTO.model_validate(item) for item in projects)}
