"""Unit tests for terminal_bridge.py."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from teleclaude.core import terminal_bridge
from teleclaude.config import init_config


@pytest.fixture(autouse=True)
def setup_config():
    """Initialize config for all tests."""
    # Mock get_config at the terminal_bridge module level
    test_config = {
        "polling": {
            "lpoll_extensions": []
        }
    }
    with patch('teleclaude.core.terminal_bridge.get_config', return_value=test_config):
        yield


class TestSendKeys:
    """Tests for send_keys() function."""

    @pytest.mark.asyncio
    async def test_append_exit_marker_true(self):
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
    async def test_append_exit_marker_false(self):
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

                text_arg = send_keys_call[0][0][4]
                assert '__EXIT__' not in text_arg, "Should NOT include exit marker"
                assert text_arg == "some input", "Should include only original text"


class TestSendCtrlKey:
    """Tests for send_ctrl_key() function."""

    @pytest.mark.asyncio
    async def test_send_ctrl_key_success(self):
        """Test sending CTRL+key combination."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_ctrl_key(
                session_name="test-session",
                key="d"
            )

            assert success is True
            mock_exec.assert_called_once()
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "C-d")

    @pytest.mark.asyncio
    async def test_send_ctrl_key_uppercase(self):
        """Test that uppercase keys are converted to lowercase."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            success = await terminal_bridge.send_ctrl_key(
                session_name="test-session",
                key="Z"
            )

            assert success is True
            call_args = mock_exec.call_args[0]
            assert call_args == ("tmux", "send-keys", "-t", "test-session", "C-z")


class TestCommandValidation:
    """Tests for command chaining validation."""

    @pytest.mark.asyncio
    async def test_reject_command_chaining_with_long_running(self):
        """Test that command chaining with long-running processes is rejected."""
        with patch.object(terminal_bridge, 'session_exists', return_value=True):
            success = await terminal_bridge.send_keys(
                session_name="test-session",
                text="vim file.txt && ls",
                append_exit_marker=True
            )
            assert success is False, "Should return False when rejecting command chaining"

    @pytest.mark.asyncio
    async def test_allow_long_running_without_chaining(self):
        """Test that long-running commands without chaining are allowed."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.wait = AsyncMock()
            mock_exec.return_value = mock_process

            with patch.object(terminal_bridge, 'session_exists', return_value=True):
                success = await terminal_bridge.send_keys(
                    session_name="test-session",
                    text="vim file.txt",
                    append_exit_marker=True
                )
                assert success is True


class TestIsLongRunningCommand:
    """Tests for is_long_running_command() function."""

    def test_claude_is_long_running(self):
        """Test that 'claude' is recognized as long-running."""
        assert terminal_bridge.is_long_running_command("claude")
        assert terminal_bridge.is_long_running_command("claude .")
        assert terminal_bridge.is_long_running_command("Claude")  # case-insensitive

    def test_text_editors_are_long_running(self):
        """Test that text editors are recognized as long-running."""
        editors = ["vim", "vi", "nvim", "nano", "emacs", "micro", "helix"]
        for editor in editors:
            assert terminal_bridge.is_long_running_command(editor)
            assert terminal_bridge.is_long_running_command(f"{editor} file.txt")

    def test_system_monitors_are_long_running(self):
        """Test that system monitors are recognized as long-running."""
        monitors = ["top", "htop", "btop", "iotop", "glances"]
        for monitor in monitors:
            assert terminal_bridge.is_long_running_command(monitor)

    def test_pagers_are_long_running(self):
        """Test that pagers are recognized as long-running."""
        assert terminal_bridge.is_long_running_command("less file.log")
        assert terminal_bridge.is_long_running_command("more file.txt")

    def test_repls_are_long_running(self):
        """Test that REPLs are recognized as long-running."""
        repls = ["python", "python3", "node", "irb", "psql"]
        for repl in repls:
            assert terminal_bridge.is_long_running_command(repl)

    def test_regular_commands_not_long_running(self):
        """Test that regular commands are NOT long-running."""
        regular_commands = ["ls", "cat", "echo", "pwd", "cd", "mkdir"]
        for cmd in regular_commands:
            assert not terminal_bridge.is_long_running_command(cmd)

    def test_empty_command(self):
        """Test empty command."""
        assert not terminal_bridge.is_long_running_command("")
        assert not terminal_bridge.is_long_running_command("   ")


class TestHasCommandSeparator:
    """Tests for has_command_separator() function."""

    def test_detects_semicolon(self):
        """Test detection of semicolon separator."""
        assert terminal_bridge.has_command_separator("echo 1; echo 2")
        assert terminal_bridge.has_command_separator("ls -la; pwd")

    def test_detects_and_operator(self):
        """Test detection of && operator."""
        assert terminal_bridge.has_command_separator("make build && make test")
        assert terminal_bridge.has_command_separator("cd /tmp && ls")

    def test_detects_or_operator(self):
        """Test detection of || operator."""
        assert terminal_bridge.has_command_separator("test -f file || echo missing")
        assert terminal_bridge.has_command_separator("command1 || command2")

    def test_no_separator(self):
        """Test commands without separators."""
        assert not terminal_bridge.has_command_separator("ls -la")
        assert not terminal_bridge.has_command_separator("echo hello world")

    def test_pipe_not_separator(self):
        """Test that pipes are NOT considered command separators."""
        # Pipes should be allowed (not blocked)
        assert not terminal_bridge.has_command_separator("ls | grep txt")
        assert not terminal_bridge.has_command_separator("cat file | wc -l")

    def test_redirect_not_separator(self):
        """Test that redirects are NOT considered command separators."""
        assert not terminal_bridge.has_command_separator("echo hello > file.txt")
        assert not terminal_bridge.has_command_separator("cat < input.txt")


class TestGetLpollList:
    """Tests for _get_lpoll_list() function."""

    def test_returns_defaults(self):
        """Test that defaults are included."""
        with patch('teleclaude.core.terminal_bridge.get_config') as mock_config:
            mock_config.return_value = {"polling": {}}
            lpoll_list = terminal_bridge._get_lpoll_list()

            # Check some known defaults
            assert "claude" in lpoll_list
            assert "vim" in lpoll_list
            assert "top" in lpoll_list

    def test_includes_extensions(self):
        """Test that config extensions are added."""
        with patch('teleclaude.core.terminal_bridge.get_config') as mock_config:
            mock_config.return_value = {
                "polling": {
                    "lpoll_extensions": ["custom-app", "my-tool"]
                }
            }
            lpoll_list = terminal_bridge._get_lpoll_list()

            # Check defaults still present
            assert "claude" in lpoll_list
            # Check extensions added
            assert "custom-app" in lpoll_list
            assert "my-tool" in lpoll_list

    def test_empty_extensions(self):
        """Test with no extensions configured."""
        with patch('teleclaude.core.terminal_bridge.get_config') as mock_config:
            mock_config.return_value = {"polling": {"lpoll_extensions": []}}
            lpoll_list = terminal_bridge._get_lpoll_list()

            # Should just have defaults
            assert len(lpoll_list) == len(terminal_bridge.LPOLL_DEFAULT_LIST)
