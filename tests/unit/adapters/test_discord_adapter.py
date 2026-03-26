from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.discord_adapter import DiscordAdapter
from teleclaude.core.models import DiscordAdapterMetadata, Session

pytestmark = pytest.mark.unit


def _make_session(session_id: str = "session-1", **discord_fields: object) -> Session:
    discord_section = DiscordAdapterMetadata(**discord_fields).to_dict() if discord_fields else {}
    return Session(
        session_id=session_id,
        computer_name="machine",
        tmux_session_name="tmux-session",
        title="Session",
        origin_metadata={"discord": discord_section},
    )


def _make_adapter() -> DiscordAdapter:
    return object.__new__(DiscordAdapter)


async def _sample_async_callable() -> str:  # pyright: ignore[reportUnusedFunction]
    return "ok"


@pytest.mark.asyncio
async def test_get_enabled_agents_returns_agent_names() -> None:
    adapter = _make_adapter()
    agents = {
        "alpha": SimpleNamespace(enabled=True),
        "beta": SimpleNamespace(enabled=False),
        "gamma": SimpleNamespace(enabled=True),
    }

    with patch(
        "teleclaude.adapters.discord_adapter.config",
        SimpleNamespace(agents=agents),
    ):
        enabled_agents = adapter._get_enabled_agents()

    assert enabled_agents == ["alpha", "gamma"]


@pytest.mark.asyncio
async def test_store_and_clear_output_message_id_use_origin_metadata() -> None:
    adapter = _make_adapter()
    session = _make_session()

    with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
        mock_db.update_origin_metadata = AsyncMock()

        await adapter._store_output_message_id(session, "discord-message-1")
        assert mock_db.update_origin_metadata.await_count == 1

        await adapter._clear_output_message_id(session)
        assert mock_db.update_origin_metadata.await_count == 2


@pytest.mark.asyncio
async def test_get_output_message_id_reads_from_origin_metadata() -> None:
    adapter = _make_adapter()
    session = _make_session()
    session.origin_metadata["discord"] = {"output_message_id": "fresh-discord-msg"}

    fresh_session = _make_session()
    fresh_session.origin_metadata["discord"] = {"output_message_id": "fresh-discord-msg"}

    with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=fresh_session)
        result = await adapter._get_output_message_id(session)

    assert result == "fresh-discord-msg"
