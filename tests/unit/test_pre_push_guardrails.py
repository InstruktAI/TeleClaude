"""Guardrail tests for the tracked .githooks/pre-push script."""

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


def _base_env(tmp_path: Path, fake_bin: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"
    env["TELECLAUDE_SESSION_ID"] = "sess-789"
    return env


@pytest.mark.timeout(5)
def test_pre_push_blocks_main_target_from_worktree(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repo"
    worktree = canonical_root / "trees" / "slug"
    (canonical_root / ".git").mkdir(parents=True, exist_ok=True)
    worktree.mkdir(parents=True, exist_ok=True)

    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)

    hook = Path(__file__).resolve().parents[2] / ".githooks" / "pre-push"
    env = _base_env(tmp_path, fake_bin)
    env["FAKE_GIT_COMMON_DIR"] = str(canonical_root / ".git")
    env["FAKE_GIT_TOPLEVEL"] = str(worktree)
    env["FAKE_GIT_BRANCH"] = "feature"
    env["FAKE_GIT_DIR"] = str(canonical_root / ".git" / "worktrees" / "slug")

    result = subprocess.run(
        [str(hook), "origin", "git@example.com/repo.git"],
        input="refs/heads/feature 111 refs/heads/main 222\n",
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "MAIN_GUARDRAIL_BLOCKED" in result.stderr
    assert "GUARDRAIL_MARKER" in result.stderr


@pytest.mark.timeout(5)
def test_pre_push_allows_feature_target_from_worktree(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repo"
    worktree = canonical_root / "trees" / "slug"
    (canonical_root / ".git").mkdir(parents=True, exist_ok=True)
    worktree.mkdir(parents=True, exist_ok=True)

    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)

    hook = Path(__file__).resolve().parents[2] / ".githooks" / "pre-push"
    env = _base_env(tmp_path, fake_bin)
    env["FAKE_GIT_COMMON_DIR"] = str(canonical_root / ".git")
    env["FAKE_GIT_TOPLEVEL"] = str(worktree)
    env["FAKE_GIT_BRANCH"] = "feature"
    env["FAKE_GIT_DIR"] = str(canonical_root / ".git" / "worktrees" / "slug")

    result = subprocess.run(
        [str(hook), "origin", "git@example.com/repo.git"],
        input="refs/heads/feature 111 refs/heads/feature 222\n",
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0


@pytest.mark.timeout(5)
def test_pre_push_allows_main_target_from_canonical_main(tmp_path: Path) -> None:
    canonical_root = tmp_path / "repo"
    (canonical_root / ".git").mkdir(parents=True, exist_ok=True)

    fake_bin = tmp_path / "real-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_fake_git(fake_bin)

    hook = Path(__file__).resolve().parents[2] / ".githooks" / "pre-push"
    env = _base_env(tmp_path, fake_bin)
    env["FAKE_GIT_COMMON_DIR"] = str(canonical_root / ".git")
    env["FAKE_GIT_TOPLEVEL"] = str(canonical_root)
    env["FAKE_GIT_BRANCH"] = "main"
    env["FAKE_GIT_DIR"] = str(canonical_root / ".git")

    result = subprocess.run(
        [str(hook), "origin", "git@example.com/repo.git"],
        input="refs/heads/main 111 refs/heads/main 222\n",
        cwd=canonical_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
