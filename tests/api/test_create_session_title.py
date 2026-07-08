from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.api import sessions_routes
from teleclaude.api.auth import CallerIdentity
from teleclaude.api_models import CreateSessionRequest
from teleclaude.constants import EVENT_NEW_SESSION
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import CreateSessionCommand


@pytest.mark.asyncio
async def test_create_session_route_threads_requested_title_to_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requested_title = "Job: recurring-summary"
    captured_commands: list[CreateSessionCommand] = []

    async def dispatch_command(_client: object, command: object) -> dict[str, str]:
        assert isinstance(command, CreateSessionCommand)
        captured_commands.append(command)
        return {"session_id": "created-session", "tmux_session_name": "tmux-created"}

    async def guard_generic_create_session(
        _request: CreateSessionRequest,
        _command: object,
        _identity: CallerIdentity,
    ) -> None:
        return None

    monkeypatch.setattr(sessions_routes, "dispatch_command", dispatch_command)
    monkeypatch.setattr(sessions_routes, "guard_generic_create_session", guard_generic_create_session)
    monkeypatch.setattr(sessions_routes._STATE, "client", object())

    request = CreateSessionRequest(
        computer="local",
        project_path=str(tmp_path),
        launch_kind="empty",
        title=requested_title,
    )
    identity = CallerIdentity(
        session_id="",
        system_role=None,
        human_role="admin",
        tmux_session_name=None,
        email="admin@example.test",
    )

    await sessions_routes.create_session(request, identity)

    assert captured_commands[0].title == requested_title


def test_command_mapper_sets_create_session_title_from_api_payload(tmp_path: Path) -> None:
    requested_title = "Job: recurring-summary"
    metadata = MessageMetadata(
        origin=InputOrigin.TERMINAL.value,
        project_path=str(tmp_path),
    )

    command = CommandMapper.map_api_input(
        EVENT_NEW_SESSION,
        {"title": requested_title},
        metadata,
        computer="local",
    )

    assert isinstance(command, CreateSessionCommand)
    assert command.title == requested_title
