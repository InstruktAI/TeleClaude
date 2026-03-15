"""Characterization tests for tmux bridge pane operations."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.tmux_bridge import _pane


def _completed_process(*, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode)


class TestPaneIdentityLookups:
    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("stdout", "expected"),
        [(b"/dev/ttys001\n", "/dev/ttys001"), (b"?\n", None), (b"??\n", None)],
    )
    async def test_get_pane_tty_maps_tmux_output_to_optional_path(self, stdout: bytes, expected: str | None) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process()),
            ) as mock_exec,
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(return_value=(stdout, b"")),
            ),
        ):
            result = await _pane.get_pane_tty("tmux-alpha")

        assert result == expected
        assert mock_exec.await_args.args == (
            _pane.config.computer.tmux_binary,
            "display-message",
            "-p",
            "-t",
            "tmux-alpha",
            "#{pane_tty}",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("stdout", "expected"), [(b"42\n", 42), (b"shell\n", None)])
    async def test_get_pane_pid_only_accepts_digit_output(self, stdout: bytes, expected: int | None) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process()),
            ),
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(return_value=(stdout, b"")),
            ),
        ):
            result = await _pane.get_pane_pid("tmux-alpha")

        assert result == expected


class TestCaptureAndSessionListing:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_capture_pane_uses_default_window_when_capture_lines_are_non_positive(self) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process()),
            ) as mock_exec,
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(return_value=(b"pane-output-\xff", b"")),
            ),
        ):
            result = await _pane.capture_pane("tmux-alpha", capture_lines=0)

        assert result == "pane-output-\ufffd"
        assert mock_exec.await_args.args == (
            _pane.config.computer.tmux_binary,
            "capture-pane",
            "-t",
            "tmux-alpha",
            "-p",
            "-J",
            "-e",
            "-S",
            f"-{_pane.UI_MESSAGE_MAX_CHARS}",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_capture_pane_returns_empty_string_when_tmux_reports_failure(self) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process(returncode=1)),
            ),
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(return_value=(b"", b"missing pane")),
            ),
        ):
            result = await _pane.capture_pane("tmux-alpha", capture_lines=25)

        assert result == ""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_kill_session_returns_true_for_zero_exit(self) -> None:
        process = _completed_process()

        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ) as mock_exec,
            patch("teleclaude.core.tmux_bridge._pane.wait_with_timeout", new=AsyncMock()) as mock_wait,
        ):
            result = await _pane.kill_session("tmux-alpha")

        assert result is True
        assert mock_exec.await_args.args == (_pane.config.computer.tmux_binary, "kill-session", "-t", "tmux-alpha")
        mock_wait.assert_awaited_once_with(process, _pane.SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_tmux_sessions_filters_blank_lines(self) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process()),
            ),
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(return_value=(b"alpha\n\nbeta\n", b"")),
            ),
        ):
            result = await _pane.list_tmux_sessions()

        assert result == ["alpha", "beta"]


class TestSessionExistence:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_session_exists_returns_false_without_diagnostics_when_logging_disabled(self) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process(returncode=1)),
            ) as mock_exec,
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(return_value=(b"", b"no session")),
            ),
        ):
            result = await _pane.session_exists("tmux-alpha", log_missing=False)

        assert result is False
        assert mock_exec.await_count == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_session_exists_collects_diagnostics_for_missing_sessions(self) -> None:
        diag_result = (
            [{"pid": 101, "create_time": 123.4}],
            SimpleNamespace(used=9 * 1024 * 1024, percent=37.5),
            12.5,
        )

        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=[_completed_process(returncode=1), _completed_process()]),
            ) as mock_exec,
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(side_effect=[(b"", b"missing"), (b"alpha\nbeta\n", b"")]),
            ),
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.to_thread",
                new=AsyncMock(return_value=diag_result),
            ) as mock_to_thread,
        ):
            result = await _pane.session_exists("tmux-alpha")

        assert result is False
        assert mock_exec.await_count == 2
        mock_to_thread.assert_awaited_once()


class TestForegroundCommandTracking:
    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("returncode", "stdout", "expected"),
        [(0, b"vim\n", "vim"), (1, b"", None)],
    )
    async def test_get_current_command_reflects_tmux_foreground_command(
        self, returncode: int, stdout: bytes, expected: str | None
    ) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process(returncode=returncode)),
            ),
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(return_value=(stdout, b"stderr")),
            ),
        ):
            result = await _pane.get_current_command("tmux-alpha")

        assert result == expected

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_wait_for_shell_ready_polls_until_shell_command_reappears(self) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.get_current_command", new=AsyncMock(side_effect=["vim", "zsh"])
            ) as mock_current,
            patch("teleclaude.core.tmux_bridge._pane.asyncio.sleep", new=AsyncMock()) as mock_sleep,
            patch.object(_pane, "_SHELL_NAME", "zsh"),
        ):
            result = await _pane.wait_for_shell_ready("tmux-alpha", timeout_s=1.0, poll_interval_s=0.1)

        assert result is True
        assert mock_current.await_count == 2
        mock_sleep.assert_awaited_once_with(0.1)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_wait_for_shell_ready_returns_false_after_timeout(self) -> None:
        with (
            patch("teleclaude.core.tmux_bridge._pane.get_current_command", new=AsyncMock(return_value="vim")),
            patch("teleclaude.core.tmux_bridge._pane.asyncio.sleep", new=AsyncMock()) as mock_sleep,
            patch("teleclaude.core.tmux_bridge._pane.time.monotonic", side_effect=[0.0, 0.0, 0.3]),
            patch.object(_pane, "_SHELL_NAME", "zsh"),
        ):
            result = await _pane.wait_for_shell_ready("tmux-alpha", timeout_s=0.2, poll_interval_s=0.05)

        assert result is False
        mock_sleep.assert_awaited_once_with(0.05)

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("current", "expected"), [(None, False), ("zsh", False), ("vim", True)])
    async def test_is_process_running_treats_shell_as_idle(self, current: str | None, expected: bool) -> None:
        with (
            patch("teleclaude.core.tmux_bridge._pane.get_current_command", new=AsyncMock(return_value=current)),
            patch.object(_pane, "_SHELL_NAME", "zsh"),
        ):
            result = await _pane.is_process_running("tmux-alpha")

        assert result is expected


class TestPaneStateAndPiping:
    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("stdout", "expected"),
        [(b"1\n1\n", True), (b"1\n0\n", False), (b"", False)],
    )
    async def test_is_pane_dead_requires_every_reported_pane_to_be_dead(self, stdout: bytes, expected: bool) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process()),
            ),
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(return_value=(stdout, b"")),
            ),
        ):
            result = await _pane.is_pane_dead("tmux-alpha")

        assert result is expected

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("stdout", "expected"), [(b"%1\n", "%1"), (b"", None)])
    async def test_get_session_pane_id_returns_none_for_empty_output(self, stdout: bytes, expected: str | None) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process()),
            ),
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(return_value=(stdout, b"")),
            ),
        ):
            result = await _pane.get_session_pane_id("tmux-alpha")

        assert result == expected

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("helper_name", "helper_args", "expected_call"),
        [
            ("start_pipe_pane", ("printf ready",), ("pipe-pane", "-t", "tmux-alpha", "-o", "printf ready")),
            ("stop_pipe_pane", (), ("pipe-pane", "-t", "tmux-alpha")),
        ],
    )
    async def test_pipe_helpers_forward_tmux_pipe_commands(
        self, helper_name: str, helper_args: tuple[str, ...], expected_call: tuple[str, ...]
    ) -> None:
        helper = getattr(_pane, helper_name)
        process = _completed_process()

        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ) as mock_exec,
            patch("teleclaude.core.tmux_bridge._pane.wait_with_timeout", new=AsyncMock()) as mock_wait,
        ):
            result = await helper("tmux-alpha", *helper_args)

        assert result is True
        assert mock_exec.await_args.args == (_pane.config.computer.tmux_binary, *expected_call)
        mock_wait.assert_awaited_once_with(process, _pane.SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_pane_title_strips_tmux_output(self) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process()),
            ),
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(return_value=(b"Agent Pane\n", b"")),
            ),
        ):
            result = await _pane.get_pane_title("tmux-alpha")

        assert result == "Agent Pane"

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("returncode", "stdout", "expected"), [(0, b"/tmp/work\n", "/tmp/work"), (1, b"", None)])
    async def test_get_current_directory_returns_none_on_tmux_error(
        self, returncode: int, stdout: bytes, expected: str | None
    ) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._pane.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process(returncode=returncode)),
            ),
            patch(
                "teleclaude.core.tmux_bridge._pane.communicate_with_timeout",
                new=AsyncMock(return_value=(stdout, b"missing path")),
            ),
        ):
            result = await _pane.get_current_directory("tmux-alpha")

        assert result == expected
