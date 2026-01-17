from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core import session_launcher
from teleclaude.core.events import EventContext
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

    def _queue_background_task(*_args, **_kwargs) -> None:
        order.append("queue")

    monkeypatch.setattr(session_launcher, "handle_create_session", _fake_create_session)

    metadata = MessageMetadata(adapter_type="telegram")
    metadata.launch_intent = SessionLaunchIntent(
        kind=SessionLaunchKind.AGENT,
        agent="claude",
        thinking_mode="slow",
    )

    result = await session_launcher.create_session(
        context=MagicMock(spec=EventContext),
        args=[],
        metadata=metadata,
        client=MagicMock(),
        execute_auto_command=_fake_execute_auto_command,
        queue_background_task=_queue_background_task,
    )

    assert order == ["create", "auto"]
    assert result["session_id"] == "s1"
