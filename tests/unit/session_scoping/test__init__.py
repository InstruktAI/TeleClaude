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


def test_anchor_intersects_extractor_with_diff_paths(tmp_path: Path) -> None:
    """With an anchor, the result is the extractor output ∩ git-diff output."""
    workspace_root = tmp_path / "git-workspace"
    workspace_root.mkdir()

    captured_scope_modes: list[object] = []

    def _extractor(**kwargs: object) -> tuple[set[str], str]:
        captured_scope_modes.append(kwargs.get("scope_mode"))
        return ({"src/owned.py", "src/other.py"}, "claude_file_history")

    with (
        patch.object(
            api_module,
            "resolve_workspace",
            return_value=ResolvedWorkspace(root=str(workspace_root), kind="git_shared"),
        ),
        patch.object(api_module, "resolve_extractor", return_value=_extractor),
        patch.object(
            api_module,
            "paths_changed_since",
            return_value={"src/owned.py", "unrelated.py"},
        ),
    ):
        result = resolve_scoped_paths(
            session_id="session-1",
            workspace_root=str(workspace_root),
            agent_name="claude",
            scope_mode="turn_delta",
            transcript_path="/tmp/session.jsonl",
            turn_anchor_sha="anchor-sha",
        )

    # Extractor must run in session_dirty mode when an anchor is present —
    # the anchor provides the turn boundary.
    assert captured_scope_modes[0] == "session_dirty"
    assert result.paths == ("src/owned.py",)
    assert result.strategy == "claude_file_history+anchor_diff"


def test_anchor_with_in_turn_commit_still_surfaces_paths(tmp_path: Path) -> None:
    """Same-turn commit: extractor knows about the edit, dirty is empty,
    diff against the anchor still includes the committed path."""
    workspace_root = tmp_path / "git-workspace"
    workspace_root.mkdir()

    with (
        patch.object(
            api_module,
            "resolve_workspace",
            return_value=ResolvedWorkspace(root=str(workspace_root), kind="git_shared"),
        ),
        patch.object(
            api_module,
            "resolve_extractor",
            return_value=lambda **_: ({"src/feature.py"}, "claude_file_history"),
        ),
        patch.object(
            api_module,
            "paths_changed_since",
            return_value={"src/feature.py"},
        ),
    ):
        result = resolve_scoped_paths(
            session_id="session-1",
            workspace_root=str(workspace_root),
            agent_name="claude",
            scope_mode="turn_delta",
            transcript_path="/tmp/session.jsonl",
            turn_anchor_sha="anchor-sha",
        )

    assert result.paths == ("src/feature.py",)


def test_anchor_skipped_when_not_turn_delta(tmp_path: Path) -> None:
    """session_dirty scope is cumulative — the anchor turn-bound is irrelevant."""
    workspace_root = tmp_path / "git-workspace"
    workspace_root.mkdir()

    with (
        patch.object(
            api_module,
            "resolve_workspace",
            return_value=ResolvedWorkspace(root=str(workspace_root), kind="git_shared"),
        ),
        patch.object(
            api_module,
            "resolve_extractor",
            return_value=lambda **_: ({"src/a.py", "src/b.py"}, "claude_file_history"),
        ),
        patch.object(api_module, "paths_changed_since") as diff_mock,
    ):
        result = resolve_scoped_paths(
            session_id="session-1",
            workspace_root=str(workspace_root),
            agent_name="claude",
            scope_mode="session_dirty",
            transcript_path="/tmp/session.jsonl",
            turn_anchor_sha="anchor-sha",
        )

    diff_mock.assert_not_called()
    assert result.paths == ("src/a.py", "src/b.py")
    assert result.strategy == "claude_file_history"


def test_anchor_absent_falls_back_to_extractor_only(tmp_path: Path) -> None:
    """No anchor → previous behavior, extractor output unmodified."""
    workspace_root = tmp_path / "git-workspace"
    workspace_root.mkdir()

    with (
        patch.object(
            api_module,
            "resolve_workspace",
            return_value=ResolvedWorkspace(root=str(workspace_root), kind="git_shared"),
        ),
        patch.object(
            api_module,
            "resolve_extractor",
            return_value=lambda **_: ({"src/a.py"}, "claude_file_history"),
        ),
        patch.object(api_module, "paths_changed_since") as diff_mock,
    ):
        result = resolve_scoped_paths(
            session_id="session-1",
            workspace_root=str(workspace_root),
            agent_name="claude",
            scope_mode="turn_delta",
            transcript_path="/tmp/session.jsonl",
            turn_anchor_sha=None,
        )

    diff_mock.assert_not_called()
    assert result.paths == ("src/a.py",)
    assert result.strategy == "claude_file_history"
