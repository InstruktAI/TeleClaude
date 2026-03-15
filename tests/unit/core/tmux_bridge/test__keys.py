"""Characterization tests for tmux bridge key dispatch."""

from __future__ import annotations

from signal import SIGHUP, SIGINT, SIGKILL, SIGTERM
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.core.tmux_bridge import _keys


def _completed_process(*, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode)


class TestPidIsAlive:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("side_effect", "expected"),
        [
            (None, True),
            (PermissionError(), True),
            (OSError(), False),
        ],
    )
    def test_kill_probe_maps_exceptions_to_liveness(self, side_effect: BaseException | None, expected: bool) -> None:
        with patch("teleclaude.core.tmux_bridge._keys.os.kill", side_effect=side_effect):
            assert _keys.pid_is_alive(321) is expected


class TestSendKeys:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_ensures_session_before_dispatching(self) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.ensure_tmux_session", new=AsyncMock(return_value=True)
            ) as mock_ensure,
            patch("teleclaude.core.tmux_bridge._keys._send_keys_tmux", new=AsyncMock(return_value=True)) as mock_send,
        ):
            result = await _keys.send_keys(
                session_name="tmux-alpha",
                text="echo hi",
                session_id="sess-1",
                working_dir="/tmp/demo",
                send_enter=False,
                active_agent="claude",
            )

        assert result is True
        mock_ensure.assert_awaited_once_with(name="tmux-alpha", working_dir="/tmp/demo", session_id="sess-1")
        mock_send.assert_awaited_once_with(
            session_name="tmux-alpha",
            text="echo hi",
            send_enter=False,
            active_agent="claude",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_returns_false_when_session_cannot_be_ensured(self) -> None:
        with (
            patch("teleclaude.core.tmux_bridge._keys.ensure_tmux_session", new=AsyncMock(return_value=False)),
            patch("teleclaude.core.tmux_bridge._keys._send_keys_tmux", new=AsyncMock()) as mock_send,
        ):
            result = await _keys.send_keys(session_name="tmux-alpha", text="echo hi")

        assert result is False
        mock_send.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_existing_tmux_returns_false_when_dispatch_raises(self) -> None:
        with patch(
            "teleclaude.core.tmux_bridge._keys._send_keys_tmux", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            result = await _keys.send_keys_existing_tmux(session_name="tmux-alpha", text="echo hi")

        assert result is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_existing_tmux_uses_literal_mode_for_bracketed_paste_and_gemini_bang(self) -> None:
        processes = [_completed_process(), _completed_process()]

        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=processes),
            ) as mock_exec,
            patch(
                "teleclaude.core.tmux_bridge._keys.communicate_with_timeout",
                new=AsyncMock(side_effect=[(b"", b""), (b"", b"")]),
            ),
            patch("teleclaude.core.tmux_bridge._keys.asyncio.sleep", new=AsyncMock()) as mock_sleep,
        ):
            result = await _keys.send_keys_existing_tmux(
                session_name="tmux-alpha",
                text="\x1b[200~run!\x1b[201~",
                active_agent=AgentName.GEMINI.value,
            )

        assert result is True
        assert mock_exec.await_args_list[0].args == (
            _keys.config.computer.tmux_binary,
            "send-keys",
            "-t",
            "tmux-alpha",
            "-l",
            "--",
            r"run\!",
        )
        assert mock_exec.await_args_list[1].args == (
            _keys.config.computer.tmux_binary,
            "send-keys",
            "-t",
            "tmux-alpha",
            "C-m",
        )
        mock_sleep.assert_awaited_once_with(1.0)


class TestSendKeysToTty:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_to_tty_writes_newline_to_pty_master(self) -> None:
        write_calls: list[bytes] = []

        async def run_inline(func: object) -> None:
            callable_func = func
            assert callable(callable_func)
            callable_func()

        def capture_write(fd: int, data: bytes) -> int:
            assert fd == 11
            write_calls.append(data)
            return len(data)

        with (
            patch("teleclaude.core.tmux_bridge._keys.asyncio.to_thread", new=AsyncMock(side_effect=run_inline)),
            patch("teleclaude.core.tmux_bridge._keys.os.open", return_value=11),
            patch("teleclaude.core.tmux_bridge._keys.os.write", side_effect=capture_write),
            patch("teleclaude.core.tmux_bridge._keys.os.close") as mock_close,
            patch("teleclaude.core.tmux_bridge._keys.fcntl.ioctl") as mock_ioctl,
        ):
            result = await _keys.send_keys_to_tty("/dev/ptyp0", "status", send_enter=True)

        assert result is True
        assert write_calls == [b"status\n"]
        mock_close.assert_called_once_with(11)
        mock_ioctl.assert_not_called()


class TestSendSignal:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_sigkill_targets_the_first_child_pid(self) -> None:
        processes = [_completed_process(), _completed_process(), _completed_process()]

        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=processes),
            ) as mock_exec,
            patch(
                "teleclaude.core.tmux_bridge._keys.communicate_with_timeout",
                new=AsyncMock(side_effect=[(b"321\n", b""), (b"654\n987\n", b""), (b"", b"")]),
            ),
        ):
            result = await _keys.send_signal("tmux-alpha", SIGKILL)

        assert result is True
        assert mock_exec.await_args_list[0].args == (
            _keys.config.computer.tmux_binary,
            "display-message",
            "-p",
            "-t",
            "tmux-alpha",
            "#{pane_pid}",
        )
        assert mock_exec.await_args_list[1].args == ("pgrep", "-P", "321")
        assert mock_exec.await_args_list[2].args == ("kill", "-9", "654")

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("signal_value", "key_name"), [(SIGINT, "C-c"), (SIGTERM, "C-\\")])
    async def test_control_signals_map_to_tmux_keys(self, signal_value: int, key_name: str) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process()),
            ) as mock_exec,
            patch(
                "teleclaude.core.tmux_bridge._keys.communicate_with_timeout",
                new=AsyncMock(return_value=(b"", b"")),
            ),
        ):
            result = await _keys.send_signal("tmux-alpha", signal_value)

        assert result is True
        assert mock_exec.await_args.args == (
            _keys.config.computer.tmux_binary,
            "send-keys",
            "-t",
            "tmux-alpha",
            key_name,
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unsupported_signal_returns_false_without_subprocesses(self) -> None:
        with patch("teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            result = await _keys.send_signal("tmux-alpha", SIGHUP)

        assert result is False
        mock_exec.assert_not_awaited()


class TestSpecialKeyHelpers:
    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("helper_name", "kwargs", "expected_call"),
        [
            ("send_escape", {}, ("send-keys", "-t", "tmux-alpha", "Escape")),
            ("send_ctrl_key", {"key": "Z"}, ("send-keys", "-t", "tmux-alpha", "C-z")),
            ("send_tab", {}, ("send-keys", "-t", "tmux-alpha", "Tab")),
            ("send_shift_tab", {"count": 3}, ("send-keys", "-t", "tmux-alpha", "-N", "3", "BTab")),
            ("send_backspace", {"count": 2}, ("send-keys", "-t", "tmux-alpha", "-N", "2", "BSpace")),
            ("send_enter", {}, ("send-keys", "-t", "tmux-alpha", "C-m")),
            ("send_arrow_key", {"direction": "left", "count": 4}, ("send-keys", "-t", "tmux-alpha", "-N", "4", "Left")),
        ],
    )
    async def test_helpers_send_expected_tmux_sequences(
        self,
        helper_name: str,
        kwargs: dict[str, int | str],
        expected_call: tuple[str, ...],
    ) -> None:
        helper = getattr(_keys, helper_name)
        process = _completed_process()

        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ) as mock_exec,
            patch("teleclaude.core.tmux_bridge._keys.wait_with_timeout", new=AsyncMock()) as mock_wait,
        ):
            result = await helper("tmux-alpha", **kwargs)

        assert result is True
        assert mock_exec.await_args.args == (_keys.config.computer.tmux_binary, *expected_call)
        mock_wait.assert_awaited_once_with(process, _keys.SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_repeat_helpers_reject_non_positive_counts(self) -> None:
        with patch("teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            shift_tab = await _keys.send_shift_tab("tmux-alpha", count=0)
            backspace = await _keys.send_backspace("tmux-alpha", count=0)
            arrow = await _keys.send_arrow_key("tmux-alpha", "up", count=0)

        assert shift_tab is False
        assert backspace is False
        assert arrow is False
        mock_exec.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_arrow_key_rejects_unknown_direction(self) -> None:
        with patch("teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            result = await _keys.send_arrow_key("tmux-alpha", "north")

        assert result is False
        mock_exec.assert_not_awaited()
