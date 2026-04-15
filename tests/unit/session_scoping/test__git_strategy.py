"""Tests for git-backed session scoping behavior."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import pytest

import teleclaude.session_scoping._git_strategy as git_strategy
import teleclaude.session_scoping._store as store_module


class _WarningCallKwargs(TypedDict):
    session_id: str
    workspace_root: str
    exc_info: bool


class _FakeGit:
    def __init__(self, status_output: str) -> None:
        self._status_output = status_output

    def status(self, *args: str) -> str:
        assert args == ("--porcelain", "--untracked-files=all")
        return self._status_output


class _FakeRepo:
    def __init__(self, status_output: str) -> None:
        self.git = _FakeGit(status_output)


def test_collect_git_dirty_paths_includes_modified_untracked_deleted_added_and_rename_dest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_output = "\n".join(
        [
            " M src/app.py",
            "?? tests/unit/test_app.py",
            " D docs/old.md",
            "A  scripts/new.py",
            "R  src/old_name.py -> src/new_name.py",
        ]
    )
    monkeypatch.setattr(git_strategy, "Repo", lambda _workspace_root: _FakeRepo(status_output))

    paths = git_strategy.collect_git_dirty_paths("/repo")

    assert paths == {
        "docs/old.md",
        "scripts/new.py",
        "src/app.py",
        "src/new_name.py",
        "tests/unit/test_app.py",
    }


def test_git_worktree_turn_delta_persists_seen_paths_across_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(store_module, "SESSION_SCOPING_DIR", tmp_path)
    monkeypatch.setattr(
        git_strategy,
        "collect_git_dirty_paths",
        lambda _workspace_root: {"docs/guide.md", "src/app.py"},
    )

    first = git_strategy.resolve_git_worktree_paths(
        session_id="session-1",
        workspace_root="/repo/trees/task-a",
        agent_name="codex",
        scope_mode="turn_delta",
    )
    second = git_strategy.resolve_git_worktree_paths(
        session_id="session-1",
        workspace_root="/repo/trees/task-a",
        agent_name="codex",
        scope_mode="turn_delta",
    )

    assert first.paths == ("docs/guide.md", "src/app.py")
    assert first.ledger_updated is True
    assert not second.paths
    assert second.ledger_updated is False


def test_git_worktree_workspace_and_session_dirty_return_full_current_dirty_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        git_strategy,
        "collect_git_dirty_paths",
        lambda _workspace_root: {"src/app.py", "tests/unit/test_app.py"},
    )

    workspace_dirty = git_strategy.resolve_git_worktree_paths(
        session_id="session-1",
        workspace_root="/repo/trees/task-a",
        agent_name="codex",
        scope_mode="workspace_dirty",
    )
    session_dirty = git_strategy.resolve_git_worktree_paths(
        session_id="session-1",
        workspace_root="/repo/trees/task-a",
        agent_name="codex",
        scope_mode="session_dirty",
    )

    assert workspace_dirty.paths == ("src/app.py", "tests/unit/test_app.py")
    assert session_dirty.paths == ("src/app.py", "tests/unit/test_app.py")
    assert workspace_dirty.ledger_updated is False
    assert session_dirty.ledger_updated is False


def test_git_worktree_turn_delta_logs_exc_info_when_ledger_write_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        git_strategy,
        "collect_git_dirty_paths",
        lambda _workspace_root: {"src/new.py"},
    )
    monkeypatch.setattr(git_strategy, "load_workspace_ledger", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        git_strategy,
        "save_workspace_ledger",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    warning_calls: list[tuple[tuple[object, ...], _WarningCallKwargs]] = []

    def _capture_warning(*args: object, **kwargs: object) -> None:
        warning_calls.append((args, kwargs))

    monkeypatch.setattr(git_strategy.logger, "warning", _capture_warning)

    result = git_strategy.resolve_git_worktree_paths(
        session_id="session-1",
        workspace_root="/repo/trees/task-a",
        agent_name="codex",
        scope_mode="turn_delta",
    )

    assert result.paths == ("src/new.py",)
    assert result.ledger_updated is False
    assert warning_calls == [
        (
            ("Ledger write failed, returning paths without persistence",),
            {
                "session_id": "session-1",
                "workspace_root": "/repo/trees/task-a",
                "exc_info": True,
            },
        )
    ]
