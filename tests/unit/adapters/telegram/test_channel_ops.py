"""Characterization tests for teleclaude.adapters.telegram.channel_ops."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import BadRequest, TelegramError

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.telegram.channel_ops import TOPIC_READY_TIMEOUT_S, ChannelOperationsMixin
from teleclaude.core.models import ChannelMetadata, Session, SessionAdapterMetadata, TelegramAdapterMetadata


class _StubChannelOps(ChannelOperationsMixin):
    """Minimal concrete implementation for testing ChannelOperationsMixin."""

    def __init__(self) -> None:
        self.supergroup_id = 12345
        self._topic_creation_locks: dict[str, asyncio.Lock] = {}
        self._topic_ready_events: dict[int, asyncio.Event] = {}
        self._topic_ready_cache: set[int] = set()
        self._qos_scheduler = MagicMock()

    @property
    def bot(self):
        raise NotImplementedError

    def _ensure_started(self) -> None:
        pass


def _make_session(session_id: str = "sess-1", topic_id: int | None = None) -> Session:
    return Session(
        session_id=session_id,
        computer_name="test-computer",
        tmux_session_name=f"tmux-{session_id}",
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=topic_id)),
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_topic_ready_timeout_is_five_seconds():
    assert TOPIC_READY_TIMEOUT_S == 5.0


# ---------------------------------------------------------------------------
# discover_peers
# ---------------------------------------------------------------------------


async def test_discover_peers_returns_empty_list():
    ops = _StubChannelOps()
    result = await ops.discover_peers()
    assert result == []


# ---------------------------------------------------------------------------
# get_all_topics
# ---------------------------------------------------------------------------


async def test_get_all_topics_returns_empty_list():
    ops = _StubChannelOps()
    result = await ops.get_all_topics()
    assert result == []


# ---------------------------------------------------------------------------
# _wait_for_topic_ready
# ---------------------------------------------------------------------------


async def test_wait_for_topic_ready_returns_immediately_when_in_cache():
    ops = _StubChannelOps()
    ops._topic_ready_cache.add(99)
    await ops._wait_for_topic_ready(99, "test-topic")
    assert 99 in ops._topic_ready_cache


async def test_wait_for_topic_ready_adds_to_cache_after_event_set():
    ops = _StubChannelOps()
    event = asyncio.Event()
    ops._topic_ready_events[42] = event
    event.set()  # Simulate topic ready signal
    await ops._wait_for_topic_ready(42, "test-topic")
    assert 42 in ops._topic_ready_cache


async def test_wait_for_topic_ready_adds_to_cache_on_timeout():
    """On timeout, the TimeoutError handler adds topic_id to cache and removes the pending event."""
    ops = _StubChannelOps()
    event = asyncio.Event()  # never set — will time out
    event.wait = AsyncMock(side_effect=TimeoutError)
    ops._topic_ready_events[77] = event

    await ops._wait_for_topic_ready(77, "timeout-topic")

    assert 77 in ops._topic_ready_cache
    assert 77 not in ops._topic_ready_events


# ---------------------------------------------------------------------------
# create_channel
# ---------------------------------------------------------------------------


async def test_create_channel_returns_topic_id_as_string():
    """Happy path: creates a new forum topic and returns its ID as a string."""
    ops = _StubChannelOps()
    session = _make_session(topic_id=None)

    topic = MagicMock()
    topic.message_thread_id = 999
    ops._create_forum_topic_with_retry = AsyncMock(return_value=topic)

    updated_session = _make_session(topic_id=None)

    with patch("teleclaude.adapters.telegram.channel_ops.db") as mock_db:
        mock_db.get_session = AsyncMock(side_effect=[session, updated_session])
        mock_db.update_session = AsyncMock()
        result = await ops.create_channel(session, "Test Topic", ChannelMetadata())

    assert result == "999"


async def test_create_channel_returns_existing_topic_id_without_creating_duplicate():
    """Deduplication: if session already has a topic_id, return it without creating another."""
    ops = _StubChannelOps()
    session = _make_session()
    existing = _make_session(topic_id=55)
    ops._create_forum_topic_with_retry = AsyncMock()

    with patch("teleclaude.adapters.telegram.channel_ops.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=existing)
        topic_id = await ops.create_channel(session, "Existing Topic", ChannelMetadata())

    assert topic_id == "55"
    ops._create_forum_topic_with_retry.assert_not_called()


# ---------------------------------------------------------------------------
# update_channel_title
# ---------------------------------------------------------------------------


async def test_update_channel_title_raises_when_topic_id_missing():
    ops = _StubChannelOps()
    session = _make_session(topic_id=None)

    with pytest.raises(AdapterError):
        await ops.update_channel_title(session, "New Title")


async def test_update_channel_title_returns_true_on_success():
    ops = _StubChannelOps()
    session = _make_session(topic_id=91)
    ops._edit_forum_topic_with_retry = AsyncMock()

    result = await ops.update_channel_title(session, "Renamed")

    ops._edit_forum_topic_with_retry.assert_awaited_once_with(91, "Renamed")
    assert result is True


async def test_update_channel_title_returns_false_on_telegram_error():
    ops = _StubChannelOps()
    session = _make_session(topic_id=42)
    ops._edit_forum_topic_with_retry = AsyncMock(side_effect=TelegramError("boom"))

    result = await ops.update_channel_title(session, "Broken")

    assert result is False


# ---------------------------------------------------------------------------
# close_channel
# ---------------------------------------------------------------------------


async def test_close_channel_returns_false_when_topic_id_missing():
    ops = _StubChannelOps()
    session = _make_session(topic_id=None)

    result = await ops.close_channel(session)

    assert result is False


async def test_close_channel_returns_true_on_success():
    ops = _StubChannelOps()
    session = _make_session(topic_id=88)
    ops._close_forum_topic_with_retry = AsyncMock()

    result = await ops.close_channel(session)

    assert result is True
    ops._close_forum_topic_with_retry.assert_awaited_once_with(88)


# ---------------------------------------------------------------------------
# reopen_channel
# ---------------------------------------------------------------------------


async def test_reopen_channel_raises_when_topic_id_missing():
    ops = _StubChannelOps()
    session = _make_session(topic_id=None)

    with pytest.raises(AdapterError, match="Session missing telegram topic_id"):
        await ops.reopen_channel(session)


async def test_reopen_channel_returns_true_on_success():
    ops = _StubChannelOps()
    session = _make_session(topic_id=77)
    ops._reopen_forum_topic_with_retry = AsyncMock()

    result = await ops.reopen_channel(session)

    assert result is True
    ops._reopen_forum_topic_with_retry.assert_awaited_once_with(77)


# ---------------------------------------------------------------------------
# delete_channel
# ---------------------------------------------------------------------------


async def test_delete_channel_returns_false_when_topic_id_missing():
    ops = _StubChannelOps()
    session = _make_session(topic_id=None)

    result = await ops.delete_channel(session)

    assert result is False


async def test_delete_channel_returns_true_and_clears_persisted_topic_id():
    """Happy path: deletes topic and clears topic_id from persisted session."""
    ops = _StubChannelOps()
    session = _make_session(topic_id=55)
    ops._delete_forum_topic_with_retry = AsyncMock()

    fresh_session = _make_session(session_id=session.session_id, topic_id=55)

    with patch("teleclaude.adapters.telegram.channel_ops.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=fresh_session)
        mock_db.update_session = AsyncMock()
        result = await ops.delete_channel(session)

    assert result is True
    assert fresh_session.get_metadata().get_ui().get_telegram().topic_id is None
    ops._delete_forum_topic_with_retry.assert_awaited_once_with(55)


async def test_delete_channel_treats_topic_id_invalid_as_success_and_clears_metadata():
    """BadRequest('topic_id_invalid') means the topic was already gone — treat as success."""
    ops = _StubChannelOps()
    session = _make_session(topic_id=88)
    fresh_session = _make_session(session_id=session.session_id, topic_id=88)
    ops._delete_forum_topic_with_retry = AsyncMock(side_effect=BadRequest("Topic_id_invalid"))

    with patch("teleclaude.adapters.telegram.channel_ops.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=fresh_session)
        mock_db.update_session = AsyncMock()

        result = await ops.delete_channel(session)

    assert result is True
    assert fresh_session.get_metadata().get_ui().get_telegram().topic_id is None


# ---------------------------------------------------------------------------
# drop_pending_output
# ---------------------------------------------------------------------------


def test_drop_pending_output_delegates_to_qos_scheduler():
    ops = _StubChannelOps()
    ops._qos_scheduler = MagicMock()
    ops._qos_scheduler.drop_pending.return_value = 3
    result = ops.drop_pending_output("session-1")
    ops._qos_scheduler.drop_pending.assert_called_once_with("session-1")
    assert result == 3
