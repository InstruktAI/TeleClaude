"""Unit tests for terminal_bridge.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core import terminal_bridge


@pytest.fixture(autouse=True)
def setup_config():
    """Initialize config for all tests."""
    # Mock _SHELL_NAME for consistent test behavior
    with patch.object(terminal_bridge, "_SHELL_NAME", "zsh"):
        yield


class TestSendKeys:
    """Tests for send_keys() function."""

    @pytest.mark.asyncio
    async def test_append_exit_marker_when_shell_ready(self):
        """Test that exit marker is appended when shell is ready (current_command is 'zsh')."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Mock session exists and get_current_command returns shell
            with patch.object(terminal_bridge, "session_exists", return_value=True):
                with patch.object(terminal_bridge, "get_current_command", return_value="zsh"):
                    # Execute - should automatically append marker
                    success, marker_id = await terminal_bridge.send_keys(session_name="test-session", text="ls -la")

                    assert success is True
                    assert marker_id is not None, "Should return auto-generated marker_id"

                    # Verify send_keys command includes exit marker
                    call_args_list = mock_exec.call_args_list
                    # Find the send-keys call (not Enter)
                    send_keys_call = [call for call in call_args_list if "send-keys" in call[0]]
                    assert len(send_keys_call) > 0

                    # Check that the command includes exit marker with marker_id
                    text_arg = send_keys_call[0][0][4]  # 5th argument is the text
                    assert f"__EXIT__{marker_id}__" in text_arg, "Should include exit marker with marker_id"
                    assert "ls -la" in text_arg, "Should include original command"

    @pytest.mark.asyncio
    async def test_no_exit_marker_when_process_running(self):
        """Test that exit marker is NOT appended when a process is running (e.g., vim)."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Mock session exists and get_current_command returns 'vim'
            with patch.object(terminal_bridge, "session_exists", return_value=True):
                with patch.object(terminal_bridge, "get_current_command", return_value="vim"):
                    # Execute - should NOT append marker (process running)
                    success, marker_id = await terminal_bridge.send_keys(session_name="test-session", text="some input")

                    assert success is True
                    assert marker_id is None, "Should not return marker_id when no marker appended"

                    # Verify send_keys command does NOT include exit marker
                    call_args_list = mock_exec.call_args_list
                    send_keys_call = [call for call in call_args_list if "send-keys" in call[0]]
                    assert len(send_keys_call) > 0

                    text_arg = send_keys_call[0][0][4]
                    assert "__EXIT__" not in text_arg, "Should NOT include exit marker"
                    assert text_arg == "some input", "Should include only original text"

    @pytest.mark.asyncio
    async def test_append_exit_marker_when_no_command(self):
        """Test that exit marker is appended when no command is running (None)."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            # Mock session exists and get_current_command returns None
            with patch.object(terminal_bridge, "session_exists", return_value=True):
                with patch.object(terminal_bridge, "get_current_command", return_value=None):
                    # Execute - should append marker (shell ready)
                    success, marker_id = await terminal_bridge.send_keys(session_name="test-session", text="echo hello")

                    assert success is True
                    assert marker_id is not None, "Should return marker_id when marker appended"

                    # Verify send_keys command includes exit marker
                    call_args_list = mock_exec.call_args_list
                    send_keys_call = [call for call in call_args_list if "send-keys" in call[0]]
                    assert len(send_keys_call) > 0

                    text_arg = send_keys_call[0][0][4]
                    assert f"__EXIT__{marker_id}__" in text_arg, "Should include exit marker"
                    assert "echo hello" in text_arg, "Should include original command"

    @pytest.mark.asyncio
    async def test_recreates_session_with_session_id(self):
        """Test that session recreation passes session_id for env var + TMPDIR injection."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            with (
                patch.object(terminal_bridge, "session_exists", new=AsyncMock(return_value=False)),
                patch.object(terminal_bridge, "create_tmux_session", new=AsyncMock(return_value=True)) as mock_create,
                patch.object(terminal_bridge, "get_current_command", new=AsyncMock(return_value="zsh")),
            ):
                success, _ = await terminal_bridge.send_keys(
                    session_name="test-session",
                    text="echo hello",
                    session_id="sid-123",
                    working_dir="/tmp",
                )

        assert success is True
        mock_create.assert_awaited_once()
        assert mock_create.await_args.kwargs.get("session_id") == "sid-123"


class TestSendCtrlKey:
    """Tests for send_ctrl_key() function."""

    @pytest.mark.asyncio
    async def test_send_ctrl_key_success(self):
        """Test sending CTRL+key combination."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_ctrl_key(session_name="test-session", key="d")

            assert success is True
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "C-d")

    @pytest.mark.asyncio
    async def test_send_ctrl_key_uppercase(self):
        """Test that uppercase keys are converted to lowercase."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_ctrl_key(session_name="test-session", key="Z")

            assert success is True
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "C-z")


class TestSendTab:
    """Tests for send_tab() function."""

    @pytest.mark.asyncio
    async def test_send_tab_success(self):
        """Test sending TAB key."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_tab(session_name="test-session")

            assert success is True
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "Tab")

    @pytest.mark.asyncio
    async def test_send_tab_failure(self):
        """Test failure when sending TAB key."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_tab(session_name="test-session")

            assert success is False


class TestSendShiftTab:
    """Tests for send_shift_tab() function."""

    @pytest.mark.asyncio
    async def test_send_shift_tab_success(self):
        """Test sending SHIFT+TAB key."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_shift_tab(session_name="test-session")

            assert success is True
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "-N", "1", "BTab")

    @pytest.mark.asyncio
    async def test_send_shift_tab_failure(self):
        """Test failure when sending SHIFT+TAB key."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 1
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_shift_tab(session_name="test-session")

            assert success is False

    @pytest.mark.asyncio
    async def test_send_shift_tab_with_count(self):
        """Test sending SHIFT+TAB key with repeat count."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_shift_tab(session_name="test-session", count=3)

            assert success is True
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "-N", "3", "BTab")

    @pytest.mark.asyncio
    async def test_send_shift_tab_invalid_count(self):
        """Test sending SHIFT+TAB key with invalid count returns False."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            success = await terminal_bridge.send_shift_tab(session_name="test-session", count=0)

            assert success is False
            mock_exec.assert_not_called()


class TestSendArrowKey:
    """Tests for send_arrow_key() function."""

    @pytest.mark.asyncio
    async def test_send_arrow_up(self):
        """Test sending UP arrow key."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_arrow_key(session_name="test-session", direction="up", count=1)

            assert success is True
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "-N", "1", "Up")

    @pytest.mark.asyncio
    async def test_send_arrow_down_with_repeat(self):
        """Test sending DOWN arrow key with repeat count."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_arrow_key(session_name="test-session", direction="down", count=5)

            assert success is True
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "-N", "5", "Down")

    @pytest.mark.asyncio
    async def test_send_arrow_left(self):
        """Test sending LEFT arrow key."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_arrow_key(session_name="test-session", direction="left", count=3)

            assert success is True
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "-N", "3", "Left")

    @pytest.mark.asyncio
    async def test_send_arrow_right(self):
        """Test sending RIGHT arrow key."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_arrow_key(session_name="test-session", direction="right", count=10)

            assert success is True
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "-N", "10", "Right")

    @pytest.mark.asyncio
    async def test_send_arrow_invalid_direction(self):
        """Test failure with invalid direction."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            success = await terminal_bridge.send_arrow_key(session_name="test-session", direction="invalid", count=1)

            assert success is False
            mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_arrow_invalid_count(self):
        """Test failure with invalid count."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            success = await terminal_bridge.send_arrow_key(session_name="test-session", direction="up", count=0)

            assert success is False
            mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_arrow_negative_count(self):
        """Test failure with negative count."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            success = await terminal_bridge.send_arrow_key(session_name="test-session", direction="down", count=-5)

            assert success is False
            mock_exec.assert_not_called()
