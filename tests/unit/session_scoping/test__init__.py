"""Tests for the public session-scoping API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import teleclaude.session_scoping._api as api_module
from teleclaude.session_scoping import resolve_scoped_paths
from teleclaude.session_scoping._types import ResolvedWorkspace, ScopedPathsResult


def test_resolve_scoped_paths_returns_empty_for_unsupported_workspace_mode() -> None:
    with patch.object(
        api_module,
        "resolve_workspace",
        return_value=ResolvedWorkspace(root="/repo", kind="git_shared"),
    ):
        result = resolve_scoped_paths(
            session_id="session-1",
            workspace_root="/repo",
            agent_name="claude",
            scope_mode="workspace_dirty",
            transcript_path="/tmp/session.jsonl",
        )

    assert not result.paths
    assert result.workspace_kind == "git_shared"
    assert result.strategy == "unsupported_mode"
    assert result.ledger_updated is False


def test_resolve_scoped_paths_logs_structured_warning_and_fails_open() -> None:
    with (
        patch.object(
            api_module,
            "resolve_workspace",
            return_value=ResolvedWorkspace(root="/repo", kind="git_shared"),
        ),
        patch.object(api_module, "resolve_native_scoped_paths", side_effect=RuntimeError("boom")),
        patch.object(api_module.logger, "warning") as warning_mock,
    ):
        result = resolve_scoped_paths(
            session_id="session-1",
            workspace_root="/repo",
            agent_name="claude",
            scope_mode="turn_delta",
            transcript_path="/tmp/session.jsonl",
        )

    assert result == ScopedPathsResult(
        paths=(),
        scope_mode="turn_delta",
        workspace_kind="git_shared",
        strategy="error",
        ledger_updated=False,
    )
    warning_mock.assert_called_once()
    assert warning_mock.call_args.kwargs == {
        "session_id": "session-1",
        "workspace_root": "/repo",
        "agent": "claude",
        "scope_mode": "turn_delta",
        "workspace_kind": "git_shared",
        "error": "boom",
        "exc_info": True,
    }


def test_resolve_scoped_paths_exercises_non_git_workspace_end_to_end(tmp_path: Path) -> None:
    workspace_root = tmp_path / "plain-workspace"
    workspace_root.mkdir()

    with (
        patch(
            "teleclaude.session_scoping._native_strategy.resolve_extractor",
            return_value=lambda **_: ({"notes/todo.md", "src/plain.py"}, "claude_file_history"),
        ),
        patch("teleclaude.session_scoping._native_strategy.collect_git_dirty_paths") as collect_git_dirty_mock,
    ):
        result = resolve_scoped_paths(
            session_id="session-1",
            workspace_root=str(workspace_root),
            agent_name="claude",
            scope_mode="session_dirty",
            transcript_path="/tmp/session.jsonl",
        )

    assert result == ScopedPathsResult(
        paths=("notes/todo.md", "src/plain.py"),
        scope_mode="session_dirty",
        workspace_kind="non_git",
        strategy="claude_file_history",
        ledger_updated=False,
    )
    collect_git_dirty_mock.assert_not_called()
