"""Unit tests for terminal_bridge.py."""

import errno
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core import terminal_bridge


@pytest.fixture(autouse=True)
def setup_config():
    """Initialize config for all tests."""
    # Mock _SHELL_NAME for consistent test behavior
    with patch.object(terminal_bridge, "_SHELL_NAME", "zsh"):
        yield


def test_tty_to_pty_master_legacy_suffix():
    """Legacy /dev/ttyp0 style names map to /dev/ptyp0."""
    assert terminal_bridge._tty_to_pty_master("/dev/ttyp0") == "/dev/ptyp0"


def test_tty_to_pty_master_modern_ttys_returns_none():
    """Modern /dev/ttysNNN devices do not expose a master path."""
    assert terminal_bridge._tty_to_pty_master("/dev/ttys050") is None


@pytest.mark.asyncio
async def test_send_keys_to_tty_injects_input():
    """send_keys_to_tty should inject bytes via TIOCSTI when available."""
    injected: list[bytes] = []

    async def _run(fn):
        fn()

    def _ioctl(_fd: int, _op: int, arg: bytes) -> int:
        injected.append(arg)
        return 0

    with (
        patch.object(terminal_bridge.asyncio, "to_thread", new=AsyncMock(side_effect=_run)),
        patch.object(terminal_bridge.os, "open", return_value=3),
        patch.object(terminal_bridge.os, "close"),
        patch.object(terminal_bridge.fcntl, "ioctl", side_effect=_ioctl),
    ):
        ok = await terminal_bridge.send_keys_to_tty("/dev/ttys001", "hello", send_enter=True)

    assert ok is True
    assert b"hello\n" == b"".join(injected)


@pytest.mark.asyncio
async def test_send_keys_to_tty_writes_to_pty_master():
    """send_keys_to_tty should write directly when given a PTY master path."""
    written: list[bytes] = []

    async def _run(fn):
        fn()

    def _write(_fd: int, chunk: bytes) -> int:
        write_len = max(1, len(chunk) // 2)
        written.append(chunk[:write_len])
        return write_len

    with (
        patch.object(terminal_bridge.asyncio, "to_thread", new=AsyncMock(side_effect=_run)),
        patch.object(terminal_bridge.os, "open", return_value=3),
        patch.object(terminal_bridge.os, "close"),
        patch.object(terminal_bridge.os, "write", side_effect=_write),
    ):
        ok = await terminal_bridge.send_keys_to_tty("/dev/ptys001", "hello", send_enter=True)

    assert ok is True
    assert b"hello\n" == b"".join(written)


@pytest.mark.asyncio
async def test_send_keys_to_tty_returns_false_on_hard_error():
    """send_keys_to_tty should return False if injection fails with a hard error."""

    async def _run(fn):
        fn()

    def _ioctl(_fd: int, _op: int, _arg: bytes) -> int:
        raise OSError(errno.EPERM, "not permitted")

    with (
        patch.object(terminal_bridge.asyncio, "to_thread", new=AsyncMock(side_effect=_run)),
        patch.object(terminal_bridge.os, "open", return_value=3),
        patch.object(terminal_bridge.os, "close"),
        patch.object(terminal_bridge.fcntl, "ioctl", side_effect=_ioctl),
    ):
        ok = await terminal_bridge.send_keys_to_tty("/dev/ttys001", "hello", send_enter=True)

    assert ok is False


@pytest.mark.asyncio
async def test_send_keys_to_tty_retries_on_eagain():
    """send_keys_to_tty should retry injection on EAGAIN and still send all bytes."""
    injected: list[bytes] = []
    calls = 0

    async def _run(fn):
        fn()

    def _ioctl(_fd: int, _op: int, arg: bytes) -> int:
        nonlocal calls
        if calls < 2:
            calls += 1
            raise OSError(errno.EAGAIN, "try again")
        injected.append(arg)
        return 0

    with (
        patch.object(terminal_bridge.asyncio, "to_thread", new=AsyncMock(side_effect=_run)),
        patch.object(terminal_bridge.os, "open", return_value=3),
        patch.object(terminal_bridge.os, "close"),
        patch.object(terminal_bridge.fcntl, "ioctl", side_effect=_ioctl),
    ):
        ok = await terminal_bridge.send_keys_to_tty("/dev/ttys001", "hello", send_enter=True)

    assert ok is True
    assert b"hello\n" == b"".join(injected)


class TestSendKeys:
    """Tests for send_keys() function."""

    @pytest.mark.asyncio
    async def test_send_keys_sends_text(self):
        """Test that send_keys wraps text in bracketed paste escape sequences."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock subprocess
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_process

            # Mock session exists
            with (
                patch.object(terminal_bridge, "session_exists", new=AsyncMock(return_value=True)),
                patch("asyncio.sleep", new=AsyncMock()) as mock_sleep,
            ):
                success = await terminal_bridge.send_keys(session_name="test-session", text="ls -la")

                assert success is True
                mock_sleep.assert_awaited_once_with(1.0)

                # Verify send_keys command sends text as-is (no bracketed paste)
                call_args_list = mock_exec.call_args_list
                send_keys_call = [call for call in call_args_list if "send-keys" in call[0]]
                assert len(send_keys_call) > 0
                text_arg = send_keys_call[0][0][-1]
                assert text_arg == "ls -la"

    @pytest.mark.asyncio
    async def test_recreates_session_with_session_id(self):
        """Test that session recreation passes session_id for env var + TMPDIR injection."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_process

            with (
                patch.object(terminal_bridge, "session_exists", new=AsyncMock(return_value=False)),
                patch.object(terminal_bridge, "create_tmux_session", new=AsyncMock(return_value=True)) as mock_create,
                patch("asyncio.sleep", new=AsyncMock()),
            ):
                success = await terminal_bridge.send_keys(
                    session_name="test-session",
                    text="echo hello",
                    session_id="sid-123",
                    working_dir="/tmp",
                )

        assert success is True
        mock_create.assert_awaited_once()
        assert mock_create.await_args.kwargs.get("session_id") == "sid-123"

    @pytest.mark.asyncio
    async def test_escapes_exclamation_for_gemini(self):
        """Test that exclamation marks are escaped for Gemini agent."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_process

            with (
                patch.object(terminal_bridge, "session_exists", new=AsyncMock(return_value=True)),
                patch("asyncio.sleep", new=AsyncMock()),
            ):
                success = await terminal_bridge.send_keys(
                    session_name="test-session",
                    text="Hello! World!",
                    active_agent="gemini",
                    send_enter=False,
                )

                assert success is True

                # Verify exclamation marks are escaped for Gemini
                call_args_list = mock_exec.call_args_list
                send_keys_call = [call for call in call_args_list if "send-keys" in call[0]]
                assert len(send_keys_call) > 0
                text_arg = send_keys_call[0][0][-1]
                assert text_arg == r"Hello\! World\!"

    @pytest.mark.asyncio
    async def test_no_escaping_for_non_gemini(self):
        """Test that exclamation marks are NOT escaped for non-Gemini agents."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = MagicMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_process

            with (
                patch.object(terminal_bridge, "session_exists", new=AsyncMock(return_value=True)),
                patch("asyncio.sleep", new=AsyncMock()),
            ):
                success = await terminal_bridge.send_keys(
                    session_name="test-session",
                    text="Hello! World!",
                    active_agent="claude",
                )

                assert success is True

                # Verify exclamation marks are NOT escaped for Claude
                call_args_list = mock_exec.call_args_list
                send_keys_call = [call for call in call_args_list if "send-keys" in call[0]]
                assert len(send_keys_call) > 0
                text_arg = send_keys_call[0][0][-1]
                assert text_arg == "Hello! World!"


class TestSendKeysExistingTmux:
    """Tests for send_keys_existing_tmux() function."""

    @pytest.mark.asyncio
    async def test_returns_false_when_session_missing(self):
        with (
            patch.object(terminal_bridge, "session_exists", new=AsyncMock(return_value=False)),
            patch.object(terminal_bridge, "_send_keys_tmux", new=AsyncMock()) as mock_send,
        ):
            success = await terminal_bridge.send_keys_existing_tmux(
                session_name="missing-session",
                text="hello",
            )

            assert success is False
            mock_send.assert_not_awaited()


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
