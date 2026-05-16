"""Characterization tests for TeleClaude runtime environment resolution."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from teleclaude.runtime.environment import (
    compose_runtime_path,
    resolve_runtime_environment,
    resolve_user_shell,
)


def test_compose_runtime_path_prepends_teleclaude_bin_and_dedupes_existing_entry(tmp_path: Path) -> None:
    teleclaude_bin = tmp_path / "tc" / "bin"
    user_bin = tmp_path / "user-bin"
    path_value = os.pathsep.join([str(user_bin), str(teleclaude_bin), str(user_bin)])

    result = compose_runtime_path(path_value, teleclaude_bin=teleclaude_bin)

    assert [Path(entry) for entry in result.split(os.pathsep)] == [teleclaude_bin, user_bin]


def test_resolve_user_shell_prefers_process_shell_when_it_is_not_the_wrapper(tmp_path: Path) -> None:
    user_shell = tmp_path / "shells" / "preferred-shell"

    resolved = resolve_user_shell({"SHELL": str(user_shell)})

    assert resolved == str(user_shell)


def test_resolve_user_shell_uses_account_shell_when_process_shell_is_the_wrapper(tmp_path: Path) -> None:
    teleclaude_shell = tmp_path / "tc" / "bin" / "teleclaude-shell"
    account_shell = tmp_path / "shells" / "account-shell"

    with patch("teleclaude.runtime.environment._account_shell", return_value=str(account_shell)):
        resolved = resolve_user_shell({"SHELL": str(teleclaude_shell)})

    assert resolved == str(account_shell)


def test_resolve_runtime_environment_captures_path_from_the_resolved_user_shell(tmp_path: Path) -> None:
    user_shell = tmp_path / "shells" / "preferred-shell"
    user_bin = tmp_path / "user-bin"
    daemon_bin = tmp_path / "daemon-bin"
    captured_path = os.pathsep.join([str(user_bin), str(daemon_bin)])

    with patch(
        "teleclaude.runtime.environment.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout=captured_path, stderr=""),
    ) as run:
        resolved = resolve_runtime_environment(
            {
                "PATH": str(daemon_bin),
                "SHELL": str(user_shell),
                "ZDOTDIR": str(tmp_path / "tc-shell"),
                "BASH_ENV": str(tmp_path / "tc-shell" / ".bashenv"),
                "ENV": str(tmp_path / "tc-shell" / ".profile"),
                "TELECLAUDE_HOST_SHELL": str(tmp_path / "wrapper-target"),
            }
        )

    assert run.call_args.args[0] == [str(user_shell), "-lic", 'printf %s "$PATH"']
    capture_env = run.call_args.kwargs["env"]
    assert "ZDOTDIR" not in capture_env
    assert "BASH_ENV" not in capture_env
    assert "ENV" not in capture_env
    assert "TELECLAUDE_HOST_SHELL" not in capture_env
    assert [Path(entry) for entry in resolved["PATH"].split(os.pathsep)] == [
        Path(os.environ["TELECLAUDE_HOME"]) / "bin",
        user_bin,
        daemon_bin,
    ]
    assert resolved["SHELL"] == str(user_shell)


def test_resolve_runtime_environment_falls_back_to_daemon_path_when_shell_capture_fails(tmp_path: Path) -> None:
    user_shell = tmp_path / "shells" / "preferred-shell"
    daemon_bin = tmp_path / "daemon-bin"

    with patch(
        "teleclaude.runtime.environment.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=[str(user_shell)], timeout=5),
    ):
        resolved = resolve_runtime_environment({"PATH": str(daemon_bin), "SHELL": str(user_shell)})

    assert [Path(entry) for entry in resolved["PATH"].split(os.pathsep)] == [
        Path(os.environ["TELECLAUDE_HOME"]) / "bin",
        daemon_bin,
    ]
    assert resolved["SHELL"] == str(user_shell)
