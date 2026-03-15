"""Characterization tests for agent availability routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import agents_routes
from teleclaude.api_models import AgentStatusRequest


class TestAgentsRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_agent_availability_marks_disabled_agents_and_db_failures(self) -> None:
        """Availability listing preserves config-disabled agents and DB read failures."""
        config_stub = SimpleNamespace(
            agents={
                "claude": SimpleNamespace(enabled=False),
                "codex": SimpleNamespace(enabled=True),
            }
        )

        with (
            patch("teleclaude.api.agents_routes.get_known_agents", return_value=["claude", "codex"]),
            patch("teleclaude.api.agents_routes.config", config_stub),
            patch("teleclaude.api.agents_routes.db") as db,
        ):
            db.get_agent_availability = AsyncMock(side_effect=[RuntimeError("db down")])

            response = await agents_routes.get_agent_availability(identity=object())

        assert response["claude"].model_dump()["status"] == "unavailable"
        assert response["claude"].model_dump()["reason"]  # non-empty reason present
        assert response["codex"].model_dump()["available"] is None
        assert response["codex"].model_dump()["error"]  # non-empty error present

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_set_agent_status_marks_degraded_and_returns_updated_dto(self) -> None:
        """Degraded status requests call the DB helper and return the refreshed DTO."""
        request = AgentStatusRequest(status="degraded", reason="latency", duration_minutes=5)
        refreshed = {
            "available": False,
            "status": "degraded",
            "degraded_until": "2025-03-15T12:05:00+00:00",
            "reason": "latency",
        }

        with (
            patch("teleclaude.api.agents_routes.normalize_agent_name", return_value="codex"),
            patch("teleclaude.api.agents_routes.db") as db,
        ):
            db.mark_agent_degraded = AsyncMock()
            db.get_agent_availability = AsyncMock(return_value=refreshed)

            response = await agents_routes.set_agent_status("Codex", request, identity=object())

        assert response["status"] == "degraded"
        assert response["reason"] == "latency"
        db.mark_agent_degraded.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_set_agent_status_requires_reason_for_unavailable_requests(self) -> None:
        """Unavailable status requests must provide an explicit reason."""
        request = AgentStatusRequest(status="unavailable")

        with patch("teleclaude.api.agents_routes.normalize_agent_name", return_value="claude"):
            with pytest.raises(HTTPException) as exc_info:
                await agents_routes.set_agent_status("claude", request, identity=object())

        assert exc_info.value.status_code == 400
