"""Tests for workspace resolution in teleclaude.session_scoping."""

from __future__ import annotations

from pathlib import Path

from teleclaude.session_scoping._workspace import resolve_workspace


def test_resolve_workspace_identifies_git_worktree_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    worktree_root = tmp_path / "trees" / "feature-a"
    gitdir = repo_root / ".git" / "worktrees" / "feature-a"
    gitdir.mkdir(parents=True)
    (worktree_root / "pkg").mkdir(parents=True)
    (worktree_root / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

    resolved = resolve_workspace(worktree_root / "pkg")

    assert resolved.kind == "git_worktree"
    assert resolved.root == str(worktree_root.resolve())


def test_resolve_workspace_identifies_shared_git_root(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    (repo_root / "pkg").mkdir()

    resolved = resolve_workspace(repo_root / "pkg")

    assert resolved.kind == "git_shared"
    assert resolved.root == str(repo_root.resolve())


def test_resolve_workspace_returns_non_git_root_when_no_repository_exists(tmp_path: Path) -> None:
    workspace_root = tmp_path / "plain-workspace"
    (workspace_root / "pkg").mkdir(parents=True)

    resolved = resolve_workspace(workspace_root / "pkg")

    assert resolved.kind == "non_git"
    assert resolved.root == str((workspace_root / "pkg").resolve())


def test_resolve_workspace_returns_none_when_workspace_root_missing() -> None:
    resolved = resolve_workspace(None)

    assert resolved.kind == "none"
    assert resolved.root is None
