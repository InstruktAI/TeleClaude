"""Tests for TUI-facing aggregate bootstrap route."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from teleclaude.api import tui_routes
from teleclaude.api.auth import CallerIdentity
from teleclaude.api_models import ComputerDTO, SessionDTO


def _identity() -> CallerIdentity:
    return CallerIdentity(
        session_id="",
        system_role=None,
        human_role="admin",
        tmux_session_name=None,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tui_bootstrap_returns_successful_pillars_and_errors_without_invalidating_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One failed pillar should not poison the whole bootstrap response."""
    computer = ComputerDTO(name="MozBook", status="online", user="morriz", host="mozbook", is_local=True)
    session = SessionDTO(
        session_id="sess-001",
        title="Working",
        status="active",
        computer="MozBook",
        project_path="/repo/app",
    )
    load_computers = AsyncMock(return_value=[computer])
    load_projects = AsyncMock(side_effect=HTTPException(status_code=503, detail="projects warming"))
    load_sessions = AsyncMock(return_value=[session])
    monkeypatch.setattr(tui_routes, "_load_computers", load_computers)
    monkeypatch.setattr(tui_routes, "_load_projects_with_todos", load_projects)
    monkeypatch.setattr(tui_routes, "_load_sessions", load_sessions)

    response = await tui_routes.get_tui_bootstrap(
        request=SimpleNamespace(headers={}),
        pillars="computers,projects,sessions",
        identity=_identity(),
    )

    assert response.requested == ["computers", "projects", "sessions"]
    assert response.complete is False
    assert response.data.computers == [computer]
    assert response.data.projects_with_todos is None
    assert response.data.sessions == [session]
    assert [(error.pillar, error.message, error.retryable) for error in response.errors] == [
        ("projects", "projects warming", True)
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tui_bootstrap_only_loads_requested_pillars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry requests can ask only for the missing pillars."""
    load_projects = AsyncMock(return_value=[])
    load_sessions = AsyncMock()
    monkeypatch.setattr(tui_routes, "_load_projects_with_todos", load_projects)
    monkeypatch.setattr(tui_routes, "_load_sessions", load_sessions)

    response = await tui_routes.get_tui_bootstrap(
        request=SimpleNamespace(headers={}),
        pillars="projects",
        identity=_identity(),
    )

    assert response.complete is True
    assert response.requested == ["projects"]
    load_projects.assert_awaited_once()
    load_sessions.assert_not_called()
