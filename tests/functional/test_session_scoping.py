"""Functional tests for the shared session-scoping subsystem."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import teleclaude.session_scoping._store as store_module
from teleclaude.session_scoping import resolve_scoped_paths


def _run_git(args: list[str], cwd: Path) -> None:
    from teleclaude.git import _find_real_git  # pylint: disable=import-outside-toplevel

    subprocess.run([_find_real_git(), *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_git_worktree_turn_delta_uses_real_git_state_and_persisted_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(store_module, "SESSION_SCOPING_DIR", tmp_path / "state")

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _run_git(["init", "-q", "-b", "main"], repo_root)
    _run_git(["config", "user.email", "test@example.com"], repo_root)
    _run_git(["config", "user.name", "Test User"], repo_root)

    tracked = repo_root / "src" / "app.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("print('base')\n", encoding="utf-8")
    _run_git(["add", "src/app.py"], repo_root)
    _run_git(["commit", "-qm", "base"], repo_root)

    worktree_root = tmp_path / "trees" / "feature-a"
    _run_git(["worktree", "add", str(worktree_root), "-b", "feature-a"], repo_root)

    (worktree_root / "src" / "app.py").write_text("print('changed')\n", encoding="utf-8")
    (worktree_root / "docs").mkdir()
    (worktree_root / "docs" / "guide.md").write_text("docs\n", encoding="utf-8")

    first = resolve_scoped_paths(
        session_id="session-1",
        workspace_root=str(worktree_root),
        agent_name="codex",
        scope_mode="turn_delta",
    )
    second = resolve_scoped_paths(
        session_id="session-1",
        workspace_root=str(worktree_root),
        agent_name="codex",
        scope_mode="turn_delta",
    )

    assert first.workspace_kind == "git_worktree"
    assert set(first.paths) == {"docs/guide.md", "src/app.py"}
    assert first.ledger_updated is True
    assert not second.paths
    assert second.ledger_updated is False
