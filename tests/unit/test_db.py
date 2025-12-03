"""Unit tests for db.py."""

import os
import tempfile

import pytest

from teleclaude.core.db import Db


@pytest.fixture
async def test_db():
    """Create temporary test database."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    test_db_instance = Db(db_path)
    await test_db_instance.initialize()

    yield test_db_instance

    await test_db_instance.close()
    try:
        os.unlink(db_path)
    except:
        pass


class TestCreateSession:
    """Tests for create_session method."""

    @pytest.mark.asyncio
    async def test_create_session_minimal(self, test_db):
        """Test business logic: UUID generation, timestamp, and default title."""
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test-session",
            origin_adapter="telegram",
            title=None,  # Test default title generation
        )

        # Test OUR business logic, not SQLite
        assert session.session_id is not None
        assert len(session.session_id) == 36  # Valid UUID format
        assert session.title == "[TestPC] New session"  # Default title logic
        assert session.created_at is not None
        assert session.last_activity is not None

    @pytest.mark.asyncio
    async def test_create_session_with_all_fields(self, test_db):
        """Test creating session with all parameters."""
        metadata = {"topic_id": 123, "user_id": 456}

        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="full-session",
            origin_adapter="telegram",
            title="Custom Title",
            adapter_metadata=metadata,
            terminal_size="120x40",
            working_directory="/home/user",
        )

        assert session.title == "Custom Title"
        assert session.adapter_metadata == metadata
        assert session.terminal_size == "120x40"
        assert session.working_directory == "/home/user"


class TestGetSession:
    """Tests for get_session method."""

    @pytest.mark.asyncio
    async def test_get_existing_session(self, test_db):
        """Test retrieving existing session."""
        created = await test_db.create_session(
            computer_name="TestPC", tmux_session_name="test-session", origin_adapter="telegram", title="Test Session"
        )

        retrieved = await test_db.get_session(created.session_id)

        assert retrieved is not None
        assert retrieved.session_id == created.session_id
        assert retrieved.computer_name == created.computer_name

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, test_db):
        """Test retrieving non-existent session returns None."""
        result = await test_db.get_session("nonexistent-id-12345")

        assert result is None


class TestListSessions:
    """Tests for list_sessions method."""

    @pytest.mark.asyncio
    async def test_list_all_sessions(self, test_db):
        """Test listing all sessions."""
        await test_db.create_session("PC1", "session-1", "telegram", "Test Session")
        await test_db.create_session("PC2", "session-2", "rest", "Test Session")
        await test_db.create_session("PC1", "session-3", "telegram", "Test Session")

        sessions = await test_db.list_sessions()

        assert len(sessions) == 3

    @pytest.mark.asyncio
    async def test_list_sessions_filter_by_computer(self, test_db):
        """Test filtering sessions by computer name."""
        await test_db.create_session("PC1", "session-1", "telegram", "Test Session")
        await test_db.create_session("PC2", "session-2", "telegram", "Test Session")
        await test_db.create_session("PC1", "session-3", "telegram", "Test Session")

        sessions = await test_db.list_sessions(computer_name="PC1")

        assert len(sessions) == 2
        assert all(s.computer_name == "PC1" for s in sessions)

    @pytest.mark.asyncio
    async def test_list_sessions_filter_by_status(self, test_db):
        """Test filtering sessions by status."""
        s1 = await test_db.create_session("PC1", "session-1", "telegram", "Test Session")
        s2 = await test_db.create_session("PC1", "session-2", "telegram", "Test Session")

        # Update one to closed
        await test_db.update_session(s2.session_id, closed=True)

        sessions = await test_db.list_sessions(closed=False)

        assert len(sessions) == 1
        assert sessions[0].session_id == s1.session_id

    @pytest.mark.asyncio
    async def test_list_sessions_filter_by_adapter_type(self, test_db):
        """Test filtering sessions by adapter type."""
        await test_db.create_session("PC1", "session-1", "telegram", "Test Session")
        await test_db.create_session("PC1", "session-2", "rest", "Test Session")
        await test_db.create_session("PC1", "session-3", "telegram", "Test Session")

        sessions = await test_db.list_sessions(origin_adapter="telegram")

        assert len(sessions) == 2
        assert all(s.origin_adapter == "telegram" for s in sessions)

    @pytest.mark.asyncio
    async def test_list_sessions_multiple_filters(self, test_db):
        """Test filtering sessions with multiple criteria."""
        await test_db.create_session("PC1", "session-1", "telegram", "Test Session")
        await test_db.create_session("PC2", "session-2", "telegram", "Test Session")
        s3 = await test_db.create_session("PC1", "session-3", "rest", "Test Session")

        sessions = await test_db.list_sessions(computer_name="PC1", origin_adapter="rest")

        assert len(sessions) == 1
        assert sessions[0].session_id == s3.session_id

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, test_db):
        """Test listing sessions when none exist."""
        sessions = await test_db.list_sessions()

        assert len(sessions) == 0


class TestUpdateSession:
    """Tests for update_session method."""

    @pytest.mark.asyncio
    async def test_update_title(self, test_db):
        """Test updating session title."""
        session = await test_db.create_session("PC1", "session-1", "telegram", "Test Session")

        await test_db.update_session(session.session_id, title="New Title")

        updated = await test_db.get_session(session.session_id)
        assert updated.title == "New Title"

    @pytest.mark.asyncio
    async def test_update_status(self, test_db):
        """Test updating session closed status."""
        session = await test_db.create_session("PC1", "session-1", "telegram", "Test Session")

        await test_db.update_session(session.session_id, closed=True)

        updated = await test_db.get_session(session.session_id)
        assert updated.closed is True

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self, test_db):
        """Test updating multiple fields at once."""
        session = await test_db.create_session("PC1", "session-1", "telegram", "Test Session")

        await test_db.update_session(session.session_id, title="Updated Title", closed=True, terminal_size="100x30")

        updated = await test_db.get_session(session.session_id)
        assert updated.title == "Updated Title"
        assert updated.closed is True
        assert updated.terminal_size == "100x30"

    @pytest.mark.asyncio
    async def test_update_no_fields(self, test_db):
        """Test update with no fields does nothing."""
        session = await test_db.create_session("PC1", "session-1", "telegram", "Test Session")

        # Should not raise error
        await test_db.update_session(session.session_id)

        # Session should be unchanged
        updated = await test_db.get_session(session.session_id)
        assert updated.title == session.title

    @pytest.mark.asyncio
    async def test_update_adapter_metadata(self, test_db):
        """Test updating adapter_metadata."""
        from teleclaude.core.models import (
            SessionAdapterMetadata,
            TelegramAdapterMetadata,
        )

        session = await test_db.create_session("PC1", "session-1", "telegram", "Test Session")

        new_metadata = SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=456))
        await test_db.update_session(session.session_id, adapter_metadata=new_metadata)

        updated = await test_db.get_session(session.session_id)
        assert updated.adapter_metadata.telegram is not None
        assert updated.adapter_metadata.telegram.topic_id == 456


class TestUpdateLastActivity:
    """Tests for update_last_activity method."""

    @pytest.mark.asyncio
    async def test_update_last_activity(self, test_db):
        """Test updating last activity timestamp."""
        session = await test_db.create_session("PC1", "session-1", "telegram", "Test Session")
        original_activity = session.last_activity

        # Wait a tiny bit to ensure timestamp changes
        import asyncio

        await asyncio.sleep(0.01)

        await test_db.update_last_activity(session.session_id)

        updated = await test_db.get_session(session.session_id)
        # Should have updated timestamp (comparing as strings is fine)
        assert updated.last_activity != original_activity


class TestDeleteSession:
    """Tests for delete_session method."""

    @pytest.mark.asyncio
    async def test_delete_existing_session(self, test_db):
        """Test deleting existing session."""
        session = await test_db.create_session("PC1", "session-1", "telegram", "Test Session")

        await test_db.delete_session(session.session_id)

        # Should not be retrievable
        result = await test_db.get_session(session.session_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_session(self, test_db):
        """Test deleting non-existent session doesn't error."""
        # Should not raise error
        await test_db.delete_session("nonexistent-id-12345")


class TestCountSessions:
    """Tests for count_sessions method."""

    @pytest.mark.asyncio
    async def test_count_all_sessions(self, test_db):
        """Test counting all sessions."""
        await test_db.create_session("PC1", "session-1", "telegram", "Test Session")
        await test_db.create_session("PC2", "session-2", "telegram", "Test Session")
        await test_db.create_session("PC1", "session-3", "telegram", "Test Session")

        count = await test_db.count_sessions()

        assert count == 3

    @pytest.mark.asyncio
    async def test_count_sessions_by_computer(self, test_db):
        """Test counting sessions by computer name."""
        await test_db.create_session("PC1", "session-1", "telegram", "Test Session")
        await test_db.create_session("PC2", "session-2", "telegram", "Test Session")
        await test_db.create_session("PC1", "session-3", "telegram", "Test Session")

        count = await test_db.count_sessions(computer_name="PC1")

        assert count == 2

    @pytest.mark.asyncio
    async def test_count_sessions_by_status(self, test_db):
        """Test counting sessions by closed status."""
        s1 = await test_db.create_session("PC1", "session-1", "telegram", "Test Session")
        s2 = await test_db.create_session("PC1", "session-2", "telegram", "Test Session")
        await test_db.update_session(s2.session_id, closed=True)

        count = await test_db.count_sessions(closed=False)

        assert count == 1

    @pytest.mark.asyncio
    async def test_count_sessions_empty(self, test_db):
        """Test counting sessions when none exist."""
        count = await test_db.count_sessions()

        assert count == 0


class TestGetSessionsByAdapterMetadata:
    """Tests for get_sessions_by_adapter_metadata method."""

    @pytest.mark.asyncio
    async def test_get_by_metadata(self, test_db):
        """Test retrieving sessions by adapter metadata."""
        from teleclaude.core.models import (
            SessionAdapterMetadata,
            TelegramAdapterMetadata,
        )

        s1 = await test_db.create_session(
            "PC1",
            "session-1",
            "telegram",
            "Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        )
        s2 = await test_db.create_session(
            "PC1",
            "session-2",
            "telegram",
            "Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=456)),
        )

        sessions = await test_db.get_sessions_by_adapter_metadata("telegram", "topic_id", 123)

        assert len(sessions) == 1
        assert sessions[0].session_id == s1.session_id

    @pytest.mark.asyncio
    async def test_get_by_metadata_no_match(self, test_db):
        """Test retrieving sessions with no metadata match."""
        from teleclaude.core.models import (
            SessionAdapterMetadata,
            TelegramAdapterMetadata,
        )

        await test_db.create_session(
            "PC1",
            "session-1",
            "telegram",
            "Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        )

        sessions = await test_db.get_sessions_by_adapter_metadata("telegram", "topic_id", 999)

        assert len(sessions) == 0

    @pytest.mark.asyncio
    async def test_get_by_metadata_finds_all_with_metadata(self, test_db):
        """Test retrieving sessions finds ALL sessions with the metadata, regardless of origin_adapter.

        This is crucial for observer adapters: when Telegram is an observer for a Redis-initiated
        session, we need to find the session by telegram.topic_id even though origin_adapter='redis'.
        """
        from teleclaude.core.models import (
            SessionAdapterMetadata,
            TelegramAdapterMetadata,
        )

        # Create session with telegram as origin
        await test_db.create_session(
            "PC1",
            "session-1",
            "telegram",
            "Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        )
        # Create session with different origin but SAME telegram metadata (observer pattern)
        await test_db.create_session(
            "PC1",
            "session-2",
            "redis",
            "Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        )

        sessions = await test_db.get_sessions_by_adapter_metadata("telegram", "topic_id", 123)

        # Should find BOTH sessions - origin_adapter doesn't matter, only metadata presence
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_get_by_metadata_excludes_sessions_without_metadata(self, test_db):
        """Test that sessions without the specified adapter metadata are NOT returned."""
        from teleclaude.core.models import (
            RedisAdapterMetadata,
            SessionAdapterMetadata,
            TelegramAdapterMetadata,
        )

        # Create session WITH telegram metadata
        await test_db.create_session(
            "PC1",
            "session-1",
            "telegram",
            "Has Telegram",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        )
        # Create session WITHOUT telegram metadata (only redis)
        await test_db.create_session(
            "PC1",
            "session-2",
            "redis",
            "No Telegram",
            adapter_metadata=SessionAdapterMetadata(redis=RedisAdapterMetadata(channel_id="test")),
        )

        sessions = await test_db.get_sessions_by_adapter_metadata("telegram", "topic_id", 123)

        # Should only find the session that HAS telegram metadata
        assert len(sessions) == 1
        assert sessions[0].title == "Has Telegram"


class TestDbAdapterClientIntegration:
    """Tests for DB integration with AdapterClient."""

    @pytest.mark.asyncio
    async def test_update_session_without_client_does_not_crash(self, test_db):
        """Test that update_session works without client wired."""
        # Create session
        session = await test_db.create_session(
            computer_name="TestPC", tmux_session_name="test-session", origin_adapter="telegram", title="Test Session"
        )

        # Update without wiring client (should not crash)
        await test_db.update_session(session.session_id, closed=True)

        # Verify session updated
        updated = await test_db.get_session(session.session_id)
        assert updated.closed is True


class TestNotificationFlag:
    """Tests for notification_sent flag helpers."""

    @pytest.mark.asyncio
    async def test_set_notification_flag(self, test_db):
        """Test setting notification_sent flag."""
        # Create session
        session = await test_db.create_session(
            computer_name="TestPC", tmux_session_name="test-session", origin_adapter="telegram", title="Test Session"
        )

        # Set flag to True
        await test_db.set_notification_flag(session.session_id, True)

        # Verify flag is set
        flag_value = await test_db.get_notification_flag(session.session_id)
        assert flag_value is True

    @pytest.mark.asyncio
    async def test_clear_notification_flag(self, test_db):
        """Test clearing notification_sent flag."""
        # Create session and set flag
        session = await test_db.create_session(
            computer_name="TestPC", tmux_session_name="test-session", origin_adapter="telegram", title="Test Session"
        )
        await test_db.set_notification_flag(session.session_id, True)

        # Clear flag
        await test_db.clear_notification_flag(session.session_id)

        # Verify flag is cleared
        flag_value = await test_db.get_notification_flag(session.session_id)
        assert flag_value is False

    @pytest.mark.asyncio
    async def test_get_notification_flag_default(self, test_db):
        """Test get_notification_flag returns False for new session."""
        # Create session (no flag set)
        session = await test_db.create_session(
            computer_name="TestPC", tmux_session_name="test-session", origin_adapter="telegram", title="Test Session"
        )

        # Verify flag defaults to False
        flag_value = await test_db.get_notification_flag(session.session_id)
        assert flag_value is False

    @pytest.mark.asyncio
    async def test_notification_flag_persists_across_updates(self, test_db):
        """Test notification_sent flag persists when other UX state fields change."""
        # Create session and set flag
        session = await test_db.create_session(
            computer_name="TestPC", tmux_session_name="test-session", origin_adapter="telegram", title="Test Session"
        )
        await test_db.set_notification_flag(session.session_id, True)

        # Update other UX state fields
        await test_db.update_ux_state(session.session_id, output_message_id="msg123", polling_active=True)

        # Verify notification flag still set
        flag_value = await test_db.get_notification_flag(session.session_id)
        assert flag_value is True

    @pytest.mark.asyncio
    async def test_notification_flag_toggle(self, test_db):
        """Test toggling notification_sent flag multiple times."""
        # Create session
        session = await test_db.create_session(
            computer_name="TestPC", tmux_session_name="test-session", origin_adapter="telegram", title="Test Session"
        )

        # Toggle: False -> True -> False -> True
        assert await test_db.get_notification_flag(session.session_id) is False

        await test_db.set_notification_flag(session.session_id, True)
        assert await test_db.get_notification_flag(session.session_id) is True

        await test_db.set_notification_flag(session.session_id, False)
        assert await test_db.get_notification_flag(session.session_id) is False

        await test_db.set_notification_flag(session.session_id, True)
        assert await test_db.get_notification_flag(session.session_id) is True
