"""Unit tests for restart_claude.py."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.models import Session
from teleclaude.restart_claude import main


@pytest.fixture
def mock_session():
    """Create a mock Session object."""
    return Session(
        session_id="test-session-id-12345",
        computer_name="TestPC",
        tmux_session_name="test-tmux-session",
        origin_adapter="telegram",
        title="Test Session",
        adapter_metadata={},
        closed=False,
        terminal_size="120x40",
        working_directory="/home/test",
    )


class TestRestartClaude:
    """Tests for restart_claude main function."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_exits_gracefully_without_env_var(self):
        """Test that script exits gracefully when TELECLAUDE_SESSION_ID is not set."""
        # Ensure env var is not set
        env_backup = os.environ.get("TELECLAUDE_SESSION_ID")
        if env_backup:
            del os.environ["TELECLAUDE_SESSION_ID"]

        try:
            with pytest.raises(SystemExit) as exc_info:
                await main()

            # Should exit with code 1
            assert exc_info.value.code == 1
        finally:
            # Restore env var
            if env_backup:
                os.environ["TELECLAUDE_SESSION_ID"] = env_backup

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_sends_restart_command_when_session_found(self, mock_session):
        """Test that restart command is sent when session is found."""
        # Set env var
        os.environ["TELECLAUDE_SESSION_ID"] = "test-claude-session-123"

        try:
            # Mock db
            mock_db_instance = AsyncMock()
            mock_db_instance.initialize = AsyncMock()
            mock_db_instance.get_session = AsyncMock(return_value=mock_session)
            mock_db_instance.close = AsyncMock()

            # Mock terminal_bridge
            mock_send_keys = AsyncMock(return_value=True)

            with (
                patch("teleclaude.restart_claude.Db") as mock_db_class,
                patch("teleclaude.restart_claude.terminal_bridge.send_keys", mock_send_keys),
            ):
                mock_db_class.return_value = mock_db_instance

                # Run main
                await main()

                # Verify db methods called
                mock_db_instance.initialize.assert_called_once()
                mock_db_instance.get_session.assert_called_once_with("test-claude-session-123")
                mock_db_instance.close.assert_called_once()

                # Verify terminal_bridge.send_keys called correctly
                mock_send_keys.assert_called_once()
                call_kwargs = mock_send_keys.call_args.kwargs
                assert call_kwargs["session_name"] == "test-tmux-session"
                assert "claude --dangerously-skip-permissions --continue" in call_kwargs["text"]
                assert call_kwargs["append_exit_marker"] is False
                assert call_kwargs["send_enter"] is True
                assert call_kwargs["working_dir"] == "/home/test"  # Uses session's working_directory

        finally:
            # Cleanup env var
            if "TELECLAUDE_SESSION_ID" in os.environ:
                del os.environ["TELECLAUDE_SESSION_ID"]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_exits_when_session_not_found(self):
        """Test that script exits when no session is found for teleclaude_session_id."""
        # Set env var
        os.environ["TELECLAUDE_SESSION_ID"] = "nonexistent-session"

        try:
            # Mock db to return None (session not found)
            mock_db_instance = AsyncMock()
            mock_db_instance.initialize = AsyncMock()
            mock_db_instance.get_session = AsyncMock(return_value=None)
            mock_db_instance.close = AsyncMock()

            with patch("teleclaude.restart_claude.Db") as mock_db_class:
                mock_db_class.return_value = mock_db_instance

                # Should exit with code 1
                with pytest.raises(SystemExit) as exc_info:
                    await main()

                assert exc_info.value.code == 1

                # Verify db was still closed
                mock_db_instance.close.assert_called_once()

        finally:
            # Cleanup env var
            if "TELECLAUDE_SESSION_ID" in os.environ:
                del os.environ["TELECLAUDE_SESSION_ID"]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_exits_when_send_keys_fails(self, mock_session):
        """Test that script exits when terminal_bridge.send_keys fails."""
        # Set env var
        os.environ["TELECLAUDE_SESSION_ID"] = "test-claude-session-123"

        try:
            # Mock db
            mock_db_instance = AsyncMock()
            mock_db_instance.initialize = AsyncMock()
            mock_db_instance.get_session = AsyncMock(return_value=mock_session)
            mock_db_instance.close = AsyncMock()

            # Mock terminal_bridge to return False (failure)
            mock_send_keys = AsyncMock(return_value=False)

            with (
                patch("teleclaude.restart_claude.Db") as mock_db_class,
                patch("teleclaude.restart_claude.terminal_bridge.send_keys", mock_send_keys),
            ):
                mock_db_class.return_value = mock_db_instance

                # Should exit with code 1
                with pytest.raises(SystemExit) as exc_info:
                    await main()

                assert exc_info.value.code == 1

                # Verify db was still closed
                mock_db_instance.close.assert_called_once()

        finally:
            # Cleanup env var
            if "TELECLAUDE_SESSION_ID" in os.environ:
                del os.environ["TELECLAUDE_SESSION_ID"]
