"""Unit tests for event_handlers module."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import event_handlers
from teleclaude.core.models import Session


@pytest.mark.asyncio
class TestHandleTopicClosed:
    """Test handle_topic_closed function."""

    async def test_topic_closed_success(self):
        """Test successful topic closure with tmux session killed."""
        session = Session(
            session_id="test-123",
            computer_name="TestMac",
            tmux_session_name="test-tmux",
            adapter_type="telegram",
            title="Test",
            closed=False,
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_session = AsyncMock()

        context = {"topic_id": 12345, "user_id": 67890}

        with patch("teleclaude.core.event_handlers.terminal_bridge") as mock_terminal:
            mock_terminal.kill_session = AsyncMock(return_value=True)

            # Execute
            await event_handlers.handle_topic_closed(
                session_id="test-123", context=context, session_manager=session_manager
            )

            # Verify tmux session killed
            mock_terminal.kill_session.assert_called_once_with("test-tmux")

            # Verify session marked as closed
            session_manager.update_session.assert_called_once_with("test-123", closed=True)

    async def test_topic_closed_session_not_found(self):
        """Test topic closure when session doesn't exist."""
        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=None)
        session_manager.update_session = AsyncMock()

        context = {"topic_id": 12345}

        with patch("teleclaude.core.event_handlers.terminal_bridge") as mock_terminal:
            mock_terminal.kill_session = AsyncMock()

            # Execute
            await event_handlers.handle_topic_closed(
                session_id="nonexistent", context=context, session_manager=session_manager
            )

            # Verify NO tmux kill attempted (session not found)
            mock_terminal.kill_session.assert_not_called()

            # Verify NO update attempted
            session_manager.update_session.assert_not_called()

    async def test_topic_closed_tmux_kill_failure(self):
        """Test topic closure when tmux kill fails (still marks as closed)."""
        session = Session(
            session_id="test-456",
            computer_name="TestMac",
            tmux_session_name="test-tmux-2",
            adapter_type="telegram",
            title="Test",
            closed=False,
        )

        session_manager = Mock()
        session_manager.get_session = AsyncMock(return_value=session)
        session_manager.update_session = AsyncMock()

        context = {"topic_id": 67890}

        with patch("teleclaude.core.event_handlers.terminal_bridge") as mock_terminal:
            # Simulate tmux kill failure
            mock_terminal.kill_session = AsyncMock(return_value=False)

            # Execute
            await event_handlers.handle_topic_closed(
                session_id="test-456", context=context, session_manager=session_manager
            )

            # Verify tmux kill was attempted
            mock_terminal.kill_session.assert_called_once_with("test-tmux-2")

            # Verify session STILL marked as closed (even if tmux kill failed)
            session_manager.update_session.assert_called_once_with("test-456", closed=True)
