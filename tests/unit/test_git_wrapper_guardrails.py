"""Guardrail tests for the git wrapper installed in agent sessions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _write_fake_git(bin_dir: Path) -> Path:
    script = bin_dir / "git"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'echo "REAL_GIT_CALLED $*"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _write_logging_git(bin_dir: Path, label: str, exit_code: int) -> Path:
    script = bin_dir / "git"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ -n "${FAKE_GIT_CALLS_FILE:-}" ]; then\n'
        f'  echo "{label} $*" >> "${{FAKE_GIT_CALLS_FILE}}"\n'
        "fi\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _render_git_wrapper(tmp_path: Path) -> Path:
    template = (Path(__file__).resolve().parents[2] / "teleclaude" / "install" / "wrappers" / "git").read_text(
        encoding="utf-8"
    )
    wrapper = tmp_path / "wrapper-bin" / "git"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(template, encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def _base_env(tmp_path: Path, wrapper_dir: Path, fake_bin: Path) -> dict[str, str]:
    env: dict[str, str] = {
        "HOME": str(tmp_path),
        "PATH": f"{wrapper_dir}:{fake_bin}:/usr/bin:/bin",
    }
    for key in ("TMPDIR", "LANG", "LC_ALL", "TERM"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


@pytest.mark.timeout(5)
@pytest.mark.parametrize(
    "subcmd,error_fragment",
    [
        (["stash"], "'git stash' is prohibited"),
        (["checkout"], "'git checkout' is prohibited"),
        (["restore"], "'git restore' is prohibited"),
        (["clean"], "'git clean' is prohibited"),
        (["reset", "--hard"], "'git reset --hard' is prohibited"),
        (["reset", "--merge"], "'git reset --merge' is prohibited"),
        (["reset", "--keep"], "'git reset --keep' is prohibited"),
    ],
)
def test_destructive_subcommands_blocked(tmp_path: Path, subcmd: list[str], error_fragment: str) -> None:
    wrapper = _render_git_wrapper(tmp_path)
    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)

    env = _base_env(tmp_path, wrapper.parent, fake_bin)
    result = subprocess.run(
        [str(wrapper), *subcmd],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert error_fragment in result.stderr


@pytest.mark.timeout(5)
def test_revert_blocked_without_confirmed(tmp_path: Path) -> None:
    wrapper = _render_git_wrapper(tmp_path)
    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)

    env = _base_env(tmp_path, wrapper.parent, fake_bin)
    result = subprocess.run(
        [str(wrapper), "revert", "abc123"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "inspection required" in result.stderr


@pytest.mark.timeout(5)
def test_revert_allowed_with_confirmed(tmp_path: Path) -> None:
    wrapper = _render_git_wrapper(tmp_path)
    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)

    env = _base_env(tmp_path, wrapper.parent, fake_bin)
    result = subprocess.run(
        [str(wrapper), "revert", "--confirmed", "abc123"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    # --confirmed should be stripped before passing to real git
    assert "REAL_GIT_CALLED revert abc123" in result.stdout
    assert "--confirmed" not in result.stdout


@pytest.mark.timeout(5)
def test_safe_reset_allowed(tmp_path: Path) -> None:
    wrapper = _render_git_wrapper(tmp_path)
    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)

    env = _base_env(tmp_path, wrapper.parent, fake_bin)
    result = subprocess.run(
        [str(wrapper), "reset", "HEAD~1"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "REAL_GIT_CALLED reset HEAD~1" in result.stdout


@pytest.mark.timeout(5)
def test_push_passes_through(tmp_path: Path) -> None:
    """Push is no longer guarded by the wrapper — the pre-push hook handles it."""
    wrapper = _render_git_wrapper(tmp_path)
    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)

    env = _base_env(tmp_path, wrapper.parent, fake_bin)
    result = subprocess.run(
        [str(wrapper), "push", "origin", "main"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "REAL_GIT_CALLED push origin main" in result.stdout


@pytest.mark.timeout(5)
def test_preserves_first_real_binary_failure(tmp_path: Path) -> None:
    wrapper = _render_git_wrapper(tmp_path)
    first_bin = tmp_path / "real-bin-1"
    second_bin = tmp_path / "real-bin-2"
    first_bin.mkdir(parents=True, exist_ok=True)
    second_bin.mkdir(parents=True, exist_ok=True)
    _write_logging_git(first_bin, "BIN1", 23)
    _write_logging_git(second_bin, "BIN2", 0)
    calls_file = tmp_path / "git-calls.log"

    env: dict[str, str] = {
        "HOME": str(tmp_path),
        "PATH": f"{wrapper.parent}:{first_bin}:{second_bin}:/usr/bin:/bin",
        "FAKE_GIT_CALLS_FILE": str(calls_file),
    }
    for key in ("TMPDIR", "LANG", "LC_ALL", "TERM"):
        if key in os.environ:
            env[key] = os.environ[key]

    result = subprocess.run(
        [str(wrapper), "status"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 23
    assert calls_file.read_text(encoding="utf-8").splitlines() == ["BIN1 status"]
