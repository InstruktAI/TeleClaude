"""Unit tests for terminal_bridge.py."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from teleclaude.core.terminal_bridge import TerminalBridge


@pytest.fixture
def terminal_bridge():
    """Create TerminalBridge instance."""
    return TerminalBridge()


class TestSendKeys:
    """Tests for send_keys() method."""

    @pytest.mark.asyncio
    async def test_append_exit_marker_true(self, terminal_bridge):
        """Test that exit marker is appended when append_exit_marker=True."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Mock session exists
            with patch.object(terminal_bridge, 'session_exists', return_value=True):
                # Execute with append_exit_marker=True
                success = await terminal_bridge.send_keys(
                    session_name="test-session",
                    text="ls -la",
                    append_exit_marker=True
                )

                assert success is True

                # Verify send_keys command includes exit marker
                call_args_list = mock_exec.call_args_list
                # Find the send-keys call (not Enter)
                send_keys_call = [call for call in call_args_list if 'send-keys' in call[0]]
                assert len(send_keys_call) > 0

                # Check that the command includes exit marker
                text_arg = send_keys_call[0][0][4]  # 5th argument is the text
                assert '__EXIT__' in text_arg, "Should include exit marker"
                assert 'ls -la' in text_arg, "Should include original command"

    @pytest.mark.asyncio
    async def test_append_exit_marker_false(self, terminal_bridge):
        """Test that exit marker is NOT appended when append_exit_marker=False."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Mock session exists
            with patch.object(terminal_bridge, 'session_exists', return_value=True):
                # Execute with append_exit_marker=False
                success = await terminal_bridge.send_keys(
                    session_name="test-session",
                    text="some input",
                    append_exit_marker=False
                )

                assert success is True

                # Verify send_keys command does NOT include exit marker
                call_args_list = mock_exec.call_args_list
                send_keys_call = [call for call in call_args_list if 'send-keys' in call[0]]
                assert len(send_keys_call) > 0

                # Check that the command does NOT include exit marker
                text_arg = send_keys_call[0][0][4]  # 5th argument is the text
                assert '__EXIT__' not in text_arg, "Should NOT include exit marker"
                assert text_arg == 'some input', "Should be original text only"

    @pytest.mark.asyncio
    async def test_creates_session_if_not_exists(self, terminal_bridge):
        """Test that session is created if it doesn't exist."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Mock session_exists to return False first, then True
            with patch.object(terminal_bridge, 'session_exists', return_value=False):
                with patch.object(terminal_bridge, 'create_tmux_session', return_value=True) as mock_create:
                    # Execute
                    success = await terminal_bridge.send_keys(
                        session_name="new-session",
                        text="echo test",
                        append_exit_marker=True
                    )

                    assert success is True
                    # Verify create_tmux_session was called
                    mock_create.assert_called_once()


class TestSendEscape:
    """Tests for send_escape() method."""

    @pytest.mark.asyncio
    async def test_send_escape_success(self, terminal_bridge):
        """Test successful ESCAPE key send."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.send_escape("test-session")

            assert result is True

            # Verify command was correct
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "Escape")

    @pytest.mark.asyncio
    async def test_send_escape_failure(self, terminal_bridge):
        """Test ESCAPE key send failure."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess failure
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.send_escape("test-session")

            assert result is False

    @pytest.mark.asyncio
    async def test_send_escape_exception(self, terminal_bridge):
        """Test ESCAPE key send with exception."""
        with patch('asyncio.create_subprocess_exec', side_effect=Exception("Test error")):
            # Execute
            result = await terminal_bridge.send_escape("test-session")

            assert result is False


class TestSendSignal:
    """Tests for send_signal() method."""

    @pytest.mark.asyncio
    async def test_send_sigint(self, terminal_bridge):
        """Test sending SIGINT (Ctrl+C)."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.send_signal("test-session", "SIGINT")

            assert result is True

            # Verify command includes C-c
            call_args = mock_exec.call_args[0]
            assert "C-c" in call_args

    @pytest.mark.asyncio
    async def test_send_sigterm(self, terminal_bridge):
        """Test sending SIGTERM (Ctrl+\\)."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.send_signal("test-session", "SIGTERM")

            assert result is True

            # Verify command includes C-\ (single backslash in tmux syntax)
            call_args = mock_exec.call_args[0]
            assert "C-\\" in call_args


class TestSessionManagement:
    """Tests for session management methods."""

    @pytest.mark.asyncio
    async def test_session_exists_true(self, terminal_bridge):
        """Test session_exists returns True when session exists."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess success (returncode 0 = session exists)
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b'', b''))
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.session_exists("existing-session")

            assert result is True

    @pytest.mark.asyncio
    async def test_session_exists_false(self, terminal_bridge):
        """Test session_exists returns False when session doesn't exist."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess failure (returncode 1 = session doesn't exist)
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.communicate = AsyncMock(return_value=(b'', b'session not found'))
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.session_exists("nonexistent-session")

            assert result is False

    @pytest.mark.asyncio
    async def test_session_exists_exception(self, terminal_bridge):
        """Test session_exists returns False on exception."""
        with patch('asyncio.create_subprocess_exec', side_effect=Exception("Test error")):
            # Execute
            result = await terminal_bridge.session_exists("error-session")

            assert result is False


class TestCapturePane:
    """Tests for capture_pane method."""

    @pytest.mark.asyncio
    async def test_capture_pane_success(self, terminal_bridge):
        """Test successful pane capture."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b'test output\nline 2', b''))
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.capture_pane("test-session")

            assert result == "test output\nline 2"

    @pytest.mark.asyncio
    async def test_capture_pane_with_lines_limit(self, terminal_bridge):
        """Test pane capture with lines limit."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b'output', b''))
            mock_exec.return_value = mock_process

            # Execute with lines limit
            result = await terminal_bridge.capture_pane("test-session", lines=100)

            assert result == "output"
            # Verify -S flag was used
            call_args = mock_exec.call_args[0]
            assert "-S" in call_args
            assert "-100" in call_args

    @pytest.mark.asyncio
    async def test_capture_pane_failure(self, terminal_bridge):
        """Test pane capture failure."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess failure
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.communicate = AsyncMock(return_value=(b'', b'error'))
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.capture_pane("test-session")

            assert result == ""

    @pytest.mark.asyncio
    async def test_capture_pane_exception(self, terminal_bridge):
        """Test pane capture with exception."""
        with patch('asyncio.create_subprocess_exec', side_effect=Exception("Test error")):
            # Execute
            result = await terminal_bridge.capture_pane("test-session")

            assert result == ""


class TestCreateSession:
    """Tests for create_tmux_session method."""

    @pytest.mark.asyncio
    async def test_create_session_success(self, terminal_bridge):
        """Test successful session creation."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.create_tmux_session(
                name="new-session",
                shell="/bin/bash",
                working_dir="/tmp",
                cols=100,
                rows=30
            )

            assert result is True
            # Verify command was correct
            call_args = mock_exec.call_args[0]
            assert "tmux" in call_args
            assert "new-session" in call_args
            assert "new-session" in call_args  # session name
            assert "100" in call_args  # cols
            assert "30" in call_args  # rows

    @pytest.mark.asyncio
    async def test_create_session_failure(self, terminal_bridge):
        """Test session creation failure."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess failure
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.create_tmux_session(
                name="fail-session",
                shell="/bin/bash",
                working_dir="/tmp"
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_create_session_exception(self, terminal_bridge):
        """Test session creation with exception."""
        with patch('asyncio.create_subprocess_exec', side_effect=Exception("Test error")):
            # Execute
            result = await terminal_bridge.create_tmux_session(
                name="error-session",
                shell="/bin/bash",
                working_dir="/tmp"
            )

            assert result is False


class TestListSessions:
    """Tests for list_tmux_sessions method."""

    @pytest.mark.asyncio
    async def test_list_sessions_success(self, terminal_bridge):
        """Test successful session listing."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b'session-1\nsession-2\nsession-3', b''))
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.list_tmux_sessions()

            assert result == ['session-1', 'session-2', 'session-3']

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, terminal_bridge):
        """Test listing sessions when none exist."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess with empty output
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b'', b''))
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.list_tmux_sessions()

            assert result == []

    @pytest.mark.asyncio
    async def test_list_sessions_failure(self, terminal_bridge):
        """Test session listing failure."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess failure
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.communicate = AsyncMock(return_value=(b'', b'error'))
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.list_tmux_sessions()

            assert result == []


class TestKillSession:
    """Tests for kill_session method."""

    @pytest.mark.asyncio
    async def test_kill_session_success(self, terminal_bridge):
        """Test successful session kill."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.kill_session("test-session")

            assert result is True

    @pytest.mark.asyncio
    async def test_kill_session_failure(self, terminal_bridge):
        """Test session kill failure."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess failure
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.kill_session("test-session")

            assert result is False


class TestResizeSession:
    """Tests for resize_session method."""

    @pytest.mark.asyncio
    async def test_resize_session_success(self, terminal_bridge):
        """Test successful session resize."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.resize_session("test-session", cols=120, rows=40)

            assert result is True
            # Verify resize command was called
            assert mock_exec.call_count >= 1

    @pytest.mark.asyncio
    async def test_resize_session_failure(self, terminal_bridge):
        """Test session resize failure."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock subprocess failure on resize command
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Execute
            result = await terminal_bridge.resize_session("test-session", cols=100, rows=30)

            assert result is False
