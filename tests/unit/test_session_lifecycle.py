"""Unit tests for session_lifecycle module."""

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import session_lifecycle
from teleclaude.core.models import Session


@pytest.mark.asyncio
class TestMigrateSessionMetadata:
    """Test migrate_session_metadata function."""

    async def test_migrate_old_metadata_to_new_format(self):
        """Test migration of old topic_id to new channel_id format."""
        # Create sessions with old metadata format
        old_session = Session(
            session_id="old-123",
            computer_name="TestMac",
            tmux_session_name="old-tmux",
            adapter_type="telegram",
            title="Old",
            adapter_metadata={"topic_id": 12345, "user_id": 67890},
        )

        session_manager = Mock()
        session_manager.list_sessions = AsyncMock(return_value=[old_session])
        session_manager.update_session = AsyncMock()

        # Execute migration
        await session_lifecycle.migrate_session_metadata(session_manager)

        # Verify update called once
        session_manager.update_session.assert_called_once()

        # Verify the call args (parse JSON to avoid dict ordering issues)
        call_args = session_manager.update_session.call_args
        assert call_args[0][0] == "old-123"
        metadata_json = call_args[1]["adapter_metadata"]
        metadata = json.loads(metadata_json)
        assert metadata == {"channel_id": "12345", "user_id": 67890}

    async def test_skip_already_migrated_sessions(self):
        """Test that sessions already migrated are skipped."""
        # Session with new format (has channel_id)
        new_session = Session(
            session_id="new-456",
            computer_name="TestMac",
            tmux_session_name="new-tmux",
            adapter_type="telegram",
            title="New",
            adapter_metadata={"channel_id": "12345", "user_id": 67890},
        )

        session_manager = Mock()
        session_manager.list_sessions = AsyncMock(return_value=[new_session])
        session_manager.update_session = AsyncMock()

        # Execute migration
        await session_lifecycle.migrate_session_metadata(session_manager)

        # Verify NO update called (already migrated)
        session_manager.update_session.assert_not_called()

    async def test_skip_sessions_without_topic_id(self):
        """Test sessions without topic_id are skipped."""
        # Session without topic_id
        session = Session(
            session_id="no-topic-789",
            computer_name="TestMac",
            tmux_session_name="no-topic-tmux",
            adapter_type="telegram",
            title="No Topic",
            adapter_metadata={"user_id": 67890},
        )

        session_manager = Mock()
        session_manager.list_sessions = AsyncMock(return_value=[session])
        session_manager.update_session = AsyncMock()

        # Execute migration
        await session_lifecycle.migrate_session_metadata(session_manager)

        # Verify NO update called (no topic_id to migrate)
        session_manager.update_session.assert_not_called()

    async def test_skip_sessions_with_no_metadata(self):
        """Test sessions with None metadata are skipped."""
        session = Session(
            session_id="no-meta-999",
            computer_name="TestMac",
            tmux_session_name="no-meta-tmux",
            adapter_type="telegram",
            title="No Metadata",
            adapter_metadata=None,
        )

        session_manager = Mock()
        session_manager.list_sessions = AsyncMock(return_value=[session])
        session_manager.update_session = AsyncMock()

        # Execute migration
        await session_lifecycle.migrate_session_metadata(session_manager)

        # Verify NO update called
        session_manager.update_session.assert_not_called()

    async def test_migrate_multiple_sessions(self):
        """Test migration of multiple sessions at once."""
        old1 = Session(
            session_id="old-1",
            computer_name="TestMac",
            tmux_session_name="old-tmux-1",
            adapter_type="telegram",
            title="Old 1",
            adapter_metadata={"topic_id": 111},
        )
        old2 = Session(
            session_id="old-2",
            computer_name="TestMac",
            tmux_session_name="old-tmux-2",
            adapter_type="telegram",
            title="Old 2",
            adapter_metadata={"topic_id": 222},
        )
        new_session = Session(
            session_id="new-3",
            computer_name="TestMac",
            tmux_session_name="new-tmux-3",
            adapter_type="telegram",
            title="New",
            adapter_metadata={"channel_id": "333"},
        )

        session_manager = Mock()
        session_manager.list_sessions = AsyncMock(return_value=[old1, old2, new_session])
        session_manager.update_session = AsyncMock()

        # Execute migration
        await session_lifecycle.migrate_session_metadata(session_manager)

        # Verify 2 updates (only old1 and old2)
        assert session_manager.update_session.call_count == 2


@pytest.mark.asyncio
class TestPeriodicCleanup:
    """Test periodic_cleanup function."""

    async def test_periodic_cleanup_runs_cleanup_every_hour(self):
        """Test that periodic_cleanup calls cleanup_inactive_sessions every hour."""
        session_manager = Mock()
        config = {}

        with patch("teleclaude.core.session_lifecycle.cleanup_inactive_sessions") as mock_cleanup:
            mock_cleanup.return_value = None

            with patch("asyncio.sleep") as mock_sleep:
                # Make sleep raise CancelledError after 2 calls
                mock_sleep.side_effect = [None, asyncio.CancelledError()]

                # Execute (will exit after 2 iterations)
                await session_lifecycle.periodic_cleanup(session_manager, config)

                # Verify sleep called with 3600 seconds (1 hour)
                assert mock_sleep.call_count == 2
                mock_sleep.assert_any_call(3600)

                # Verify cleanup called once (before CancelledError)
                assert mock_cleanup.call_count == 1

    async def test_periodic_cleanup_handles_exceptions(self):
        """Test periodic_cleanup continues running even after exceptions."""
        session_manager = Mock()
        config = {}

        with patch("teleclaude.core.session_lifecycle.cleanup_inactive_sessions") as mock_cleanup:
            # First call raises exception, second succeeds, third raises CancelledError
            mock_cleanup.side_effect = [
                Exception("Test error"),
                None,
                asyncio.CancelledError(),
            ]

            with patch("asyncio.sleep") as mock_sleep:
                mock_sleep.return_value = None

                # Execute (will continue after exception, exit on CancelledError)
                await session_lifecycle.periodic_cleanup(session_manager, config)

                # Verify cleanup called 3 times (error, success, cancelled)
                assert mock_cleanup.call_count == 3


@pytest.mark.asyncio
class TestCleanupInactiveSessions:
    """Test cleanup_inactive_sessions function."""

    async def test_cleanup_sessions_inactive_72_hours(self):
        """Test cleanup of sessions inactive for 72+ hours."""
        # Create session inactive for 73 hours
        old_time = datetime.now() - timedelta(hours=73)
        inactive_session = Session(
            session_id="inactive-123",
            computer_name="TestMac",
            tmux_session_name="inactive-tmux",
            adapter_type="telegram",
            title="Inactive",
            status="active",
            last_activity=old_time,
        )

        session_manager = Mock()
        session_manager.list_sessions = AsyncMock(return_value=[inactive_session])
        session_manager.update_session = AsyncMock()

        config = {}

        with patch("teleclaude.core.session_lifecycle.terminal_bridge") as mock_terminal:
            mock_terminal.kill_session = AsyncMock()

            # Execute cleanup
            await session_lifecycle.cleanup_inactive_sessions(session_manager, config)

            # Verify tmux session killed
            mock_terminal.kill_session.assert_called_once_with("inactive-tmux")

            # Verify session marked as closed
            session_manager.update_session.assert_called_once_with("inactive-123", status="closed")

    async def test_skip_recently_active_sessions(self):
        """Test that recently active sessions are not cleaned up."""
        # Create session active 1 hour ago
        recent_time = datetime.now() - timedelta(hours=1)
        active_session = Session(
            session_id="active-456",
            computer_name="TestMac",
            tmux_session_name="active-tmux",
            adapter_type="telegram",
            title="Active",
            status="active",
            last_activity=recent_time,
        )

        session_manager = Mock()
        session_manager.list_sessions = AsyncMock(return_value=[active_session])
        session_manager.update_session = AsyncMock()

        config = {}

        with patch("teleclaude.core.session_lifecycle.terminal_bridge") as mock_terminal:
            mock_terminal.kill_session = AsyncMock()

            # Execute cleanup
            await session_lifecycle.cleanup_inactive_sessions(session_manager, config)

            # Verify NO cleanup
            mock_terminal.kill_session.assert_not_called()
            session_manager.update_session.assert_not_called()

    async def test_skip_non_active_sessions(self):
        """Test that sessions with status != 'active' are skipped."""
        old_time = datetime.now() - timedelta(hours=100)
        closed_session = Session(
            session_id="closed-789",
            computer_name="TestMac",
            tmux_session_name="closed-tmux",
            adapter_type="telegram",
            title="Closed",
            status="closed",  # Not active
            last_activity=old_time,
        )

        session_manager = Mock()
        session_manager.list_sessions = AsyncMock(return_value=[closed_session])
        session_manager.update_session = AsyncMock()

        config = {}

        with patch("teleclaude.core.session_lifecycle.terminal_bridge") as mock_terminal:
            mock_terminal.kill_session = AsyncMock()

            # Execute cleanup
            await session_lifecycle.cleanup_inactive_sessions(session_manager, config)

            # Verify NO cleanup (status not active)
            mock_terminal.kill_session.assert_not_called()
            session_manager.update_session.assert_not_called()

    async def test_skip_sessions_without_last_activity(self):
        """Test sessions with no last_activity are skipped."""
        session = Session(
            session_id="no-activity-999",
            computer_name="TestMac",
            tmux_session_name="no-activity-tmux",
            adapter_type="telegram",
            title="No Activity",
            status="active",
            last_activity=None,  # No activity timestamp
        )

        session_manager = Mock()
        session_manager.list_sessions = AsyncMock(return_value=[session])
        session_manager.update_session = AsyncMock()

        config = {}

        with patch("teleclaude.core.session_lifecycle.terminal_bridge") as mock_terminal:
            mock_terminal.kill_session = AsyncMock()

            # Execute cleanup
            await session_lifecycle.cleanup_inactive_sessions(session_manager, config)

            # Verify NO cleanup (no last_activity)
            mock_terminal.kill_session.assert_not_called()
            session_manager.update_session.assert_not_called()

    async def test_cleanup_handles_exceptions(self):
        """Test cleanup continues even if exceptions occur."""
        old_time = datetime.now() - timedelta(hours=73)
        session1 = Session(
            session_id="session-1",
            computer_name="TestMac",
            tmux_session_name="tmux-1",
            adapter_type="telegram",
            title="Session 1",
            status="active",
            last_activity=old_time,
        )
        session2 = Session(
            session_id="session-2",
            computer_name="TestMac",
            tmux_session_name="tmux-2",
            adapter_type="telegram",
            title="Session 2",
            status="active",
            last_activity=old_time,
        )

        session_manager = Mock()
        session_manager.list_sessions = AsyncMock(side_effect=Exception("DB error"))

        config = {}

        # Execute cleanup (should not raise)
        await session_lifecycle.cleanup_inactive_sessions(session_manager, config)

        # Exception caught and logged, no crash
