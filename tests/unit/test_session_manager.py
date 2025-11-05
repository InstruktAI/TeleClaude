"""Unit tests for session_manager.py."""

import pytest
import tempfile
import os
from datetime import datetime
from teleclaude.core.session_manager import SessionManager
from teleclaude.core.models import Session


@pytest.fixture
async def session_manager():
    """Create temporary session manager."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    manager = SessionManager(db_path)
    await manager.initialize()

    yield manager

    await manager.close()
    try:
        os.unlink(db_path)
    except:
        pass


class TestCreateSession:
    """Tests for create_session method."""

    @pytest.mark.asyncio
    async def test_create_session_minimal(self, session_manager):
        """Test creating session with minimal parameters."""
        session = await session_manager.create_session(
            computer_name="TestPC",
            tmux_session_name="test-session",
            adapter_type="telegram"
        )

        assert session.session_id is not None
        assert session.computer_name == "TestPC"
        assert session.tmux_session_name == "test-session"
        assert session.adapter_type == "telegram"
        assert session.closed is False
        assert session.command_count == 0
        assert session.title == "[TestPC] New session"

    @pytest.mark.asyncio
    async def test_create_session_with_all_fields(self, session_manager):
        """Test creating session with all parameters."""
        metadata = {"topic_id": 123, "user_id": 456}

        session = await session_manager.create_session(
            computer_name="TestPC",
            tmux_session_name="full-session",
            adapter_type="telegram",
            title="Custom Title",
            adapter_metadata=metadata,
            terminal_size="120x40",
            working_directory="/home/user"
        )

        assert session.title == "Custom Title"
        assert session.adapter_metadata == metadata
        assert session.terminal_size == "120x40"
        assert session.working_directory == "/home/user"


class TestGetSession:
    """Tests for get_session method."""

    @pytest.mark.asyncio
    async def test_get_existing_session(self, session_manager):
        """Test retrieving existing session."""
        created = await session_manager.create_session(
            computer_name="TestPC",
            tmux_session_name="test-session",
            adapter_type="telegram"
        )

        retrieved = await session_manager.get_session(created.session_id)

        assert retrieved is not None
        assert retrieved.session_id == created.session_id
        assert retrieved.computer_name == created.computer_name

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, session_manager):
        """Test retrieving non-existent session returns None."""
        result = await session_manager.get_session("nonexistent-id-12345")

        assert result is None


class TestListSessions:
    """Tests for list_sessions method."""

    @pytest.mark.asyncio
    async def test_list_all_sessions(self, session_manager):
        """Test listing all sessions."""
        await session_manager.create_session("PC1", "session-1", "telegram")
        await session_manager.create_session("PC2", "session-2", "rest")
        await session_manager.create_session("PC1", "session-3", "telegram")

        sessions = await session_manager.list_sessions()

        assert len(sessions) == 3

    @pytest.mark.asyncio
    async def test_list_sessions_filter_by_computer(self, session_manager):
        """Test filtering sessions by computer name."""
        await session_manager.create_session("PC1", "session-1", "telegram")
        await session_manager.create_session("PC2", "session-2", "telegram")
        await session_manager.create_session("PC1", "session-3", "telegram")

        sessions = await session_manager.list_sessions(computer_name="PC1")

        assert len(sessions) == 2
        assert all(s.computer_name == "PC1" for s in sessions)

    @pytest.mark.asyncio
    async def test_list_sessions_filter_by_status(self, session_manager):
        """Test filtering sessions by status."""
        s1 = await session_manager.create_session("PC1", "session-1", "telegram")
        s2 = await session_manager.create_session("PC1", "session-2", "telegram")

        # Update one to closed
        await session_manager.update_session(s2.session_id, closed=True)

        sessions = await session_manager.list_sessions(closed=False)

        assert len(sessions) == 1
        assert sessions[0].session_id == s1.session_id

    @pytest.mark.asyncio
    async def test_list_sessions_filter_by_adapter_type(self, session_manager):
        """Test filtering sessions by adapter type."""
        await session_manager.create_session("PC1", "session-1", "telegram")
        await session_manager.create_session("PC1", "session-2", "rest")
        await session_manager.create_session("PC1", "session-3", "telegram")

        sessions = await session_manager.list_sessions(adapter_type="telegram")

        assert len(sessions) == 2
        assert all(s.adapter_type == "telegram" for s in sessions)

    @pytest.mark.asyncio
    async def test_list_sessions_multiple_filters(self, session_manager):
        """Test filtering sessions with multiple criteria."""
        await session_manager.create_session("PC1", "session-1", "telegram")
        await session_manager.create_session("PC2", "session-2", "telegram")
        s3 = await session_manager.create_session("PC1", "session-3", "rest")

        sessions = await session_manager.list_sessions(
            computer_name="PC1",
            adapter_type="rest"
        )

        assert len(sessions) == 1
        assert sessions[0].session_id == s3.session_id

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, session_manager):
        """Test listing sessions when none exist."""
        sessions = await session_manager.list_sessions()

        assert len(sessions) == 0


class TestUpdateSession:
    """Tests for update_session method."""

    @pytest.mark.asyncio
    async def test_update_title(self, session_manager):
        """Test updating session title."""
        session = await session_manager.create_session("PC1", "session-1", "telegram")

        await session_manager.update_session(session.session_id, title="New Title")

        updated = await session_manager.get_session(session.session_id)
        assert updated.title == "New Title"

    @pytest.mark.asyncio
    async def test_update_status(self, session_manager):
        """Test updating session closed status."""
        session = await session_manager.create_session("PC1", "session-1", "telegram")

        await session_manager.update_session(session.session_id, closed=True)

        updated = await session_manager.get_session(session.session_id)
        assert updated.closed is True

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self, session_manager):
        """Test updating multiple fields at once."""
        session = await session_manager.create_session("PC1", "session-1", "telegram")

        await session_manager.update_session(
            session.session_id,
            title="Updated Title",
            closed=True,
            terminal_size="100x30"
        )

        updated = await session_manager.get_session(session.session_id)
        assert updated.title == "Updated Title"
        assert updated.closed is True
        assert updated.terminal_size == "100x30"

    @pytest.mark.asyncio
    async def test_update_no_fields(self, session_manager):
        """Test update with no fields does nothing."""
        session = await session_manager.create_session("PC1", "session-1", "telegram")

        # Should not raise error
        await session_manager.update_session(session.session_id)

        # Session should be unchanged
        updated = await session_manager.get_session(session.session_id)
        assert updated.title == session.title

    @pytest.mark.asyncio
    async def test_update_adapter_metadata(self, session_manager):
        """Test updating adapter_metadata dict."""
        session = await session_manager.create_session(
            "PC1", "session-1", "telegram",
            adapter_metadata={"topic_id": 123}
        )

        new_metadata = {"topic_id": 456, "user_id": 789}
        await session_manager.update_session(
            session.session_id,
            adapter_metadata=new_metadata
        )

        updated = await session_manager.get_session(session.session_id)
        assert updated.adapter_metadata == new_metadata


class TestUpdateLastActivity:
    """Tests for update_last_activity method."""

    @pytest.mark.asyncio
    async def test_update_last_activity(self, session_manager):
        """Test updating last activity timestamp."""
        session = await session_manager.create_session("PC1", "session-1", "telegram")
        original_activity = session.last_activity

        # Wait a tiny bit to ensure timestamp changes
        import asyncio
        await asyncio.sleep(0.01)

        await session_manager.update_last_activity(session.session_id)

        updated = await session_manager.get_session(session.session_id)
        # Should have updated timestamp (comparing as strings is fine)
        assert updated.last_activity != original_activity


class TestDeleteSession:
    """Tests for delete_session method."""

    @pytest.mark.asyncio
    async def test_delete_existing_session(self, session_manager):
        """Test deleting existing session."""
        session = await session_manager.create_session("PC1", "session-1", "telegram")

        await session_manager.delete_session(session.session_id)

        # Should not be retrievable
        result = await session_manager.get_session(session.session_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_session(self, session_manager):
        """Test deleting non-existent session doesn't error."""
        # Should not raise error
        await session_manager.delete_session("nonexistent-id-12345")


class TestCountSessions:
    """Tests for count_sessions method."""

    @pytest.mark.asyncio
    async def test_count_all_sessions(self, session_manager):
        """Test counting all sessions."""
        await session_manager.create_session("PC1", "session-1", "telegram")
        await session_manager.create_session("PC2", "session-2", "telegram")
        await session_manager.create_session("PC1", "session-3", "telegram")

        count = await session_manager.count_sessions()

        assert count == 3

    @pytest.mark.asyncio
    async def test_count_sessions_by_computer(self, session_manager):
        """Test counting sessions by computer name."""
        await session_manager.create_session("PC1", "session-1", "telegram")
        await session_manager.create_session("PC2", "session-2", "telegram")
        await session_manager.create_session("PC1", "session-3", "telegram")

        count = await session_manager.count_sessions(computer_name="PC1")

        assert count == 2

    @pytest.mark.asyncio
    async def test_count_sessions_by_status(self, session_manager):
        """Test counting sessions by closed status."""
        s1 = await session_manager.create_session("PC1", "session-1", "telegram")
        s2 = await session_manager.create_session("PC1", "session-2", "telegram")
        await session_manager.update_session(s2.session_id, closed=True)

        count = await session_manager.count_sessions(closed=False)

        assert count == 1

    @pytest.mark.asyncio
    async def test_count_sessions_empty(self, session_manager):
        """Test counting sessions when none exist."""
        count = await session_manager.count_sessions()

        assert count == 0


class TestGetSessionsByAdapterMetadata:
    """Tests for get_sessions_by_adapter_metadata method."""

    @pytest.mark.asyncio
    async def test_get_by_metadata(self, session_manager):
        """Test retrieving sessions by adapter metadata."""
        s1 = await session_manager.create_session(
            "PC1", "session-1", "telegram",
            adapter_metadata={"topic_id": 123}
        )
        s2 = await session_manager.create_session(
            "PC1", "session-2", "telegram",
            adapter_metadata={"topic_id": 456}
        )

        sessions = await session_manager.get_sessions_by_adapter_metadata(
            "telegram", "topic_id", 123
        )

        assert len(sessions) == 1
        assert sessions[0].session_id == s1.session_id

    @pytest.mark.asyncio
    async def test_get_by_metadata_no_match(self, session_manager):
        """Test retrieving sessions with no metadata match."""
        await session_manager.create_session(
            "PC1", "session-1", "telegram",
            adapter_metadata={"topic_id": 123}
        )

        sessions = await session_manager.get_sessions_by_adapter_metadata(
            "telegram", "topic_id", 999
        )

        assert len(sessions) == 0

    @pytest.mark.asyncio
    async def test_get_by_metadata_different_adapter(self, session_manager):
        """Test retrieving sessions filters by adapter type."""
        await session_manager.create_session(
            "PC1", "session-1", "telegram",
            adapter_metadata={"topic_id": 123}
        )
        await session_manager.create_session(
            "PC1", "session-2", "rest",
            adapter_metadata={"topic_id": 123}
        )

        sessions = await session_manager.get_sessions_by_adapter_metadata(
            "telegram", "topic_id", 123
        )

        assert len(sessions) == 1
        assert sessions[0].adapter_type == "telegram"
