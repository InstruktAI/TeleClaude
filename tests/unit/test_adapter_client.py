"""Unit tests for AdapterClient peer discovery aggregation."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.models import PeerInfo


class DummyTelegramAdapter(UiAdapter):
    ADAPTER_KEY = "telegram"

    def __init__(
        self,
        adapter_client,
        *,
        error: Exception | None = None,
        error_sequence: list[Exception] | None = None,
        send_feedback_return: str | None = None,
    ) -> None:
        super().__init__(adapter_client)
        self._error = error
        self._error_sequence = list(error_sequence) if error_sequence else []
        if send_feedback_return is not None:
            self.send_feedback = AsyncMock(return_value=send_feedback_return)  # type: ignore[assignment]

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def create_channel(self, _session, _title, _metadata) -> str:
        return "topic"

    async def update_channel_title(self, _session, _title) -> bool:
        return True

    async def close_channel(self, _session) -> bool:
        return True

    async def reopen_channel(self, _session) -> bool:
        return True

    async def delete_channel(self, _session) -> bool:
        return True

    async def send_message(self, _session, _text, _metadata) -> str:
        return "msg"

    async def edit_message(self, _session, _message_id, _text, _metadata) -> bool:
        return True

    async def delete_message(self, _session, _message_id) -> bool:
        return True

    async def send_file(self, _session, _file_path, _metadata, _caption=None) -> str:
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


@pytest.mark.asyncio
async def test_adapter_client_register_adapter():
    """Test adapter registration."""
    from unittest.mock import Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapters
    mock_telegram_adapter = Mock()
    mock_redis_adapter = Mock()

    # Register adapters
    client.register_adapter("telegram", mock_telegram_adapter)
    client.register_adapter("redis", mock_redis_adapter)

    # Verify registration
    assert "telegram" in client.adapters
    assert "redis" in client.adapters
    assert client.adapters["telegram"] == mock_telegram_adapter
    assert client.adapters["redis"] == mock_redis_adapter


@pytest.mark.asyncio
async def test_adapter_client_discover_peers_single_adapter():
    """Test peer discovery with single adapter."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapter
    mock_client = Mock()
    mock_client.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="macbook",
                status="online",
                last_seen=datetime.now(),
                adapter_type="telegram",
            ),
            PeerInfo(
                name="workstation",
                status="online",
                last_seen=datetime.now(),
                adapter_type="telegram",
            ),
        ]
    )

    # Register adapter
    client.register_adapter("telegram", mock_client)

    # Test discovery (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 2
    assert "macbook" in [p["name"] for p in peers]
    assert "workstation" in [p["name"] for p in peers]


@pytest.mark.asyncio
async def test_adapter_client_discover_peers_multiple_adapters():
    """Test peer discovery aggregation from multiple adapters."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapters with different peers
    mock_telegram = Mock()
    mock_telegram.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="macbook",
                status="online",
                last_seen=datetime.now(),
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
                last_seen=datetime.now(),
                adapter_type="redis",
            ),
            PeerInfo(
                name="server",
                status="online",
                last_seen=datetime.now(),
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
    assert "macbook" in [p["name"] for p in peers]
    assert "workstation" in [p["name"] for p in peers]
    assert "server" in [p["name"] for p in peers]


@pytest.mark.asyncio
async def test_adapter_client_deduplication():
    """Test that duplicate peers are deduplicated (first adapter wins)."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapters with overlapping peers
    now = datetime.now()
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
    macbook_peer = next(p for p in peers if p["name"] == "macbook")
    assert macbook_peer["adapter_type"] == "telegram"


@pytest.mark.asyncio
async def test_adapter_client_handles_adapter_errors():
    """Test that errors from one adapter don't break discovery from others."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

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
                last_seen=datetime.now(),
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
    """Test behavior when no peers are discovered."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

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
    """Test behavior when no adapters are registered."""
    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Test discovery with no adapters (explicitly enable Redis for test)
    peers = await client.discover_peers(redis_enabled=True)
    assert len(peers) == 0
    assert peers == []


@pytest.mark.asyncio
async def test_adapter_client_system_stats_passthrough():
    """Test that system_stats are passed through from PeerInfo to dict."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapter with system_stats
    mock_adapter = Mock()
    mock_adapter.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="server",
                status="online",
                last_seen=datetime.now(),
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
    """Test that discover_peers returns empty list when Redis is disabled."""
    from unittest.mock import AsyncMock, Mock

    from teleclaude.core.adapter_client import AdapterClient

    client = AdapterClient()

    # Create mock adapter that would return peers
    mock_adapter = Mock()
    mock_adapter.discover_peers = AsyncMock(
        return_value=[
            PeerInfo(
                name="should-not-appear",
                status="online",
                last_seen=datetime.now(),
                adapter_type="redis",
            )
        ]
    )

    client.register_adapter("redis", mock_adapter)

    # Test with Redis disabled - should return empty list without calling adapter
    peers = await client.discover_peers(redis_enabled=False)
    assert len(peers) == 0
    assert peers == []
    # Adapter should NOT have been called
    mock_adapter.discover_peers.assert_not_called()


@pytest.mark.asyncio
async def test_send_output_update_missing_thread_recreates_topic():
    """Missing Telegram topic should trigger topic recreation."""
    from unittest.mock import AsyncMock, patch

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session, SessionAdapterMetadata, TelegramAdapterMetadata

    client = AdapterClient()
    client.register_adapter("telegram", DummyTelegramAdapter(client, error=Exception("Message thread not found")))

    session = Session(
        session_id="session-123",
        computer_name="test",
        tmux_session_name="tc_session",
        origin_adapter="telegram",
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(
            telegram=TelegramAdapterMetadata(topic_id=123, output_message_id="msg-1")
        ),
    )

    with (
        patch("teleclaude.core.adapter_client.db.get_session", new=AsyncMock(return_value=session)) as get_session,
        patch("teleclaude.core.adapter_client.db.update_session", new=AsyncMock()) as update_session,
        patch.object(client, "create_channel", new=AsyncMock(return_value="999")) as create_channel,
    ):
        await client.send_output_update(session, "output", 0.0, 0.0)

    assert get_session.call_count == 2
    get_session.assert_any_call("session-123")
    create_channel.assert_called_once()
    assert update_session.call_count == 1


@pytest.mark.asyncio
async def test_send_output_update_missing_thread_non_telegram_origin_recreates_topic():
    """Missing Telegram topic should recreate topic even for non-telegram origin."""
    from unittest.mock import AsyncMock, patch

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session, SessionAdapterMetadata, TelegramAdapterMetadata

    client = AdapterClient()
    client.register_adapter("telegram", DummyTelegramAdapter(client, error=Exception("Message thread not found")))

    session = Session(
        session_id="session-456",
        computer_name="test",
        tmux_session_name="tc_session_456",
        origin_adapter="redis",
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(
            telegram=TelegramAdapterMetadata(topic_id=456, output_message_id="msg-2")
        ),
    )

    with (
        patch("teleclaude.core.adapter_client.db.get_session", new=AsyncMock(return_value=session)) as get_session,
        patch("teleclaude.core.adapter_client.db.update_session", new=AsyncMock()) as update_session,
        patch.object(client, "create_channel", new=AsyncMock(return_value="999")) as create_channel,
    ):
        await client.send_output_update(session, "output", 0.0, 0.0)

    assert get_session.call_count == 2
    get_session.assert_any_call("session-456")
    create_channel.assert_called_once()
    assert update_session.call_count == 1


@pytest.mark.asyncio
async def test_send_output_update_missing_thread_terminal_recreates_topic():
    """Terminal-origin sessions should recreate missing Telegram topics."""
    from unittest.mock import AsyncMock, patch

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session, SessionAdapterMetadata, TelegramAdapterMetadata

    client = AdapterClient()
    client.register_adapter(
        "telegram",
        DummyTelegramAdapter(client, error_sequence=[Exception("Topic_deleted")]),
    )

    session = Session(
        session_id="session-789",
        computer_name="test",
        tmux_session_name="tc_session_789",
        origin_adapter="terminal",
        title="Test Terminal Session",
        adapter_metadata=SessionAdapterMetadata(
            telegram=TelegramAdapterMetadata(topic_id=123, output_message_id="msg-1")
        ),
    )

    with patch("teleclaude.core.adapter_client.db.get_session", new=AsyncMock(return_value=session)) as get_session:
        with patch("teleclaude.core.adapter_client.db.update_session", new=AsyncMock()) as update_session:
            with patch.object(client, "create_channel", new=AsyncMock(return_value="999")) as create_channel:
                result = await client.send_output_update(session, "output", 0.0, 0.0)

    assert get_session.call_count == 2
    get_session.assert_any_call("session-789")
    create_channel.assert_called_once()
    assert update_session.call_count == 1
    _, kwargs = update_session.call_args
    updated_meta = kwargs["adapter_metadata"]
    assert updated_meta.telegram.topic_id is None
    assert updated_meta.telegram.output_message_id is None
    assert result == "msg"


@pytest.mark.asyncio
async def test_send_feedback_routes_to_last_input_adapter():
    """Test feedback routes to last_input_adapter when origin is non-UI."""
    from unittest.mock import AsyncMock, patch

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import MessageMetadata, Session
    from teleclaude.core.ux_state import SessionUXState

    client = AdapterClient()

    origin_adapter = AsyncMock()
    origin_adapter.send_feedback = AsyncMock(return_value=None)
    telegram_adapter = DummyTelegramAdapter(client, send_feedback_return="tg-msg-1")

    client.register_adapter("redis", origin_adapter)
    client.register_adapter("telegram", telegram_adapter)

    session = Session(
        session_id="session-789",
        computer_name="test",
        tmux_session_name="tc_session_789",
        origin_adapter="redis",
        title="Test Session",
    )

    with patch(
        "teleclaude.core.adapter_client.db.get_ux_state",
        new=AsyncMock(return_value=SessionUXState(last_input_adapter="telegram")),
    ):
        message_id = await client.send_feedback(session, "hello", MessageMetadata())

    assert message_id == "tg-msg-1"
    origin_adapter.send_feedback.assert_not_called()
    telegram_adapter.send_feedback.assert_called_once()


@pytest.mark.asyncio
async def test_send_feedback_falls_back_to_origin_ui():
    """Test feedback falls back to origin adapter when last_input_adapter isn't UI."""
    from unittest.mock import AsyncMock, patch

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import MessageMetadata, Session
    from teleclaude.core.ux_state import SessionUXState

    client = AdapterClient()

    origin_adapter = DummyTelegramAdapter(client, send_feedback_return="tg-msg-2")
    client.register_adapter("telegram", origin_adapter)

    session = Session(
        session_id="session-790",
        computer_name="test",
        tmux_session_name="tc_session_790",
        origin_adapter="telegram",
        title="Test Session",
    )

    with patch(
        "teleclaude.core.adapter_client.db.get_ux_state",
        new=AsyncMock(return_value=SessionUXState(last_input_adapter="redis")),
    ):
        message_id = await client.send_feedback(session, "hello", MessageMetadata())

    assert message_id == "tg-msg-2"
    origin_adapter.send_feedback.assert_called_once()
