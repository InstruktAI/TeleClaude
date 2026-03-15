from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord_adapter import DiscordAdapter
from teleclaude.core.models import Session

pytestmark = pytest.mark.unit


def _make_session(session_id: str = "session-1") -> Session:
    return Session(
        session_id=session_id,
        computer_name="machine",
        tmux_session_name="tmux-session",
        title="Session",
    )


def _make_adapter() -> DiscordAdapter:
    return object.__new__(DiscordAdapter)


async def _sample_async_callable() -> str:
    return "ok"


def test_require_async_callable_returns_original_callable() -> None:
    result = DiscordAdapter._require_async_callable(_sample_async_callable, label="callback")

    assert result is _sample_async_callable


def test_require_async_callable_raises_for_non_callable_value() -> None:
    with pytest.raises(AdapterError):
        DiscordAdapter._require_async_callable(None, label="callback")


def test_get_enabled_agents_keeps_only_truthy_enabled_entries() -> None:
    adapter = _make_adapter()

    with patch(
        "teleclaude.adapters.discord_adapter.config",
        SimpleNamespace(
            agents={
                "alpha": SimpleNamespace(enabled=True),
                "beta": SimpleNamespace(enabled=False),
                "gamma": SimpleNamespace(enabled=1),
            }
        ),
    ):
        enabled_agents = adapter._get_enabled_agents()

    assert enabled_agents == ["alpha", "gamma"]


@pytest.mark.asyncio
async def test_store_and_clear_output_message_id_update_session_metadata_and_db() -> None:
    adapter = _make_adapter()
    session = _make_session()

    with patch("teleclaude.adapters.discord_adapter.db") as db:
        db.update_session = AsyncMock()

        await adapter._store_output_message_id(session, "discord-message-1")
        await adapter._clear_output_message_id(session)

    discord_meta = session.get_metadata().get_ui().get_discord()

    assert discord_meta.output_message_id is None
    assert db.update_session.await_count == 2
    db.update_session.assert_any_await("session-1", adapter_metadata=session.adapter_metadata)


@pytest.mark.asyncio
async def test_get_output_message_id_prefers_fresh_db_session_before_fallback() -> None:
    adapter = _make_adapter()
    stale_session = _make_session()
    stale_session.get_metadata().get_ui().get_discord().output_message_id = "stale-message"

    fresh_session = _make_session()
    fresh_session.get_metadata().get_ui().get_discord().output_message_id = "fresh-message"

    with patch("teleclaude.adapters.discord_adapter.db") as db:
        db.get_session = AsyncMock(return_value=fresh_session)

        fresh_result = await adapter._get_output_message_id(stale_session)

    assert fresh_result == "fresh-message"
    db.get_session.assert_awaited_once_with("session-1")

    with patch("teleclaude.adapters.discord_adapter.db") as db:
        db.get_session = AsyncMock(return_value=None)

        fallback_result = await adapter._get_output_message_id(stale_session)

    assert fallback_result == "stale-message"
