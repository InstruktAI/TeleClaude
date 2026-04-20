"""Tests for canonical project-root resolution."""

from __future__ import annotations

from pathlib import Path

from teleclaude.project_root import resolve_main_repo_root


def test_resolve_main_repo_root_follows_worktree_gitdir(tmp_path: Path) -> None:
    repo_root = tmp_path / "main"
    worktree = tmp_path / "trees" / "sample"
    gitdir = repo_root / ".git" / "worktrees" / "sample"
    gitdir.mkdir(parents=True)
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

    assert resolve_main_repo_root(worktree) == repo_root


def test_resolve_main_repo_root_returns_requested_path_without_git_metadata(tmp_path: Path) -> None:
    cwd = tmp_path / "plain-dir"
    cwd.mkdir()

    assert resolve_main_repo_root(cwd) == cwd
