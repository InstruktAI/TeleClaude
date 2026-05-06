"""Tests for the public session-scoping API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import teleclaude.session_scoping._api as api_module
from teleclaude.session_scoping import resolve_scoped_paths
from teleclaude.session_scoping._types import ResolvedWorkspace, ScopedPathsResult


def test_resolve_scoped_paths_returns_empty_for_workspace_kind_none() -> None:
    with patch.object(
        api_module,
        "resolve_workspace",
        return_value=ResolvedWorkspace(root=None, kind="none"),
    ):
        result = resolve_scoped_paths(
            session_id="session-1",
            workspace_root=None,
            agent_name="claude",
            scope_mode="turn_delta",
            transcript_path="/tmp/session.jsonl",
        )

    assert result == ScopedPathsResult(
        paths=(),
        scope_mode="turn_delta",
        workspace_kind="none",
        strategy="none",
        ledger_updated=False,
    )


def test_resolve_scoped_paths_logs_structured_warning_and_fails_open() -> None:
    with (
        patch.object(
            api_module,
            "resolve_workspace",
            return_value=ResolvedWorkspace(root="/repo", kind="git_shared"),
        ),
        patch.object(api_module, "resolve_extractor", side_effect=RuntimeError("boom")),
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


def test_resolve_scoped_paths_returns_extractor_paths_unchanged(tmp_path: Path) -> None:
    workspace_root = tmp_path / "plain-workspace"
    workspace_root.mkdir()

    with patch.object(
        api_module,
        "resolve_extractor",
        return_value=lambda **_: ({"notes/todo.md", "src/plain.py"}, "claude_file_history"),
    ):
        result = resolve_scoped_paths(
            session_id="session-1",
            workspace_root=str(workspace_root),
            agent_name="claude",
            scope_mode="turn_delta",
            transcript_path="/tmp/session.jsonl",
        )

    assert result == ScopedPathsResult(
        paths=("notes/todo.md", "src/plain.py"),
        scope_mode="turn_delta",
        workspace_kind="non_git",
        strategy="claude_file_history",
        ledger_updated=False,
    )
