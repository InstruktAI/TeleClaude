from unittest.mock import MagicMock

import pytest

from teleclaude.core import session_launcher
from teleclaude.core.models import MessageMetadata, SessionLaunchIntent, SessionLaunchKind


@pytest.mark.asyncio
async def test_create_session_runs_auto_command_after_create(monkeypatch):
    """Auto command must run only after session creation completes."""
    order: list[str] = []

    async def _fake_create_session(*_args, **_kwargs):
        order.append("create")
        return {"session_id": "s1", "tmux_session_name": "tc_s1"}

    async def _fake_execute_auto_command(session_id: str, _cmd: str):
        order.append("auto")
        assert session_id == "s1"
        return {"status": "success", "message": "ok"}

    async def _fake_bootstrap_session(session_id: str, _cmd: str | None) -> None:
        order.append("bootstrap")
        assert session_id == "s1"

    def _queue_background_task(coro, _name) -> None:
        order.append("queue")
        coro.close()

    monkeypatch.setattr(session_launcher, "create_tmux_session", _fake_create_session)

    metadata = MessageMetadata(origin="telegram")
    metadata.launch_intent = SessionLaunchIntent(
        kind=SessionLaunchKind.AGENT,
        agent="claude",
        thinking_mode="slow",
    )

    from teleclaude.types.commands import CreateSessionCommand

    cmd = CreateSessionCommand(project_path=".", origin="telegram", launch_intent=metadata.launch_intent)

    result = await session_launcher.create_session(
        cmd=cmd,
        client=MagicMock(),
        execute_auto_command=_fake_execute_auto_command,
        queue_background_task=_queue_background_task,
        bootstrap_session=_fake_bootstrap_session,
    )

    assert order == ["create", "queue"]
    assert result["session_id"] == "s1"
    assert result["auto_command_status"] == "queued"
