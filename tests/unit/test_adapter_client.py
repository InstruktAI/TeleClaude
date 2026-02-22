"""Paranoid tests for AdapterClient peer discovery aggregation."""

import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.models import (
    CleanupTrigger,
    PeerInfo,
    Session,
    SessionAdapterMetadata,
    TelegramAdapterMetadata,
)
from teleclaude.core.origins import InputOrigin

FIXED_NOW = datetime(2024, 1, 1, 12, 0, 0)


class DummyTelegramAdapter(UiAdapter):
    ADAPTER_KEY = "telegram"

    def __init__(
        self,
        adapter_client,
        *,
        error: Exception | None = None,
        error_sequence: list[Exception] | None = None,
        send_message_return: str | None = None,
    ) -> None:
        super().__init__(adapter_client)
        self._error = error
        self._error_sequence = list(error_sequence) if error_sequence else []
        self.sent_messages: list[str] = []
        self.deleted_channels: list[str] = []
        if send_message_return is not None:

            async def record_send_message(_session, _text, *, metadata=None, multi_message=False) -> str:  # type: ignore[override]
                _ = (metadata, multi_message)
                self.sent_messages.append(_text)
                return send_message_return

            self.send_message = record_send_message  # type: ignore[assignment]

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def create_channel(self, _session, _title, metadata) -> str:
        _ = metadata
        return "topic"

    async def update_channel_title(self, _session, _title) -> bool:
        return True

    async def close_channel(self, _session) -> bool:
        return True

    async def reopen_channel(self, _session) -> bool:
        return True

    async def delete_channel(self, _session) -> bool:
        self.deleted_channels.append(_session.session_id)
        return True

    async def send_message(self, _session, _text, *, metadata=None, multi_message=False) -> str:
        _ = (metadata, multi_message)
        return "msg"

    async def edit_message(self, _session, _message_id, _text, *, metadata=None) -> bool:
        _ = metadata
        return True

    async def delete_message(self, _session, _message_id) -> bool:
        return True

    async def send_file(self, _session, _file_path, *, caption=None, metadata=None) -> str:
        _ = (caption, metadata)
        return "file"

    async def discover_peers(self):
        return []

    async def poll_output_stream(self, _session, timeout: float = 300.0):
        if False:  # pragma: no cover - generator shape
            yield timeout

    def get_max_message_length(self) -> int:
        return 4096

    def get_ai_session_poll_interval(self) -> float:
        return 1.0

    async def send_output_update(self, *_args, **_kwargs):  # type: ignore[override]
        if self._error_sequence:
            raise self._error_sequence.pop(0)
        if self._error is not None:
            raise self._error
        return "msg"

    async def recover_lane_error(self, session, error, task_factory, display_title):
        """Simulate Telegram-style recovery for missing thread errors."""
        msg = str(error).lower()
        if "message thread not found" not in msg and "topic_deleted" not in msg:
            raise error
        return await task_factory(self, session)


class DummyFailingAdapter(UiAdapter):
    ADAPTER_KEY = "dummy"

    def __init__(self, adapter_client, *, error: Exception) -> None:
        super().__init__(adapter_client)
        self._error = error

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def create_channel(self, _session, _title, metadata) -> str:
        _ = metadata
        return "topic"

    async def update_channel_title(self, _session, _title) -> bool:
        return True

    async def close_channel(self, _session) -> bool:
        return True

    async def reopen_channel(self, _session) -> bool:
        return True

    async def delete_channel(self, _session) -> bool:
        return True

    async def send_message(self, _session, _text, *, metadata=None, multi_message=False) -> str:
        _ = (metadata, multi_message)
        raise self._error

    async def edit_message(self, _session, _message_id, _text, *, metadata=None) -> bool:
        _ = metadata
        return True

    async def delete_message(self, _session, _message_id) -> bool:
        return True

    async def send_file(self, _session, _file_path, *, caption=None, metadata=None) -> str:
        _ = (caption, metadata)
        return "file"

    async def discover_peers(self):
        return []

    async def poll_output_stream(self, _session, timeout: float = 300.0):
        if False:  # pragma: no cover - generator shape
            yield timeout

    def get_max_message_length(self) -> int:
        return 4096

    def get_ai_session_poll_interval(self) -> float:
        return 1.0

    async def send_output_update(self, *_args, **_kwargs):  # type: ignore[override]
        raise self._error


@pytest.mark.asyncio
async def test_adapter_client_register_adapter():
    """Paranoid test adapter registration."""
    client = AdapterClient()

    # Create mock adapters
    mock_telegram_adapter = Mock()
    mock_redis_transport = Mock()

    # Register adapters
    client.register_adapter("telegram", mock_telegram_adapter)
    client.register_adapter("redis", mock_redis_transport)

    # Verify registration
    assert "telegram" in client.adapters
    assert "redis" in client.adapters
    assert client.adapters["telegram"] == mock_telegram_adapter
    assert client.adapters["redis"] == mock_redis_transport


@pytest.mark.asyncio
async def test_adapter_client_discover_peers_single_adapter():
    """Paranoid test peer discovery with single adapter."""
    client = AdapterClient()

    # Create mock adapter
    mock_client = Mock()
    mock_client.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="macbook",
                status="online",
                last_seen=FIXED_NOW,
                adapter_type="telegram",
            ),
            PeerInfo(
                name="workstation",
                status="online",
                last_seen=FIXED_NOW,
                adapter_type="telegram",
            ),
        ]
    )

    # Register adapter
    client.register_adapter("telegram", mock_client)

    # Test discovery (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 2
    assert peers[0]["name"] == "macbook"
    assert peers[1]["name"] == "workstation"


@pytest.mark.asyncio
async def test_adapter_client_discover_peers_multiple_adapters():
    """Paranoid test peer discovery aggregation from multiple adapters."""
    client = AdapterClient()

    # Create mock adapters with different peers
    mock_telegram = Mock()
    mock_telegram.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="macbook",
                status="online",
                last_seen=FIXED_NOW,
                adapter_type="telegram",
            )
        ]
    )

    mock_redis = Mock()
    mock_redis.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="workstation",
                status="online",
                last_seen=FIXED_NOW,
                adapter_type="redis",
            ),
            PeerInfo(
                name="server",
                status="online",
                last_seen=FIXED_NOW,
                adapter_type="redis",
            ),
        ]
    )

    # Register adapters
    client.register_adapter("telegram", mock_telegram)
    client.register_adapter("redis", mock_redis)

    # Test aggregation (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 3
    assert peers[0]["name"] == "macbook"
    assert peers[1]["name"] == "workstation"
    assert peers[2]["name"] == "server"


@pytest.mark.asyncio
async def test_non_ui_origin_broadcasts_to_all_ui():
    """Non-UI origin broadcasts to all registered UI adapters."""
    client = AdapterClient()
    ok_adapter = DummyTelegramAdapter(client, send_message_return="123")
    failing_adapter = DummyFailingAdapter(client, error=TimeoutError("Timed out"))

    client.register_adapter("telegram", ok_adapter)
    client.register_adapter("dummy", failing_adapter)

    session = Session(
        session_id="session-123",
        computer_name="test",
        tmux_session_name="test-tmux",
        last_input_origin=InputOrigin.API.value,
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=1)),
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        result = await client.send_message(session, "hello", ephemeral=False)

    assert result == "123"


@pytest.mark.asyncio
async def test_adapter_client_deduplication():
    """Paranoid test that duplicate peers are deduplicated (first adapter wins)."""
    client = AdapterClient()

    # Create mock adapters with overlapping peers
    now = FIXED_NOW
    mock_telegram = Mock()
    mock_telegram.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="macbook",
                status="online",
                last_seen=now,
                adapter_type="telegram",
            )
        ]
    )

    mock_redis = Mock()
    mock_redis.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="macbook",  # Duplicate!
                status="online",
                last_seen=now,
                adapter_type="redis",
            ),
            PeerInfo(
                name="workstation",
                status="online",
                last_seen=now,
                adapter_type="redis",
            ),
        ]
    )

    # Register adapters (order matters - first wins)
    client.register_adapter("telegram", mock_telegram)
    client.register_adapter("redis", mock_redis)

    # Test deduplication (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 2  # Not 3 - macbook deduplicated

    # First adapter (telegram) wins for "macbook"
    # Order: telegram peer was registered first, then redis peers.
    # macbook (telegram) and workstation (redis)
    assert peers[0]["name"] == "macbook"
    assert peers[0]["adapter_type"] == "telegram"
    assert peers[1]["name"] == "workstation"
    assert peers[1]["adapter_type"] == "redis"


@pytest.mark.asyncio
async def test_adapter_client_handles_adapter_errors():
    """Paranoid test that errors from one adapter don't break discovery from others."""
    client = AdapterClient()

    # Create mock adapters - one fails, one succeeds
    mock_failing_adapter = Mock()
    mock_failing_adapter.discover_peers = AsyncMock(side_effect=Exception("Connection failed"))

    mock_working_adapter = Mock()
    mock_working_adapter.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="workstation",
                status="online",
                last_seen=FIXED_NOW,
                adapter_type="redis",
            )
        ]
    )

    # Register both adapters
    client.register_adapter("telegram", mock_failing_adapter)
    client.register_adapter("redis", mock_working_adapter)

    # Test that discovery continues despite failure (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 1
    assert peers[0]["name"] == "workstation"


@pytest.mark.asyncio
async def test_adapter_client_empty_peers():
    """Paranoid test behavior when no peers are discovered."""
    client = AdapterClient()

    # Create mock adapter with no peers
    mock_client = Mock()
    mock_client.discover_peers = AsyncMock(return_value=[])

    client.register_adapter("telegram", mock_client)

    # Test empty result (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 0
    assert peers == []


@pytest.mark.asyncio
async def test_adapter_client_no_adapters():
    """Paranoid test behavior when no adapters are registered."""
    client = AdapterClient()

    # Test discovery with no adapters (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 0
    assert peers == []


@pytest.mark.asyncio
async def test_adapter_client_system_stats_passthrough():
    """Paranoid test that system_stats are passed through from PeerInfo to dict."""
    client = AdapterClient()

    # Create mock adapter with system_stats
    mock_adapter = Mock()
    mock_adapter.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="server",
                status="online",
                last_seen=FIXED_NOW,
                adapter_type="redis",
                user="testuser",
                host="server.local",
                role="development",
                system_stats={
                    "memory": {"total_gb": 16.0, "available_gb": 8.0, "percent_used": 50.0},
                    "disk": {"total_gb": 500.0, "free_gb": 250.0, "percent_used": 50.0},
                    "cpu": {"percent_used": 25.0},
                },
            )
        ]
    )

    client.register_adapter("redis", mock_adapter)

    # Test that system_stats are passed through (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 1
    assert peers[0]["name"] == "server"
    assert peers[0]["role"] == "development"
    assert "system_stats" in peers[0]
    assert peers[0]["system_stats"]["memory"]["total_gb"] == 16.0
    assert peers[0]["system_stats"]["cpu"]["percent_used"] == 25.0


@pytest.mark.asyncio
async def test_adapter_client_discover_peers_redis_disabled():
    """Paranoid test that discover_peers returns empty list when Redis is disabled."""
    client = AdapterClient()

    # Create mock adapter that would return peers
    mock_adapter = Mock()
    mock_adapter.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="should-not-appear",
                status="online",
                last_seen=FIXED_NOW,
                adapter_type="redis",
            )
        ]
    )

    client.register_adapter("redis", mock_adapter)

    # Test with Redis disabled - should return empty list without calling adapter
    peers = await client.discover_peers(redis_enabled=False)
    assert len(peers) == 0
    assert peers == []


@pytest.mark.asyncio
async def test_send_output_update_missing_thread_recovers_via_adapter():
    """Adapter's recover_lane_error handles missing-thread errors transparently."""
    client = AdapterClient()
    client.register_adapter(
        "telegram",
        DummyTelegramAdapter(client, error_sequence=[Exception("Message thread not found")]),
    )

    session = Session(
        session_id="session-123",
        computer_name="test",
        tmux_session_name="tc_session",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(
            telegram=TelegramAdapterMetadata(topic_id=123, output_message_id="msg-1")
        ),
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    mock_db.get_pending_deletions = AsyncMock(return_value=[])
    with patch("teleclaude.core.adapter_client.db", mock_db):
        result = await client.send_output_update(session, "output", 0.0, 0.0)
    assert result == "msg"


@pytest.mark.asyncio
async def test_send_output_update_non_ui_origin_broadcasts_to_all_ui():
    """Non-UI origin (api) broadcasts output to all registered UI adapters."""
    client = AdapterClient()
    adapter = DummyTelegramAdapter(client)
    client.register_adapter("telegram", adapter)

    session = Session(
        session_id="session-456",
        computer_name="test",
        tmux_session_name="tc_session_456",
        last_input_origin=InputOrigin.API.value,
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(
            telegram=TelegramAdapterMetadata(topic_id=456, output_message_id="msg-2")
        ),
    )

    mock_db = AsyncMock()
    mock_db.get_pending_deletions = AsyncMock(return_value=[])
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        result = await client.send_output_update(session, "output", 0.0, 0.0)
    assert result == "msg"


@pytest.mark.asyncio
async def test_send_output_update_topic_deleted_recovers_via_adapter():
    """Topic deleted errors trigger adapter-owned recovery."""
    client = AdapterClient()
    client.register_adapter(
        "telegram",
        DummyTelegramAdapter(client, error_sequence=[Exception("Topic_deleted")]),
    )

    session = Session(
        session_id="session-789",
        computer_name="test",
        tmux_session_name="tc_session_789",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Tmux Session",
        adapter_metadata=SessionAdapterMetadata(
            telegram=TelegramAdapterMetadata(topic_id=123, output_message_id="msg-1")
        ),
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    mock_db.get_pending_deletions = AsyncMock(return_value=[])
    with patch("teleclaude.core.adapter_client.db", mock_db):
        result = await client.send_output_update(session, "output", 0.0, 0.0)
    assert result == "msg"


@pytest.mark.asyncio
async def test_send_output_update_missing_metadata_creates_ui_channel():
    """Missing UI metadata should trigger UI channel creation before sending output."""
    client = AdapterClient()
    telegram = DummyTelegramAdapter(client)
    telegram.send_output_update = AsyncMock(return_value="msg")  # type: ignore[assignment]
    client.register_adapter("telegram", telegram)

    session = Session(
        session_id="session-999",
        computer_name="test",
        tmux_session_name="tc_session_999",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Tmux Session",
        adapter_metadata=SessionAdapterMetadata(),
    )
    updated_session = Session(
        session_id="session-999",
        computer_name="test",
        tmux_session_name="tc_session_999",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Tmux Session",
        adapter_metadata=SessionAdapterMetadata(
            telegram=TelegramAdapterMetadata(topic_id=999, output_message_id="msg-1")
        ),
    )

    sent_sessions: list[Session] = []

    async def record_send_output_update(sent_session: Session, *_args, **_kwargs):
        sent_sessions.append(sent_session)
        return "msg"

    mock_db = AsyncMock()
    # First get_session: inside ensure_ui_channels lock (returns original session)
    # Second get_session: after ensure_ui_channels lock (returns updated session with topic_id)
    mock_db.get_session = AsyncMock(side_effect=[session, updated_session])
    mock_db.get_pending_deletions = AsyncMock(return_value=[])
    with (
        patch.object(telegram, "ensure_channel", new=AsyncMock(return_value=updated_session)),
        patch("teleclaude.core.adapter_client.db", mock_db),
    ):
        telegram.send_output_update = record_send_output_update  # type: ignore[assignment]
        await client.send_output_update(session, "output", 0.0, 0.0)

    assert len(sent_sessions) == 1
    sent_session = sent_sessions[0]
    telegram_meta = sent_session.get_metadata().get_ui().get_telegram()
    assert telegram_meta
    assert telegram_meta.topic_id == 999


@pytest.mark.asyncio
async def test_send_output_update_non_gemini_not_suppressed_when_experiment_global():
    """Threaded suppression applies only to Gemini sessions."""
    client = AdapterClient()
    telegram = DummyTelegramAdapter(client)
    telegram.send_output_update = AsyncMock(return_value="msg")  # type: ignore[assignment]
    client.register_adapter("telegram", telegram)

    session = Session(
        session_id="session-codex",
        computer_name="test",
        tmux_session_name="tc_session_codex",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Session",
        active_agent="codex",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    mock_db.get_pending_deletions = AsyncMock(return_value=[])
    with patch("teleclaude.core.adapter_client.db", mock_db):
        result = await client.send_output_update(session, "output", 0.0, 0.0)

    assert result == "msg"
    telegram.send_output_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_broadcasts_to_ui_adapters():
    """Paranoid test send_message broadcasts to all UI adapters."""
    client = AdapterClient()

    # Non-UI adapter (Redis) should not receive send_message
    redis_transport = AsyncMock()
    redis_transport.send_message = AsyncMock(return_value=None)

    # UI adapter (Telegram) should receive send_message
    telegram_adapter = DummyTelegramAdapter(client, send_message_return="tg-msg-1")

    client.register_adapter("redis", redis_transport)
    client.register_adapter("telegram", telegram_adapter)

    session = Session(
        session_id="session-789",
        computer_name="test",
        tmux_session_name="tc_session_789",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Session",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        message_id = await client.send_message(session, "hello")

    assert message_id == "tg-msg-1"
    assert telegram_adapter.sent_messages == ["hello"]


@pytest.mark.asyncio
async def test_send_message_ephemeral_tracks_for_deletion():
    """Paranoid test ephemeral messages are auto-tracked for deletion."""
    client = AdapterClient()

    telegram_adapter = DummyTelegramAdapter(client, send_message_return="tg-msg-2")
    client.register_adapter("telegram", telegram_adapter)

    session = Session(
        session_id="session-790",
        computer_name="test",
        tmux_session_name="tc_session_790",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Session",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        # Default ephemeral=True should track for deletion
        await client.send_message(session, "hello")

    assert mock_db.add_pending_deletion.await_count == 1
    _, kwargs = mock_db.add_pending_deletion.call_args
    assert kwargs == {"deletion_type": "feedback"}
    assert mock_db.add_pending_deletion.call_args.args == ("session-790", "tg-msg-2")


@pytest.mark.asyncio
async def test_send_message_persistent_not_tracked():
    """Paranoid test persistent messages are NOT tracked for deletion."""
    client = AdapterClient()

    telegram_adapter = DummyTelegramAdapter(client, send_message_return="tg-msg-3")
    client.register_adapter("telegram", telegram_adapter)

    session = Session(
        session_id="session-791",
        computer_name="test",
        tmux_session_name="tc_session_791",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Session",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        # ephemeral=False should NOT track for deletion
        await client.send_message(session, "hello", ephemeral=False)

    assert mock_db.add_pending_deletion.await_count == 0


@pytest.mark.asyncio
async def test_send_message_notice_broadcasts_when_missing_origin():
    """Notices with no origin broadcast to all UI adapters."""
    client = AdapterClient()

    telegram_adapter = DummyTelegramAdapter(client, send_message_return="tg-feedback")
    slack_adapter = DummyTelegramAdapter(client, send_message_return="slack-feedback")
    client.register_adapter("telegram", telegram_adapter)
    client.register_adapter("slack", slack_adapter)

    session = Session(
        session_id="session-800",
        computer_name="test",
        tmux_session_name="tc_session_800",
        last_input_origin=None,
        title="Test Session",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        result = await client.send_message(session, "hello", cleanup_trigger=CleanupTrigger.NEXT_NOTICE)

    # Broadcasts to all UI adapters; first successful result returned
    assert result is not None


@pytest.mark.asyncio
async def test_send_message_notice_fans_out_to_all_ui_adapters():
    """Notices fan out to all UI adapters (unconditional fan-out)."""
    client = AdapterClient()

    telegram_adapter = DummyTelegramAdapter(client, send_message_return="tg-feedback")
    slack_adapter = DummyTelegramAdapter(client, send_message_return="slack-feedback")
    client.register_adapter("telegram", telegram_adapter)
    client.register_adapter("slack", slack_adapter)

    session = Session(
        session_id="session-800",
        computer_name="test",
        tmux_session_name="tc_session_800",
        last_input_origin="slack",
        title="Test Session",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        message_id = await client.send_message(session, "hello", cleanup_trigger=CleanupTrigger.NEXT_NOTICE)

    assert message_id == "slack-feedback"
    assert telegram_adapter.sent_messages == ["hello"]  # All adapters receive
    assert slack_adapter.sent_messages == ["hello"]


@pytest.mark.asyncio
async def test_send_message_notice_api_origin_broadcasts():
    """Notices with API origin broadcast to all UI adapters."""
    client = AdapterClient()

    telegram_adapter = DummyTelegramAdapter(client, send_message_return="tg-feedback")
    client.register_adapter("telegram", telegram_adapter)

    session = Session(
        session_id="session-802",
        computer_name="test",
        tmux_session_name="tc_session_802",
        last_input_origin=InputOrigin.API.value,
        title="Test Session",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        result = await client.send_message(session, "hello", cleanup_trigger=CleanupTrigger.NEXT_NOTICE)

    assert result == "tg-feedback"


@pytest.mark.asyncio
async def test_send_message_notice_skipped_for_ai_to_ai():
    """Notices are skipped for AI-to-AI sessions."""
    client = AdapterClient()

    telegram_adapter = DummyTelegramAdapter(client, send_message_return="tg-feedback")
    client.register_adapter("telegram", telegram_adapter)

    session = Session(
        session_id="session-801",
        computer_name="test",
        tmux_session_name="tc_session_801",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Session",
        initiator_session_id="initiator-123",
    )

    with patch("teleclaude.core.adapter_client.db", new=AsyncMock()):
        message_id = await client.send_message(session, "hello", cleanup_trigger=CleanupTrigger.NEXT_NOTICE)

    assert message_id is None
    assert telegram_adapter.sent_messages == []


@pytest.mark.asyncio
async def test_delete_channel_always_broadcasts():
    """delete_channel should hit all UI adapters regardless of delivery scope."""
    client = AdapterClient()

    telegram_adapter = DummyTelegramAdapter(client, send_message_return="tg-msg")
    slack_adapter = DummyTelegramAdapter(client, send_message_return="slack-msg")

    client.register_adapter("telegram", telegram_adapter)
    client.register_adapter("slack", slack_adapter)

    session = Session(
        session_id="session-900",
        computer_name="test",
        tmux_session_name="tc_session_900",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Session",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        ok = await client.delete_channel(session)

    assert ok is True
    assert telegram_adapter.deleted_channels == [session.session_id]
    assert slack_adapter.deleted_channels == [session.session_id]


@pytest.mark.asyncio
async def test_send_threaded_output_routes_through_route_to_ui():
    """send_threaded_output should route via _route_to_ui with broadcast=True."""
    client = AdapterClient()
    telegram = DummyTelegramAdapter(client)
    telegram.send_threaded_output = AsyncMock(return_value="threaded-msg-1")  # type: ignore[assignment]
    client.register_adapter("telegram", telegram)

    session = Session(
        session_id="session-threaded",
        computer_name="test",
        tmux_session_name="tc_threaded",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Session",
        active_agent="gemini",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        result = await client.send_threaded_output(session, "Output text", multi_message=True)

    assert result == "threaded-msg-1"
    telegram.send_threaded_output.assert_awaited_once_with(session, "Output text", multi_message=True)


@pytest.mark.asyncio
async def test_send_threaded_output_broadcasts_to_observers():
    """send_threaded_output broadcasts to observer adapters for cross-platform mirroring."""
    client = AdapterClient()

    telegram = DummyTelegramAdapter(client)
    telegram.send_threaded_output = AsyncMock(return_value="tg-threaded")  # type: ignore[assignment]

    slack = DummyTelegramAdapter(client)
    slack.send_threaded_output = AsyncMock(return_value="slack-threaded")  # type: ignore[assignment]

    client.register_adapter("telegram", telegram)
    client.register_adapter("slack", slack)

    session = Session(
        session_id="session-threaded-broadcast",
        computer_name="test",
        tmux_session_name="tc_threaded_bc",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Session",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        result = await client.send_threaded_output(session, "Output text")

    assert result == "tg-threaded"
    telegram.send_threaded_output.assert_awaited_once()
    slack.send_threaded_output.assert_awaited_once()


@pytest.mark.asyncio
async def test_broadcast_user_input_sends_to_observers_not_origin():
    """broadcast_user_input should send formatted text to non-origin UI adapters."""
    client = AdapterClient()

    telegram = DummyTelegramAdapter(client, send_message_return="tg-broadcast")
    slack = DummyTelegramAdapter(client, send_message_return="slack-broadcast")
    client.register_adapter("telegram", telegram)
    client.register_adapter("slack", slack)

    session = Session(
        session_id="session-broadcast",
        computer_name="test",
        tmux_session_name="tc_broadcast",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Session",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        await client.broadcast_user_input(session, "Hello from user", "telegram")

    # Origin (telegram) should NOT receive the broadcast
    assert telegram.sent_messages == []
    # Observer (slack) should receive formatted user input
    assert len(slack.sent_messages) == 1
    assert "Hello from user" in slack.sent_messages[0]


@pytest.mark.asyncio
async def test_broadcast_user_input_includes_origin_attribution():
    """broadcast_user_input formats with origin + computer name."""
    client = AdapterClient()

    slack = DummyTelegramAdapter(client, send_message_return="slack-msg")
    client.register_adapter("slack", slack)

    session = Session(
        session_id="session-attribution",
        computer_name="test",
        tmux_session_name="tc_attribution",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Session",
    )

    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(return_value=session)
    with patch("teleclaude.core.adapter_client.db", mock_db):
        await client.broadcast_user_input(session, "test input", "api")

    assert len(slack.sent_messages) == 1
    msg = slack.sent_messages[0]
    # "api" origin should display as "TUI"
    assert "TUI" in msg
    assert "test input" in msg
