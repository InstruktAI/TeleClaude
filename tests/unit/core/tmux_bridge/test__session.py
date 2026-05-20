"""Characterization tests for tmux bridge session management."""

from __future__ import annotations

import hashlib
import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import teleclaude.paths as tc_paths
from teleclaude.core.tmux_bridge import _session


def _completed_process(*, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode)


def _extract_tmux_env(command: tuple[object, ...]) -> dict[str, str]:
    env_values: dict[str, str] = {}
    command_list = list(command)

    for index, token in enumerate(command_list):
        if token == "-e":
            assignment = str(command_list[index + 1])
            name, value = assignment.split("=", 1)
            env_values[name] = value

    return env_values


class TestSessionTmpDirHelpers:
    @pytest.mark.unit
    def test_safe_path_component_preserves_safe_values_and_hashes_unsafe_values(self) -> None:
        safe_value = "agent.session-01_ok"
        unsafe_value = "agent/session with spaces"

        assert _session._safe_path_component(safe_value) == safe_value
        assert (
            _session._safe_path_component(unsafe_value) == hashlib.sha256(unsafe_value.encode("utf-8")).hexdigest()[:32]
        )

    @pytest.mark.unit
    def test_prepare_session_tmp_dir_recreates_the_directory_and_records_session_id(self, tmp_path: Path) -> None:
        session_id = "agent/session with spaces"
        expected_name = _session._safe_path_component(session_id)
        stale_dir = tmp_path / expected_name
        stale_dir.mkdir(parents=True)
        (stale_dir / "stale.txt").write_text("old", encoding="utf-8")

        with patch.dict(
            "teleclaude.core.tmux_bridge._session.os.environ", {"TELECLAUDE_SESSION_TMPDIR_BASE": str(tmp_path)}
        ):
            session_tmp = _session._prepare_session_tmp_dir(session_id)

        assert session_tmp == stale_dir
        assert session_tmp.is_dir()
        assert not (session_tmp / "stale.txt").exists()
        assert not (session_tmp / "teleclaude_identity.json").exists()


class TestCreateAndEnsureSession:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_tmux_session_injects_env_overrides(self, tmp_path: Path) -> None:
        teleclaude_bin = str(tc_paths.BIN_DIR)
        shell_dir = str(tc_paths.SHELL_DIR)
        session_tmp = Path("/tmp/tmux-alpha")
        runtime_path = f"{teleclaude_bin}:{tmp_path / 'user-bin'}"
        host_shell = str(tmp_path / "user-shell")

        with (
            patch.dict(
                "teleclaude.core.tmux_bridge._session.os.environ",
                {"PATH": f"/usr/local/bin:{teleclaude_bin}:/usr/bin"},
                clear=False,
            ),
            patch("teleclaude.core.tmux_bridge._session._prepare_session_tmp_dir", return_value=session_tmp),
            patch(
                "teleclaude.core.tmux_bridge._session.resolve_runtime_environment",
                return_value={"PATH": runtime_path, "SHELL": host_shell},
            ),
            patch(
                "teleclaude.core.tmux_bridge._session.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=[_completed_process(), _completed_process()]),
            ) as mock_exec,
            patch(
                "teleclaude.core.tmux_bridge._session.communicate_with_timeout",
                new=AsyncMock(side_effect=[(b"", b""), (b"", b"")]),
            ),
        ):
            result = await _session._create_tmux_session(
                name="tmux-alpha",
                working_dir="/workspace/demo",
                session_id="sess-1",
                env_vars={"VOICE": "alloy"},
            )

        assert result is True
        new_session_command = mock_exec.await_args_list[0].args
        assert new_session_command[:6] == (
            _session.config.computer.tmux_binary,
            "new-session",
            "-d",
            "-s",
            "tmux-alpha",
            "-c",
        )
        assert new_session_command[6] == "/workspace/demo"

        env_values = _extract_tmux_env(new_session_command)
        assert env_values["VOICE"] == "alloy"
        assert env_values["ZSH_LAST_WORKING_DIRECTORY"] == "1"
        # PATH is resolved live from the user's shell at session creation and
        # injected here so the pane and every agent CLI see the same lookup path.
        assert env_values["PATH"] == runtime_path
        assert env_values["TELECLAUDE_HOST_SHELL"] == host_shell
        assert env_values["COLORTERM"] == "truecolor"
        assert env_values["TMPDIR"] == str(session_tmp)
        assert env_values["TMP"] == str(session_tmp)
        assert env_values["TEMP"] == str(session_tmp)
        # Deterministic shell environment: agents and their subshells land
        # in our minimal rc tree regardless of the user's preferred shell.
        assert env_values["SHELL"] == f"{teleclaude_bin}/teleclaude-shell"
        assert env_values["ZDOTDIR"] == shell_dir
        assert env_values["BASH_ENV"] == f"{shell_dir}/.bashenv"
        assert env_values["ENV"] == f"{shell_dir}/.profile"
        # TELECLAUDE_HOME injected so the wrapper + rc files resolve to
        # the same root the daemon is configured for; otherwise an
        # override-rooted daemon would have the wrapper reset paths back
        # to the default via its $HOME/.teleclaude fallback.
        assert env_values["TELECLAUDE_HOME"] == str(tc_paths.TELECLAUDE_HOME)
        pane_command_parts = shlex.split(str(new_session_command[-1]))
        assert f"PATH={runtime_path}" in pane_command_parts
        assert f"SHELL={teleclaude_bin}/teleclaude-shell" in pane_command_parts
        assert f"TELECLAUDE_HOST_SHELL={host_shell}" in pane_command_parts
        assert pane_command_parts[-2:] == ["exec", f"{teleclaude_bin}/teleclaude-shell"]

        assert mock_exec.await_args_list[1].args == (
            _session.config.computer.tmux_binary,
            "set-environment",
            "-t",
            "tmux-alpha",
            "-u",
            "NO_COLOR",
            ";",
            "run-shell",
            f"printf {_session._SETUP_STEP_NO_COLOR_DONE}",
            ";",
            "set-option",
            "-t",
            "tmux-alpha",
            "destroy-unattached",
            "off",
            ";",
            "run-shell",
            f"printf {_session._SETUP_STEP_DESTROY_DONE}",
            ";",
            "set-hook",
            "-t",
            "tmux-alpha",
            "client-detached",
            "run-shell true",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_tmux_session_returns_false_when_new_session_fails(self) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._session.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process(returncode=1)),
            ) as mock_exec,
            patch(
                "teleclaude.core.tmux_bridge._session.resolve_runtime_environment",
                return_value={"PATH": "/usr/bin", "SHELL": "/bin/zsh"},
            ),
            patch(
                "teleclaude.core.tmux_bridge._session.communicate_with_timeout",
                new=AsyncMock(return_value=(b"", b"duplicate session")),
            ),
        ):
            result = await _session._create_tmux_session(name="tmux-alpha", working_dir="/workspace/demo")

        assert result is False
        assert mock_exec.await_count == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ensure_tmux_session_returns_true_without_recreating_existing_sessions(self) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._session.session_exists", new=AsyncMock(return_value=True)
            ) as mock_exists,
            patch("teleclaude.core.tmux_bridge._session._create_tmux_session", new=AsyncMock()) as mock_create,
        ):
            result = await _session.ensure_tmux_session("tmux-alpha", working_dir="/workspace/demo")

        assert result is True
        mock_exists.assert_awaited_once_with("tmux-alpha", log_missing=False)
        mock_create.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ensure_tmux_session_rechecks_existence_after_failed_creation(self) -> None:
        with (
            patch(
                "teleclaude.core.tmux_bridge._session.session_exists",
                new=AsyncMock(side_effect=[False, True]),
            ) as mock_exists,
            patch(
                "teleclaude.core.tmux_bridge._session._create_tmux_session",
                new=AsyncMock(return_value=False),
            ) as mock_create,
        ):
            result = await _session.ensure_tmux_session(
                "tmux-alpha",
                working_dir="/workspace/demo",
                session_id="sess-1",
                env_vars={"VOICE": "alloy"},
            )

        assert result is True
        assert mock_exists.await_args_list[0].args == ("tmux-alpha",)
        assert mock_exists.await_args_list[0].kwargs == {"log_missing": False}
        assert mock_exists.await_args_list[1].args == ("tmux-alpha",)
        assert mock_exists.await_args_list[1].kwargs == {"log_missing": False}
        mock_create.assert_awaited_once_with(
            name="tmux-alpha",
            working_dir="/workspace/demo",
            session_id="sess-1",
            env_vars={"VOICE": "alloy"},
        )


class TestCreateSessionChaining:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_tmux_session_chains_post_create_setup_commands(self) -> None:
        with (
            patch("teleclaude.core.tmux_bridge._session._prepare_session_tmp_dir", return_value=Path("/tmp/fake")),
            patch(
                "teleclaude.core.tmux_bridge._session.resolve_runtime_environment", return_value={"PATH": "/usr/bin"}
            ),
            patch(
                "teleclaude.core.tmux_bridge._session.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_completed_process()),
            ) as mock_exec,
            patch(
                "teleclaude.core.tmux_bridge._session.communicate_with_timeout",
                new=AsyncMock(return_value=(b"", b"")),
            ),
        ):
            await _session._create_tmux_session(
                name="tmux-alpha",
                working_dir="/workspace/demo",
                session_id="sess-1",
            )

        assert mock_exec.await_count == 2
        setup_argv = mock_exec.await_args_list[1].args
        assert "set-environment" in setup_argv
        assert "set-option" in setup_argv
        assert "set-hook" in setup_argv

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_tmux_session_logs_the_specific_setup_step_when_chain_fails(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with (
            patch("teleclaude.core.tmux_bridge._session._prepare_session_tmp_dir", return_value=Path("/tmp/fake")),
            patch(
                "teleclaude.core.tmux_bridge._session.resolve_runtime_environment", return_value={"PATH": "/usr/bin"}
            ),
            patch(
                "teleclaude.core.tmux_bridge._session.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=[_completed_process(), _completed_process(returncode=1)]),
            ),
            patch(
                "teleclaude.core.tmux_bridge._session.communicate_with_timeout",
                new=AsyncMock(side_effect=[(b"", b""), (_session._SETUP_STEP_NO_COLOR_DONE.encode(), b"readonly")]),
            ),
        ):
            with caplog.at_level("WARNING"):
                result = await _session._create_tmux_session(
                    name="tmux-alpha",
                    working_dir="/workspace/demo",
                    session_id="sess-1",
                )

        assert result is True
        assert "set-option destroy-unattached off" in caplog.text


class TestUpdateSessionEnvironment:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_tmux_session_sets_each_env_var_until_a_failure_occurs(self) -> None:
        env_vars = {"VOICE": "alloy", "MODE": "interactive"}

        with (
            patch(
                "teleclaude.core.tmux_bridge._session.asyncio.create_subprocess_exec",
                new=AsyncMock(side_effect=[_completed_process(), _completed_process(returncode=1)]),
            ) as mock_exec,
            patch(
                "teleclaude.core.tmux_bridge._session.communicate_with_timeout",
                new=AsyncMock(side_effect=[(b"", b""), (b"", b"readonly")]),
            ),
        ):
            result = await _session.update_tmux_session("tmux-alpha", env_vars)

        assert result is False
        assert mock_exec.await_args_list[0].args == (
            _session.config.computer.tmux_binary,
            "setenv",
            "-t",
            "tmux-alpha",
            "VOICE",
            "alloy",
        )
        assert mock_exec.await_args_list[1].args == (
            _session.config.computer.tmux_binary,
            "setenv",
            "-t",
            "tmux-alpha",
            "MODE",
            "interactive",
        )
