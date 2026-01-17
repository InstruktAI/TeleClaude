"""Integration test for multi-adapter broadcasting.

Tests UC-M1: Telegram User with Redis Observer
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.db import Db
from teleclaude.core.models import ChannelMetadata, MessageMetadata, Session


class MockTelegramAdapter(UiAdapter):
    """Mock Telegram adapter (UI-enabled origin)."""

    ADAPTER_KEY = "telegram"

    def __init__(self, client: AdapterClient):
        self.client = client
        self.send_message_calls = []
        self.edit_message_calls = []
        self.delete_message_calls = []

    async def send_message(self, session: Session, text: str, *, metadata: MessageMetadata | None = None) -> str:
        self.send_message_calls.append((session, text, metadata))
        return "msg-123"

    async def edit_message(
        self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
    ) -> bool:
        self.edit_message_calls.append((session, message_id, text, metadata))
        return True

    async def delete_message(self, session: Session, message_id: str) -> bool:
        self.delete_message_calls.append((session, message_id))
        return True

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        return "channel-123"

    async def update_channel_title(self, session: Session, title: str) -> bool:
        return True

    async def close_channel(self, session: Session) -> bool:
        return True

    async def reopen_channel(self, session: Session) -> bool:
        return True

    async def delete_channel(self, session: Session) -> bool:
        return True

    async def send_file(
        self, session: Session, file_path: str, *, caption: str | None = None, metadata: MessageMetadata | None = None
    ) -> str:
        return "file-msg-123"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def discover_peers(self):
        return []

    async def poll_output_stream(self, session: Session, timeout: float = 300.0):
        """Not used in these tests."""
        _ = (session, timeout)
        if False:
            yield ""
        return


class MockRedisAdapter(BaseAdapter):
    """Mock Redis adapter (has_ui=False, observer)."""

    has_ui = False  # Pure transport, no UI

    def __init__(self):
        super().__init__()
        self.send_message_calls = []

    async def send_message(self, session: Session, text: str, *, metadata: MessageMetadata | None = None) -> str:
        self.send_message_calls.append((session, text, metadata))
        return "redis-msg-123"

    async def edit_message(
        self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
    ) -> bool:
        return True

    async def delete_message(self, session: Session, message_id: str) -> bool:
        return True

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        return "redis-channel-123"

    async def update_channel_title(self, session: Session, title: str) -> bool:
        return True

    async def close_channel(self, session: Session) -> bool:
        return True

    async def reopen_channel(self, session: Session) -> bool:
        return True

    async def delete_channel(self, session: Session) -> bool:
        return True

    async def send_file(
        self, session: Session, file_path: str, *, caption: str | None = None, metadata: MessageMetadata | None = None
    ) -> str:
        return "redis-file-msg-123"

    async def is_session_observed(self, session_id: str) -> bool:
        return False  # Mock: no observers by default

    async def start(self):
        pass

    async def stop(self):
        pass

    async def discover_peers(self):
        return []

    async def poll_output_stream(self, session: Session, timeout: float = 300.0):
        """Not used in these tests."""
        _ = (session, timeout)
        if False:
            yield ""
        return


@pytest.mark.integration
async def test_origin_adapter_receives_output():
    """Test output sent to origin adapter (CRITICAL).

    Use Case: UC-M1
    Flow:
    1. Create session with origin_adapter="telegram"
    2. Register TelegramAdapter as origin
    3. Send message via adapter_client
    4. Verify send_message() called on TelegramAdapter
    5. Verify message_id returned
    """
    # Setup test database
    db_path = "/tmp/test_origin_adapter.db"
    Path(db_path).unlink(missing_ok=True)

    test_db = Db(db_path)
    await test_db.initialize()

    try:
        with patch("teleclaude.core.db.db", test_db):
            with patch("teleclaude.core.adapter_client.db", test_db):
                # Create session
                session = await test_db.create_session(
                    computer_name="TestPC",
                    tmux_session_name="test-origin",
                    origin_adapter="telegram",
                    title="Origin Test",
                )

                # Create adapter_client with TelegramAdapter as origin
                adapter_client = AdapterClient()
                telegram_adapter = MockTelegramAdapter(adapter_client)
                adapter_client.adapters = {"telegram": telegram_adapter}

                # Send message (should route to origin)
                result = await adapter_client.send_message(session, "Test output")

                # Verify send_message called on TelegramAdapter
                assert len(telegram_adapter.send_message_calls) == 1
                call_session, call_text, call_metadata = telegram_adapter.send_message_calls[0]
                assert call_session.session_id == session.session_id
                assert call_text == "Test output"

                # Verify message_id returned
                assert result == "msg-123"

    finally:
        await test_db.close()
        Path(db_path).unlink(missing_ok=True)


@pytest.mark.integration
async def test_redis_observer_skipped_no_ui():
    """Test RedisTransport (has_ui=False) skipped for broadcasts.

    Use Case: UC-M1
    Flow:
    1. Create session with telegram origin
    2. Register both TelegramAdapter (origin) and RedisTransport (observer)
    3. Send message via adapter_client
    4. Verify output sent to telegram (origin)
    5. Verify Redis send_message() NOT called (has_ui=False)
    """
    # Setup test database
    db_path = "/tmp/test_redis_observer.db"
    Path(db_path).unlink(missing_ok=True)

    test_db = Db(db_path)
    await test_db.initialize()

    try:
        with patch("teleclaude.core.db.db", test_db):
            with patch("teleclaude.core.adapter_client.db", test_db):
                # Create session with telegram origin
                session = await test_db.create_session(
                    computer_name="TestPC",
                    tmux_session_name="test-redis-observer",
                    origin_adapter="telegram",
                    title="Redis Observer Test",
                )

                # Create adapter_client with both adapters
                adapter_client = AdapterClient()
                telegram_adapter = MockTelegramAdapter(adapter_client)
                redis_adapter = MockRedisAdapter()
                adapter_client.adapters = {
                    "telegram": telegram_adapter,
                    "redis": redis_adapter,
                }

                # Send message (origin: telegram, observer: redis)
                await adapter_client.send_message(session, "Test output")

                # Verify telegram (origin) received message
                assert len(telegram_adapter.send_message_calls) == 1

                # Verify redis (observer with has_ui=False) NOT called
                assert len(redis_adapter.send_message_calls) == 0

    finally:
        await test_db.close()
        Path(db_path).unlink(missing_ok=True)


@pytest.mark.integration
async def test_ui_observer_receives_broadcasts():
    """Test UI observer (has_ui=True) receives broadcasts (future Slack/WhatsApp).

    Use Case: UC-M2 (future)
    Flow:
    1. Create session with telegram origin
    2. Register Telegram (origin) and MockSlack (observer with has_ui=True)
    3. Send message via adapter_client
    4. Verify telegram (origin) receives message
    5. Verify slack (observer with has_ui=True) also receives message
    """

    from teleclaude.adapters.ui_adapter import UiAdapter

    class MockSlackAdapter(UiAdapter):
        """Mock Slack adapter (UI-enabled observer)."""

        def __init__(self):
            # Create mock client
            mock_client = MagicMock()
            mock_client.on = MagicMock()
            super().__init__(mock_client)
            self.send_message_calls = []

        async def send_message(self, session: Session, text: str, *, metadata: MessageMetadata | None = None) -> str:
            self.send_message_calls.append((session, text, metadata))
            return "slack-msg-123"

        async def edit_message(
            self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
        ) -> bool:
            return True

        async def delete_message(self, session: Session, message_id: str) -> bool:
            return True

        async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
            return "slack-channel-123"

        async def update_channel_title(self, session: Session, title: str) -> bool:
            return True

        async def close_channel(self, session: Session) -> bool:
            return True

        async def reopen_channel(self, session: Session) -> bool:
            return True

        async def delete_channel(self, session: Session) -> bool:
            return True

        async def send_file(
            self,
            session: Session,
            file_path: str,
            *,
            caption: str | None = None,
            metadata: MessageMetadata | None = None,
        ) -> str:
            return "slack-file-msg-123"

        async def start(self):
            pass

        async def stop(self):
            pass

        async def discover_peers(self):
            return []

        async def poll_output_stream(self, session: Session, timeout: float = 300.0):
            """Not used in these tests."""
            _ = (session, timeout)
            if False:
                yield ""
            return

    # Setup test database
    db_path = "/tmp/test_ui_observer.db"
    Path(db_path).unlink(missing_ok=True)

    test_db = Db(db_path)
    await test_db.initialize()

    try:
        with patch("teleclaude.core.db.db", test_db):
            with patch("teleclaude.core.adapter_client.db", test_db):
                # Create session
                session = await test_db.create_session(
                    computer_name="TestPC",
                    tmux_session_name="test-ui-observer",
                    origin_adapter="telegram",
                    title="UI Observer Test",
                )

                # Create adapter_client
                adapter_client = AdapterClient()
                telegram_adapter = MockTelegramAdapter(adapter_client)
                slack_adapter = MockSlackAdapter()
                adapter_client.adapters = {
                    "telegram": telegram_adapter,
                    "slack": slack_adapter,
                }

                # Send message
                await adapter_client.send_message(session, "Test output")

                # Verify telegram (origin) called
                assert len(telegram_adapter.send_message_calls) == 1

                # Verify slack (observer with has_ui=True) also called (best-effort)
                assert len(slack_adapter.send_message_calls) == 1
                call_session, call_text, call_metadata = slack_adapter.send_message_calls[0]
                assert call_session.session_id == session.session_id
                assert call_text == "Test output"

    finally:
        await test_db.close()
        Path(db_path).unlink(missing_ok=True)


@pytest.mark.integration
async def test_observer_failure_does_not_affect_origin():
    """Test observer failure logged but origin message succeeds.

    Use Case: UC-M1 (error handling)
    Flow:
    1. Create session with telegram origin and slack observer
    2. Make slack send_message() raise exception
    3. Send message via adapter_client
    4. Verify telegram (origin) succeeds
    5. Verify slack exception logged but not raised
    """

    from teleclaude.adapters.ui_adapter import UiAdapter

    class MockSlackAdapterFailing(UiAdapter):
        """Mock Slack adapter that always fails."""

        def __init__(self):
            # Create mock client
            mock_client = MagicMock()
            mock_client.on = MagicMock()
            super().__init__(mock_client)
            self.send_message_calls = []

        async def send_message(self, session: Session, text: str, *, metadata: MessageMetadata | None = None) -> str:
            self.send_message_calls.append((session, text, metadata))
            raise Exception("Slack API error")

        async def edit_message(
            self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
        ) -> bool:
            return True

        async def delete_message(self, session: Session, message_id: str) -> bool:
            return True

        async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
            return "slack-channel-123"

        async def update_channel_title(self, session: Session, title: str) -> bool:
            return True

        async def close_channel(self, session: Session) -> bool:
            return True

        async def reopen_channel(self, session: Session) -> bool:
            return True

        async def delete_channel(self, session: Session) -> bool:
            return True

        async def send_file(
            self,
            session: Session,
            file_path: str,
            *,
            caption: str | None = None,
            metadata: MessageMetadata | None = None,
        ) -> str:
            return "slack-file-msg-123"

        async def start(self):
            pass

        async def stop(self):
            pass

        async def discover_peers(self):
            return []

        async def poll_output_stream(self, session: Session, timeout: float = 300.0):
            """Not used in these tests."""
            _ = (session, timeout)
            if False:
                yield ""
            return

    # Setup test database
    db_path = "/tmp/test_observer_failure.db"
    Path(db_path).unlink(missing_ok=True)

    test_db = Db(db_path)
    await test_db.initialize()

    try:
        with patch("teleclaude.core.db.db", test_db):
            with patch("teleclaude.core.adapter_client.db", test_db):
                # Create session
                session = await test_db.create_session(
                    computer_name="TestPC",
                    tmux_session_name="test-observer-failure",
                    origin_adapter="telegram",
                    title="Observer Failure Test",
                )

                # Create adapter_client
                adapter_client = AdapterClient()
                telegram_adapter = MockTelegramAdapter(adapter_client)
                slack_adapter = MockSlackAdapterFailing()
                adapter_client.adapters = {
                    "telegram": telegram_adapter,
                    "slack": slack_adapter,
                }

                # Send message (should succeed despite slack failure)
                result = await adapter_client.send_message(session, "Test output")

                # Verify telegram (origin) succeeded
                assert len(telegram_adapter.send_message_calls) == 1
                assert result == "msg-123"

                # Verify slack was attempted (logged the call before failing)
                assert len(slack_adapter.send_message_calls) == 1

    finally:
        await test_db.close()
        Path(db_path).unlink(missing_ok=True)


@pytest.mark.integration
async def test_origin_failure_raises_exception():
    """Test origin adapter failure raises exception (CRITICAL).

    Use Case: UC-M1 (error handling)
    Flow:
    1. Create session with telegram origin
    2. Make telegram send_message() raise exception
    3. Attempt to send message via adapter_client
    4. Verify exception raised (origin failures are critical)
    """

    class MockTelegramAdapterFailing(UiAdapter):
        """Mock Telegram adapter that fails."""

        ADAPTER_KEY = "telegram"

        def __init__(self, client: AdapterClient):
            self.client = client

        async def send_message(self, session: Session, text: str, *, metadata: MessageMetadata | None = None) -> str:
            raise Exception("Telegram API error")

        async def edit_message(
            self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
        ) -> bool:
            return True

        async def delete_message(self, session: Session, message_id: str) -> bool:
            return True

        async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
            return "channel-123"

        async def update_channel_title(self, session: Session, title: str) -> bool:
            return True

        async def close_channel(self, session: Session) -> bool:
            return True

        async def reopen_channel(self, session: Session) -> bool:
            return True

        async def delete_channel(self, session: Session) -> bool:
            return True

        async def send_file(
            self,
            session: Session,
            file_path: str,
            *,
            caption: str | None = None,
            metadata: MessageMetadata | None = None,
        ) -> str:
            return "file-msg-123"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def discover_peers(self):
            return []

        async def poll_output_stream(self, session: Session, timeout: float = 300.0):
            """Not used in these tests."""
            _ = (session, timeout)
            if False:
                yield ""
            return

    # Setup test database
    db_path = "/tmp/test_origin_failure.db"
    Path(db_path).unlink(missing_ok=True)

    test_db = Db(db_path)
    await test_db.initialize()

    try:
        with patch("teleclaude.core.db.db", test_db):
            with patch("teleclaude.core.adapter_client.db", test_db):
                # Create session
                session = await test_db.create_session(
                    computer_name="TestPC",
                    tmux_session_name="test-origin-failure",
                    origin_adapter="telegram",
                    title="Origin Failure Test",
                )

                # Create adapter_client
                adapter_client = AdapterClient()
                # Create failing adapter
                telegram_adapter = MockTelegramAdapterFailing(adapter_client)
                adapter_client.adapters = {"telegram": telegram_adapter}

                # Attempt to send message (should raise)
                with pytest.raises(Exception, match="Telegram API error"):
                    await adapter_client.send_message(session, "Test output")

    finally:
        await test_db.close()
        Path(db_path).unlink(missing_ok=True)


@pytest.mark.integration
async def test_discover_peers_respects_redis_enabled_flag():
    """Test discover_peers() respects redis_enabled config flag.

    When Redis is disabled, discover_peers() should return empty list
    without querying adapters - local operations still work.

    Verifies:
    1. redis_enabled=False returns empty list without calling adapters
    2. redis_enabled=True queries adapters and returns peers
    3. Local session creation works regardless of redis_enabled
    """
    from datetime import datetime

    from teleclaude.core.models import PeerInfo

    # Create mock Redis adapter that would return peers if called
    class MockRedisAdapterWithPeers(BaseAdapter):
        """Mock Redis adapter that returns peers."""

        has_ui = False

        def __init__(self):
            super().__init__()
            self.discover_peers_called = False

        async def send_message(self, session: Session, text: str, *, metadata: MessageMetadata | None = None) -> str:
            return "redis-msg-123"

        async def edit_message(
            self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
        ) -> bool:
            return True

        async def delete_message(self, session: Session, message_id: str) -> bool:
            return True

        async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
            return "redis-channel-123"

        async def update_channel_title(self, session: Session, title: str) -> bool:
            return True

        async def close_channel(self, session: Session) -> bool:
            return True

        async def reopen_channel(self, session: Session) -> bool:
            return True

        async def delete_channel(self, session: Session) -> bool:
            return True

        async def send_file(
            self,
            session: Session,
            file_path: str,
            *,
            caption: str | None = None,
            metadata: MessageMetadata | None = None,
        ) -> str:
            return "redis-file-msg-123"

        async def start(self):
            pass

        async def stop(self):
            pass

        async def discover_peers(self):
            """Return mock peers - tracks if called."""
            self.discover_peers_called = True
            return [
                PeerInfo(
                    name="RemotePC",
                    status="online",
                    last_seen=datetime.now(),
                    adapter_type="redis",
                    user="testuser",
                    host="remote.local",
                )
            ]

        async def poll_output_stream(self, session: Session, timeout: float = 300.0):
            _ = (session, timeout)
            if False:
                yield ""
            return

    # Setup test database
    db_path = "/tmp/test_redis_enabled_flag.db"
    Path(db_path).unlink(missing_ok=True)

    test_db = Db(db_path)
    await test_db.initialize()

    try:
        with patch("teleclaude.core.db.db", test_db):
            with patch("teleclaude.core.adapter_client.db", test_db):
                # Create adapter client with mock Redis adapter
                redis_adapter = MockRedisAdapterWithPeers()
                adapter_client = AdapterClient()
                adapter_client.adapters = {"redis": redis_adapter}

                # Test 1: redis_enabled=False - should return empty without calling adapter
                peers = await adapter_client.discover_peers(redis_enabled=False)
                assert peers == [], "Should return empty list when Redis disabled"
                assert not redis_adapter.discover_peers_called, "Should NOT call adapter when Redis disabled"

                # Test 2: redis_enabled=True - should query adapter and return peers
                peers = await adapter_client.discover_peers(redis_enabled=True)
                assert len(peers) == 1, "Should return peers when Redis enabled"
                assert peers[0]["name"] == "RemotePC"
                assert redis_adapter.discover_peers_called, "Should call adapter when Redis enabled"

                # Test 3: Local session creation works regardless (isolation test)
                session = await test_db.create_session(
                    computer_name="LocalPC",
                    tmux_session_name="local-session",
                    origin_adapter="telegram",
                    title="Local Session Test",
                )
                assert session is not None, "Local session creation should work"
                assert session.computer_name == "LocalPC"

    finally:
        await test_db.close()
        Path(db_path).unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
