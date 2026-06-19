"""Regression coverage for per-project integrator spawn scoping."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from teleclaude.constants import JobRole
from teleclaude.core import integration_bridge

_PROJECT = "/Users/x/Workspace/TeleClaude"
_OTHER_PROJECT = "/Users/x/Workspace/itsUP"
_SPAWNED_STATUS = "spawned"


@dataclass(frozen=True)
class _StubSession:
    session_id: str
    job: str | None
    project_path: str | None


def _spawn_args() -> dict[str, str]:
    return {
        "slug": "demo-slug",
        "branch": "demo-slug",
        "sha": "abc12345",
        "caller_session_id": "orchestrator-1",
        "project_path": _PROJECT,
    }


async def test_integrator_in_other_project_does_not_block_spawn() -> None:
    """An integrator running in another project must not starve this project's spawn."""
    sessions = [_StubSession(session_id="s-other", job=JobRole.INTEGRATOR, project_path=_OTHER_PROJECT)]
    command_service = MagicMock()
    command_service.create_session = AsyncMock()

    with (
        patch.object(integration_bridge.db, "list_sessions", AsyncMock(return_value=sessions)),
        patch.object(integration_bridge, "get_command_service", return_value=command_service),
    ):
        result = await integration_bridge.spawn_integrator_session(**_spawn_args())

    assert result is not None
    assert result["status"] == _SPAWNED_STATUS
    command_service.create_session.assert_awaited_once()


async def test_integrator_in_same_project_blocks_spawn() -> None:
    """An integrator already open for this project leaves the existing one undisturbed."""
    sessions = [_StubSession(session_id="s-same", job=JobRole.INTEGRATOR, project_path=_PROJECT)]
    command_service = MagicMock()
    command_service.create_session = AsyncMock()

    with (
        patch.object(integration_bridge.db, "list_sessions", AsyncMock(return_value=sessions)),
        patch.object(integration_bridge, "get_command_service", return_value=command_service),
    ):
        result = await integration_bridge.spawn_integrator_session(**_spawn_args())

    assert result is None
    command_service.create_session.assert_not_awaited()
