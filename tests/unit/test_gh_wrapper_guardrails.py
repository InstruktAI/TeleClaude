"""Guardrail tests for the gh wrapper installed in agent sessions."""

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
        'cmd="${1:-}"\n'
        'case "$cmd" in\n'
        "  rev-parse)\n"
        '    sub="${2:-}"\n'
        '    case "$sub" in\n'
        '      --git-common-dir) echo "${FAKE_GIT_COMMON_DIR:-.git}" ;;\n'
        '      --show-toplevel) echo "${FAKE_GIT_TOPLEVEL:-$PWD}" ;;\n'
        '      --abbrev-ref) echo "${FAKE_GIT_BRANCH:-main}" ;;\n'
        '      --git-dir) echo "${FAKE_GIT_DIR:-.git}" ;;\n'
        '      *) echo "${FAKE_GIT_TOPLEVEL:-$PWD}" ;;\n'
        "    esac\n"
        "    ;;\n"
        "  *)\n"
        '    echo "REAL_GIT_CALLED $*"\n'
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _write_fake_gh(bin_dir: Path) -> Path:
    script = bin_dir / "gh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ -n "${FAKE_GH_CALLS_FILE:-}" ]; then\n'
        '  echo "$*" >> "${FAKE_GH_CALLS_FILE}"\n'
        "fi\n"
        'if [ "${1:-}" = "pr" ] && [ "${2:-}" = "view" ]; then\n'
        '  echo "${FAKE_GH_BASE:-main}"\n'
        "  exit 0\n"
        "fi\n"
        'echo "REAL_GH_CALLED $*"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _write_logging_gh(bin_dir: Path, label: str, exit_code: int) -> Path:
    script = bin_dir / "gh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ -n "${FAKE_GH_CALLS_FILE:-}" ]; then\n'
        f'  echo "{label} $*" >> "${{FAKE_GH_CALLS_FILE}}"\n'
        "fi\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _render_gh_wrapper(tmp_path: Path, canonical_root: Path) -> Path:
    template = (Path(__file__).resolve().parents[2] / "teleclaude" / "install" / "wrappers" / "gh").read_text(
        encoding="utf-8"
    )
    wrapper = tmp_path / "wrapper-bin" / "gh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(template.replace("{{CANONICAL_ROOT}}", str(canonical_root)), encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def _base_env(tmp_path: Path, wrapper_dir: Path, fake_bin: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["PATH"] = f"{wrapper_dir}:{fake_bin}:/usr/bin:/bin"
    env["TELECLAUDE_SESSION_ID"] = "sess-456"
    return env


@pytest.mark.timeout(5)
def test_gh_wrapper_blocks_pr_merge_to_main_from_worktree(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repo"
    worktree = canonical_root / "trees" / "slug"
    (canonical_root / ".git").mkdir(parents=True, exist_ok=True)
    worktree.mkdir(parents=True, exist_ok=True)

    wrapper = _render_gh_wrapper(tmp_path, canonical_root)
    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)
    _write_fake_gh(fake_bin)

    env = _base_env(tmp_path, wrapper.parent, fake_bin)
    env["FAKE_GIT_COMMON_DIR"] = str(canonical_root / ".git")
    env["FAKE_GIT_TOPLEVEL"] = str(worktree)
    env["FAKE_GIT_BRANCH"] = "feature"
    env["FAKE_GIT_DIR"] = str(canonical_root / ".git" / "worktrees" / "slug")

    result = subprocess.run(
        [str(wrapper), "pr", "merge", "123", "--base", "main"],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "MAIN_GUARDRAIL_BLOCKED" in result.stderr
    assert "GUARDRAIL_MARKER" in result.stderr

    log_file = tmp_path / ".teleclaude" / "logs" / "guardrails.log"
    assert log_file.exists()
    log_text = log_file.read_text(encoding="utf-8")
    assert "TELECLAUDE_GH_MAIN_MERGE_GUARD_BLOCK" in log_text


@pytest.mark.timeout(5)
def test_gh_wrapper_allows_non_main_merge(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repo"
    worktree = canonical_root / "trees" / "slug"
    (canonical_root / ".git").mkdir(parents=True, exist_ok=True)
    worktree.mkdir(parents=True, exist_ok=True)

    wrapper = _render_gh_wrapper(tmp_path, canonical_root)
    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)
    _write_fake_gh(fake_bin)

    env = _base_env(tmp_path, wrapper.parent, fake_bin)
    env["FAKE_GIT_COMMON_DIR"] = str(canonical_root / ".git")
    env["FAKE_GIT_TOPLEVEL"] = str(worktree)
    env["FAKE_GIT_BRANCH"] = "feature"
    env["FAKE_GIT_DIR"] = str(canonical_root / ".git" / "worktrees" / "slug")

    result = subprocess.run(
        [str(wrapper), "pr", "merge", "123", "--base", "release"],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "REAL_GH_CALLED pr merge 123 --base release" in result.stdout


@pytest.mark.timeout(5)
def test_gh_wrapper_non_merge_command_executes_once(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repo"
    worktree = canonical_root / "trees" / "slug"
    (canonical_root / ".git").mkdir(parents=True, exist_ok=True)
    worktree.mkdir(parents=True, exist_ok=True)

    wrapper = _render_gh_wrapper(tmp_path, canonical_root)
    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)
    _write_fake_gh(fake_bin)
    calls_file = tmp_path / "gh-calls.log"

    env = _base_env(tmp_path, wrapper.parent, fake_bin)
    env["FAKE_GIT_COMMON_DIR"] = str(canonical_root / ".git")
    env["FAKE_GIT_TOPLEVEL"] = str(worktree)
    env["FAKE_GIT_BRANCH"] = "feature"
    env["FAKE_GIT_DIR"] = str(canonical_root / ".git" / "worktrees" / "slug")
    env["FAKE_GH_CALLS_FILE"] = str(calls_file)

    result = subprocess.run(
        [str(wrapper), "auth", "status"],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.count("REAL_GH_CALLED auth status") == 1
    assert calls_file.read_text(encoding="utf-8").splitlines() == ["auth status"]


@pytest.mark.timeout(5)
def test_gh_wrapper_allows_main_merge_from_canonical_main(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repo"
    (canonical_root / ".git").mkdir(parents=True, exist_ok=True)

    wrapper = _render_gh_wrapper(tmp_path, canonical_root)
    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)
    _write_fake_gh(fake_bin)

    env = _base_env(tmp_path, wrapper.parent, fake_bin)
    env["FAKE_GIT_COMMON_DIR"] = str(canonical_root / ".git")
    env["FAKE_GIT_TOPLEVEL"] = str(canonical_root)
    env["FAKE_GIT_BRANCH"] = "main"
    env["FAKE_GIT_DIR"] = str(canonical_root / ".git")

    result = subprocess.run(
        [str(wrapper), "pr", "merge", "123", "--base", "main"],
        cwd=canonical_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "REAL_GH_CALLED pr merge 123 --base main" in result.stdout


@pytest.mark.timeout(5)
def test_gh_wrapper_preserves_first_real_binary_failure(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repo"
    worktree = canonical_root / "trees" / "slug"
    (canonical_root / ".git").mkdir(parents=True, exist_ok=True)
    worktree.mkdir(parents=True, exist_ok=True)

    wrapper = _render_gh_wrapper(tmp_path, canonical_root)
    first_bin = tmp_path / "real-bin-1"
    second_bin = tmp_path / "real-bin-2"
    first_bin.mkdir(parents=True, exist_ok=True)
    second_bin.mkdir(parents=True, exist_ok=True)
    _write_logging_gh(first_bin, "GH1", 19)
    _write_logging_gh(second_bin, "GH2", 0)
    calls_file = tmp_path / "gh-calls.log"

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["PATH"] = f"{wrapper.parent}:{first_bin}:{second_bin}:/usr/bin:/bin"
    env["TELECLAUDE_SESSION_ID"] = "sess-456"
    env["FAKE_GH_CALLS_FILE"] = str(calls_file)

    result = subprocess.run(
        [str(wrapper), "auth", "status"],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 19
    assert calls_file.read_text(encoding="utf-8").splitlines() == ["GH1 auth status"]
