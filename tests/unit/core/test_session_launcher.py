"""Characterization tests for teleclaude.core.session_launcher."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from teleclaude.core import session_launcher
from teleclaude.core.models import SessionLaunchIntent, SessionLaunchKind
from teleclaude.types.commands import CreateSessionCommand


@pytest.mark.unit
def test_validate_launch_intent_rejects_incomplete_agent_then_message() -> None:
    intent = SessionLaunchIntent(
        kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
        agent="claude",
        thinking_mode="slow",
        message=None,
    )

    with pytest.raises(ValueError, match="agent_then_message"):
        session_launcher._validate_launch_intent(intent)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_headless_create_session_skips_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    create_empty = AsyncMock(return_value={"session_id": "headless-001", "tmux_session_name": ""})
    queued: list[tuple[object, str]] = []

    monkeypatch.setattr(session_launcher, "create_empty_session", create_empty)

    result = await session_launcher.create_session(
        CreateSessionCommand(project_path="/repo", origin="terminal", headless=True),
        client=object(),
        queue_background_task=lambda coro, label: queued.append((coro, label)),
        bootstrap_session=AsyncMock(),
    )

    assert result["session_id"] == "headless-001"
    assert not queued


@pytest.mark.unit
@pytest.mark.asyncio
async def test_agent_then_message_queues_bootstrap_with_launch_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    create_tmux = AsyncMock(return_value={"session_id": "sess-1", "tmux_session_name": "tc_sess_1"})
    queued: list[tuple[object, str]] = []

    monkeypatch.setattr(session_launcher, "create_tmux_session", create_tmux)

    intent = SessionLaunchIntent(
        kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
        agent="codex",
        thinking_mode="slow",
        message="hello",
    )
    bootstrap = AsyncMock()

    result = await session_launcher.create_session(
        CreateSessionCommand(
            project_path="/repo",
            origin="terminal",
            launch_intent=intent,
        ),
        client=object(),
        queue_background_task=lambda coro, label: queued.append((coro, label)),
        bootstrap_session=bootstrap,
    )

    assert result["session_id"] == "sess-1"
    assert len(queued) == 1
    queued_coro, queued_label = queued[0]
    assert queued_label == "session_bootstrap:sess-1"
    queued_coro.close()
    bootstrap.assert_not_awaited()
