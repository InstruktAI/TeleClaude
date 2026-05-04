"""Tests for the native session-scoping strategy."""

from __future__ import annotations

from unittest.mock import patch

from teleclaude.session_scoping._native_strategy import resolve_native_scoped_paths
from teleclaude.session_scoping._types import ResolvedWorkspace, ScopedPathsResult


def test_git_shared_native_strategy_intersects_with_git_dirty_paths() -> None:
    workspace = ResolvedWorkspace(root="/repo", kind="git_shared")

    with (
        patch(
            "teleclaude.session_scoping._native_strategy.resolve_extractor",
            return_value=lambda **_: ({"src/kept.py", "src/dropped.py"}, "gemini_structured"),
        ),
        patch("teleclaude.session_scoping._native_strategy.collect_git_dirty_paths", return_value={"src/kept.py"}),
    ):
        result = resolve_native_scoped_paths(
            workspace=workspace,
            agent_name="gemini",
            scope_mode="session_dirty",
            transcript_path="/tmp/session.json",
            native_session_id="native-1",
        )

    assert result == ScopedPathsResult(
        paths=("src/kept.py",),
        scope_mode="session_dirty",
        workspace_kind="git_shared",
        strategy="gemini_structured",
        ledger_updated=False,
    )


def test_git_shared_native_strategy_returns_empty_when_git_dirty_set_is_empty() -> None:
    workspace = ResolvedWorkspace(root="/repo", kind="git_shared")

    with (
        patch(
            "teleclaude.session_scoping._native_strategy.resolve_extractor",
            return_value=lambda **_: ({"src/only_native.py"}, "codex_structured"),
        ),
        patch("teleclaude.session_scoping._native_strategy.collect_git_dirty_paths", return_value=set()),
    ):
        result = resolve_native_scoped_paths(
            workspace=workspace,
            agent_name="codex",
            scope_mode="session_dirty",
            transcript_path="/tmp/session.jsonl",
            native_session_id="native-1",
        )

    assert not result.paths
    assert result.strategy == "codex_structured"


def test_non_git_native_strategy_passes_through_native_paths() -> None:
    workspace = ResolvedWorkspace(root="/plain", kind="non_git")

    with patch(
        "teleclaude.session_scoping._native_strategy.resolve_extractor",
        return_value=lambda **_: ({"notes/todo.md", "src/plain.py"}, "claude_file_history"),
    ):
        result = resolve_native_scoped_paths(
            workspace=workspace,
            agent_name="claude",
            scope_mode="session_dirty",
            transcript_path="/tmp/claude.jsonl",
            native_session_id=None,
        )

    assert result == ScopedPathsResult(
        paths=("notes/todo.md", "src/plain.py"),
        scope_mode="session_dirty",
        workspace_kind="non_git",
        strategy="claude_file_history",
        ledger_updated=False,
    )


def test_native_strategy_returns_empty_for_workspace_dirty_in_non_git_workspace() -> None:
    workspace = ResolvedWorkspace(root="/plain", kind="non_git")

    result = resolve_native_scoped_paths(
        workspace=workspace,
        agent_name="claude",
        scope_mode="workspace_dirty",
        transcript_path="/tmp/claude.jsonl",
        native_session_id=None,
    )

    assert result == ScopedPathsResult(
        paths=(),
        scope_mode="workspace_dirty",
        workspace_kind="non_git",
        strategy="unsupported_mode",
        ledger_updated=False,
    )


def test_native_strategy_returns_empty_when_extractor_returns_no_paths() -> None:
    workspace = ResolvedWorkspace(root="/plain", kind="non_git")

    with patch(
        "teleclaude.session_scoping._native_strategy.resolve_extractor",
        return_value=lambda **_: (set(), "claude_structured_fallback"),
    ):
        result = resolve_native_scoped_paths(
            workspace=workspace,
            agent_name="claude",
            scope_mode="turn_delta",
            transcript_path="/tmp/claude.jsonl",
            native_session_id=None,
        )

    assert not result.paths
    assert result.workspace_kind == "non_git"
    assert result.strategy == "claude_structured_fallback"
