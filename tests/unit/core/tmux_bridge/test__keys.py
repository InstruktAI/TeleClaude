"""Characterization tests for tmux bridge key dispatch."""

from __future__ import annotations

from signal import SIGHUP, SIGINT, SIGKILL, SIGTERM
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.core.tmux_bridge import _keys
from teleclaude.core.tmux_bridge._subprocess import SubprocessTimeoutError


def _completed_process(*, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode)


class TestPidIsAlive:
    @pytest.mark.unit
    def test_kill_probe_succeeds_returns_true(self) -> None:
        with patch("teleclaude.core.tmux_bridge._keys.os.kill"):
            assert _keys.pid_is_alive(321) is True

    @pytest.mark.unit
    def test_kill_probe_permission_error_returns_true(self) -> None:
        # PermissionError means the pid exists but we don't own it — still alive.
        with patch("teleclaude.core.tmux_bridge._keys.os.kill", side_effect=PermissionError()):
            assert _keys.pid_is_alive(321) is True

    @pytest.mark.unit
    def test_kill_probe_oserror_returns_false(self) -> None:
        # OSError (typically ESRCH) means the pid is gone.
        with patch("teleclaude.core.tmux_bridge._keys.os.kill", side_effect=OSError()):
            assert _keys.pid_is_alive(321) is False


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
                active_agent="claude",
            )

        assert result is True
        mock_ensure.assert_awaited_once_with(name="tmux-alpha", working_dir="/tmp/demo", session_id="sess-1")
        mock_send.assert_awaited_once_with(
            session_name="tmux-alpha",
            text="echo hi",
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
    async def test_send_keys_existing_tmux_returns_false_on_subprocess_timeout(self) -> None:
        with patch(
            "teleclaude.core.tmux_bridge._keys._send_keys_tmux",
            new=AsyncMock(side_effect=SubprocessTimeoutError("tmux operation", 15.0, 1234)),
        ):
            result = await _keys.send_keys_existing_tmux(session_name="tmux-alpha", text="hi", timeout=15.0)

        assert result is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_existing_tmux_propagates_custom_timeout(self) -> None:
        # Buffer pipeline: load-buffer, paste-buffer, delete-buffer, submit (C-m).
        processes = [_completed_process() for _ in range(4)]
        communicate_mock = AsyncMock(side_effect=[(b"", b"")] * 4)

        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=processes),
            ),
            patch("teleclaude.core.tmux_bridge._keys.communicate_with_timeout", new=communicate_mock),
            patch("teleclaude.core.tmux_bridge._keys.asyncio.sleep", new=AsyncMock()),
        ):
            result = await _keys.send_keys_existing_tmux(
                session_name="tmux-alpha",
                text="hello",
                timeout=15.0,
            )

        assert result is True
        for call in communicate_mock.await_args_list:
            assert call.args[2] == 15.0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_existing_tmux_uses_buffer_pipeline(self) -> None:
        # The buffer pipeline must:
        # 1. send the payload via load-buffer stdin (NO trailing \r —
        #    agent CLIs don't treat \r inside a paste burst as discrete Enter)
        # 2. paste-buffer -p -r (emit DECSET 2004 markers conditional on app
        #    request; preserve LF instead of rewriting to CR)
        # 3. delete the buffer
        # 4. discrete send-keys C-m AFTER the fixed _SUBMIT_GAP_S
        processes = [_completed_process() for _ in range(4)]
        communicate_mock = AsyncMock(side_effect=[(b"", b"")] * 4)

        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=processes),
            ) as mock_exec,
            patch("teleclaude.core.tmux_bridge._keys.communicate_with_timeout", new=communicate_mock),
            patch("teleclaude.core.tmux_bridge._keys.asyncio.sleep", new=AsyncMock()),
        ):
            result = await _keys.send_keys_existing_tmux(
                session_name="tmux-alpha",
                text="run!",
                active_agent=AgentName.GEMINI.value,
            )

        assert result is True
        assert mock_exec.await_count == 4
        binary = _keys.config.computer.tmux_binary

        load_args = mock_exec.await_args_list[0].args
        assert load_args[:3] == (binary, "load-buffer", "-b")
        buf_name = load_args[3]
        assert buf_name.startswith("telec-")
        assert load_args[4] == "-"

        # Stdin to load-buffer is the bang-escaped payload — no trailing \r.
        # Communicate is called positionally with (proc, input_bytes, timeout, label).
        load_input = communicate_mock.await_args_list[0].args[1]
        assert load_input == rb"run\!"

        paste_args = mock_exec.await_args_list[1].args
        assert paste_args == (binary, "paste-buffer", "-p", "-r", "-t", "tmux-alpha", "-b", buf_name)

        delete_args = mock_exec.await_args_list[2].args
        assert delete_args == (binary, "delete-buffer", "-b", buf_name)

        submit_args = mock_exec.await_args_list[3].args
        assert submit_args == (binary, "send-keys", "-t", "tmux-alpha", "C-m")


class TestSendKeysSubmission:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_submit_uses_fixed_short_gap_regardless_of_size(self) -> None:
        # The submit gap is size-INDEPENDENT: it only covers tmux's flush of
        # the bracketed-paste close marker, which is the same regardless of
        # how much content preceded it. Both small and large payloads use
        # the same fixed _SUBMIT_GAP_S.
        sleep_mock = AsyncMock()
        processes = [_completed_process() for _ in range(4)]
        communicate_mock = AsyncMock(side_effect=[(b"", b"")] * 4)

        big_payload = "x" * 100_000  # 100 KB
        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=processes),
            ),
            patch("teleclaude.core.tmux_bridge._keys.communicate_with_timeout", new=communicate_mock),
            patch("teleclaude.core.tmux_bridge._keys.asyncio.sleep", new=sleep_mock),
        ):
            result = await _keys.send_keys_existing_tmux(
                session_name="tmux-alpha",
                text=big_payload,
            )
        assert result is True
        sleep_mock.assert_awaited_once()
        big_gap = sleep_mock.await_args.args[0]

        # Reset and run with a tiny payload — gap must be identical.
        sleep_mock = AsyncMock()
        processes = [_completed_process() for _ in range(4)]
        communicate_mock = AsyncMock(side_effect=[(b"", b"")] * 4)
        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=processes),
            ),
            patch("teleclaude.core.tmux_bridge._keys.communicate_with_timeout", new=communicate_mock),
            patch("teleclaude.core.tmux_bridge._keys.asyncio.sleep", new=sleep_mock),
        ):
            result = await _keys.send_keys_existing_tmux(
                session_name="tmux-alpha",
                text="ok",
            )
        assert result is True
        small_gap = sleep_mock.await_args.args[0]

        # Same fixed gap for any size. Matches the module constant.
        assert big_gap == small_gap == _keys._SUBMIT_GAP_S

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_paste_buffer_uses_dash_r_to_preserve_newlines(self) -> None:
        # Without -r, tmux rewrites every LF to CR, collapsing multiline bundles
        # into one carriage-returned line. paste-buffer must include -r so LFs
        # are preserved in the stream that hits the pane.
        multiline = "first line\nsecond line\nthird line"
        processes = [_completed_process() for _ in range(4)]
        communicate_mock = AsyncMock(side_effect=[(b"", b"")] * 4)

        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=processes),
            ) as mock_exec,
            patch("teleclaude.core.tmux_bridge._keys.communicate_with_timeout", new=communicate_mock),
            patch("teleclaude.core.tmux_bridge._keys.asyncio.sleep", new=AsyncMock()),
        ):
            result = await _keys.send_keys_existing_tmux(
                session_name="tmux-alpha",
                text=multiline,
            )

        assert result is True
        binary = _keys.config.computer.tmux_binary
        # Load-buffer stdin is the content with LFs intact (NO trailing \r).
        load_input = communicate_mock.await_args_list[0].args[1]
        assert load_input == multiline.encode()
        assert b"\n" in load_input
        # paste-buffer must include -r so tmux does NOT rewrite LF -> CR.
        paste_args = mock_exec.await_args_list[1].args
        assert paste_args == (binary, "paste-buffer", "-p", "-r", "-t", "tmux-alpha", "-b", paste_args[7])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_returns_false_when_load_buffer_fails(self) -> None:
        # If load-buffer fails, no paste/delete attempts are made.
        processes = [_completed_process(returncode=1)]
        communicate_mock = AsyncMock(side_effect=[(b"", b"load failed")])

        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=processes),
            ) as mock_exec,
            patch("teleclaude.core.tmux_bridge._keys.communicate_with_timeout", new=communicate_mock),
            patch("teleclaude.core.tmux_bridge._keys.asyncio.sleep", new=AsyncMock()),
        ):
            result = await _keys.send_keys_existing_tmux(
                session_name="tmux-alpha",
                text="hello",
            )

        assert result is False
        assert mock_exec.await_count == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_returns_true_when_delete_buffer_fails_after_successful_paste(self) -> None:
        # Cleanup failure after a successful paste must NOT override the
        # operation result. paste-buffer wrote the payload; submit still runs;
        # the leftover buffer is logged but not failed-back to the caller.
        processes = [
            _completed_process(),  # load-buffer
            _completed_process(),  # paste-buffer
            _completed_process(returncode=1),  # delete-buffer (fails)
            _completed_process(),  # submit C-m
        ]
        communicate_mock = AsyncMock(side_effect=[(b"", b""), (b"", b""), (b"", b"no such buffer"), (b"", b"")])

        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=processes),
            ) as mock_exec,
            patch("teleclaude.core.tmux_bridge._keys.communicate_with_timeout", new=communicate_mock),
            patch("teleclaude.core.tmux_bridge._keys.asyncio.sleep", new=AsyncMock()),
        ):
            result = await _keys.send_keys_existing_tmux(
                session_name="tmux-alpha",
                text="hello",
            )

        assert result is True
        assert mock_exec.await_count == 4
        # Submit ran after the cleanup failure.
        assert mock_exec.await_args_list[3].args[1] == "send-keys"
        assert mock_exec.await_args_list[3].args[-1] == "C-m"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_returns_true_when_delete_buffer_times_out_after_successful_paste(self) -> None:
        # Cleanup timeout must NOT override the operation result either. Same
        # invariant: paste-buffer wrote the payload, submit still runs.
        processes = [
            _completed_process(),  # load-buffer
            _completed_process(),  # paste-buffer
            _completed_process(),  # delete-buffer (times out via communicate)
            _completed_process(),  # submit C-m
        ]
        communicate_mock = AsyncMock(
            side_effect=[
                (b"", b""),  # load-buffer
                (b"", b""),  # paste-buffer
                SubprocessTimeoutError("tmux delete-buffer", 5.0, 1234),  # cleanup timeout
                (b"", b""),  # submit
            ]
        )

        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=processes),
            ) as mock_exec,
            patch("teleclaude.core.tmux_bridge._keys.communicate_with_timeout", new=communicate_mock),
            patch("teleclaude.core.tmux_bridge._keys.asyncio.sleep", new=AsyncMock()),
        ):
            result = await _keys.send_keys_existing_tmux(
                session_name="tmux-alpha",
                text="hello",
            )

        assert result is True
        assert mock_exec.await_count == 4
        assert mock_exec.await_args_list[3].args[1] == "send-keys"
        assert mock_exec.await_args_list[3].args[-1] == "C-m"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_runs_delete_buffer_cleanup_even_when_paste_buffer_fails(self) -> None:
        # The reviewer's contract: paste failure must NOT skip delete-buffer cleanup.
        # The buffer holds the user payload; leaving it in tmux is data retention.
        processes = [
            _completed_process(),  # load-buffer
            _completed_process(returncode=2),  # paste-buffer (fails)
            _completed_process(),  # delete-buffer (still runs)
        ]
        communicate_mock = AsyncMock(side_effect=[(b"", b""), (b"", b"paste failed"), (b"", b"")])

        with (
            patch(
                "teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=processes),
            ) as mock_exec,
            patch("teleclaude.core.tmux_bridge._keys.communicate_with_timeout", new=communicate_mock),
            patch("teleclaude.core.tmux_bridge._keys.asyncio.sleep", new=AsyncMock()),
        ):
            result = await _keys.send_keys_existing_tmux(
                session_name="tmux-alpha",
                text="hello",
            )

        # Operation result reflects the paste failure — submit is skipped.
        assert result is False
        assert mock_exec.await_count == 3
        binary = _keys.config.computer.tmux_binary
        # 3rd call is delete-buffer with the same buffer name as load.
        load_args = mock_exec.await_args_list[0].args
        buf_name = load_args[3]
        assert mock_exec.await_args_list[2].args == (binary, "delete-buffer", "-b", buf_name)


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
            result = await _keys.send_keys_to_tty("/dev/ptyp0", "status")

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
    async def test_sigint_maps_to_ctrl_c_via_send_keys(self) -> None:
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
            result = await _keys.send_signal("tmux-alpha", SIGINT)

        assert result is True
        assert mock_exec.await_args.args == (
            _keys.config.computer.tmux_binary,
            "send-keys",
            "-t",
            "tmux-alpha",
            "C-c",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_sigterm_maps_to_ctrl_backslash_via_send_keys(self) -> None:
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
            result = await _keys.send_signal("tmux-alpha", SIGTERM)

        assert result is True
        assert mock_exec.await_args.args == (
            _keys.config.computer.tmux_binary,
            "send-keys",
            "-t",
            "tmux-alpha",
            "C-\\",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unsupported_signal_returns_false_without_subprocesses(self) -> None:
        with patch("teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            result = await _keys.send_signal("tmux-alpha", SIGHUP)

        assert result is False
        mock_exec.assert_not_awaited()


class TestSpecialKeyHelpers:
    @staticmethod
    async def _run_helper(
        helper: object,
        kwargs: dict[str, object],  # guard: loose-dict - test scaffolding accepts varied helper kwargs
    ) -> tuple[bool, AsyncMock, AsyncMock, SimpleNamespace]:
        """Shared scaffolding: patch subprocess + wait, invoke the helper, return mocks."""
        process = _completed_process()
        mock_exec = AsyncMock(return_value=process)
        mock_wait = AsyncMock()
        with (
            patch("teleclaude.core.tmux_bridge._keys.asyncio.create_subprocess_exec", new=mock_exec),
            patch("teleclaude.core.tmux_bridge._keys.wait_with_timeout", new=mock_wait),
        ):
            assert callable(helper)
            result = await helper("tmux-alpha", **kwargs)
        return result, mock_exec, mock_wait, process

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_escape_emits_escape_key(self) -> None:
        result, mock_exec, mock_wait, process = await self._run_helper(_keys.send_escape, {})
        assert result is True
        assert mock_exec.await_args.args == (
            _keys.config.computer.tmux_binary,
            "send-keys",
            "-t",
            "tmux-alpha",
            "Escape",
        )
        mock_wait.assert_awaited_once_with(process, _keys.SUBPROCESS_TIMEOUT_QUICK, "tmux operation")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_ctrl_key_emits_lowercase_modifier_form(self) -> None:
        result, mock_exec, _, _ = await self._run_helper(_keys.send_ctrl_key, {"key": "Z"})
        assert result is True
        assert mock_exec.await_args.args == (_keys.config.computer.tmux_binary, "send-keys", "-t", "tmux-alpha", "C-z")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_tab_emits_tab_key(self) -> None:
        result, mock_exec, _, _ = await self._run_helper(_keys.send_tab, {})
        assert result is True
        assert mock_exec.await_args.args == (_keys.config.computer.tmux_binary, "send-keys", "-t", "tmux-alpha", "Tab")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_shift_tab_uses_repeat_count(self) -> None:
        result, mock_exec, _, _ = await self._run_helper(_keys.send_shift_tab, {"count": 3})
        assert result is True
        assert mock_exec.await_args.args == (
            _keys.config.computer.tmux_binary,
            "send-keys",
            "-t",
            "tmux-alpha",
            "-N",
            "3",
            "BTab",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_backspace_uses_repeat_count(self) -> None:
        result, mock_exec, _, _ = await self._run_helper(_keys.send_backspace, {"count": 2})
        assert result is True
        assert mock_exec.await_args.args == (
            _keys.config.computer.tmux_binary,
            "send-keys",
            "-t",
            "tmux-alpha",
            "-N",
            "2",
            "BSpace",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_enter_emits_carriage_return(self) -> None:
        result, mock_exec, _, _ = await self._run_helper(_keys.send_enter, {})
        assert result is True
        assert mock_exec.await_args.args == (_keys.config.computer.tmux_binary, "send-keys", "-t", "tmux-alpha", "C-m")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_arrow_key_left_uses_repeat_count(self) -> None:
        result, mock_exec, _, _ = await self._run_helper(_keys.send_arrow_key, {"direction": "left", "count": 4})
        assert result is True
        assert mock_exec.await_args.args == (
            _keys.config.computer.tmux_binary,
            "send-keys",
            "-t",
            "tmux-alpha",
            "-N",
            "4",
            "Left",
        )

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
