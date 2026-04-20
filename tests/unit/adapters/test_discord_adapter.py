"""Unit tests for Discord adapter helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.base_adapter import AdapterError, ChannelNotProvisionedError
from teleclaude.adapters.discord_adapter import DISCORD_TYPING_INTERVAL_S, DiscordAdapter
from teleclaude.adapters.qos.action_throttler import AdapterActionThrottler
from teleclaude.adapters.ui.threaded_output import OverflowContext
from teleclaude.core.events import SessionUpdatedContext
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


@pytest.mark.asyncio
async def test_recover_lane_error_swallows_stale_metadata_cleanup() -> None:
    adapter = _make_adapter()
    session = _make_session()

    with patch("teleclaude.adapters.discord_adapter.logger") as mock_logger:
        result = await adapter.recover_lane_error(
            session,
            AdapterError("Discord channel 123 not found (metadata cleared)"),
            AsyncMock(),
            "Session",
        )

    assert result is None
    mock_logger.info.assert_called_once()
    mock_logger.warning.assert_not_called()
    mock_logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_recover_lane_error_swallows_channel_not_provisioned() -> None:
    adapter = _make_adapter()
    session = _make_session()

    with patch("teleclaude.adapters.discord_adapter.logger") as mock_logger:
        result = await adapter.recover_lane_error(
            session,
            ChannelNotProvisionedError("Session session-1 has no discord channel mapping yet"),
            AsyncMock(),
            "Session",
        )

    assert result is None
    mock_logger.info.assert_called_once()
    mock_logger.warning.assert_not_called()
    mock_logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_recover_lane_error_re_raises_unknown_errors() -> None:
    adapter = _make_adapter()
    session = _make_session()

    with pytest.raises(AdapterError, match="boom"):
        await adapter.recover_lane_error(
            session,
            AdapterError("boom"),
            AsyncMock(),
            "Session",
        )


@pytest.mark.asyncio
async def test_convert_markdown_for_platform_normalizes_markdown_links() -> None:
    adapter = _make_adapter()

    rendered = adapter._convert_markdown_for_platform(
        "[session-output-routing.md](/Users/test/project/docs/project/spec/session-output-routing.md)"
    )

    assert rendered == (
        "`session-output-routing.md`: `/Users/test/project/docs/project/spec/session-output-routing.md`"
    )


def test_get_action_throttle_interval_uses_discord_typing_window() -> None:
    adapter = _make_adapter()
    adapter._action_throttler = AdapterActionThrottler()

    assert adapter.get_action_throttle_interval_s("typing") == pytest.approx(DISCORD_TYPING_INTERVAL_S)


def test_finalize_overflow_split_uses_previous_newline() -> None:
    adapter = _make_adapter()

    split_idx, chunk = adapter._finalize_overflow_split(
        "first line\nsecond line\nthird line",
        OverflowContext(continuation_prefix="", available_for_content=22),
        0,
        "unused",
    )

    assert split_idx == len("first line\nsecond line\n")
    assert chunk == "first line\nsecond line"


def test_finalize_overflow_split_starts_new_message_for_next_full_line() -> None:
    adapter = _make_adapter()

    split_idx, chunk = adapter._finalize_overflow_split(
        "1234\n5678\n90",
        OverflowContext(continuation_prefix="", available_for_content=10),
        0,
        "unused",
    )

    assert split_idx == len("1234\n5678\n")
    assert chunk == "1234\n5678"


def test_finalize_overflow_split_raises_when_no_newline_exists_before_limit() -> None:
    adapter = _make_adapter()

    with pytest.raises(ValueError, match="line packing"):
        adapter._finalize_overflow_split(
            "single very long line without separators",
            OverflowContext(continuation_prefix="", available_for_content=20),
            20,
            "unused",
        )


@pytest.mark.asyncio
async def test_session_updated_refreshes_thread_topper_when_agent_fields_change() -> None:
    adapter = _make_adapter()
    session = _make_session(thread_id="123", thread_topper_message_id="topper-1")
    session.active_agent = "codex"
    session.thinking_mode = "slow"

    with (
        patch("teleclaude.adapters.discord_adapter.db.get_session", AsyncMock(return_value=session)),
        patch.object(adapter, "edit_message", AsyncMock(return_value=True)) as edit_message,
        patch.object(adapter, "_build_thread_topper", return_value="project: TeleClaude | agent: codex/slow"),
    ):
        await adapter._handle_session_updated(
            "session_updated",
            SessionUpdatedContext(session_id=session.session_id, updated_fields={"active_agent": "codex"}),
        )

    edit_message.assert_awaited_once_with(
        session,
        "topper-1",
        "project: TeleClaude | agent: codex/slow",
    )
