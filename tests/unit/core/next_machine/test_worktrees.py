"""Characterization tests for worktree preparation policy helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from teleclaude.core.next_machine._types import WorktreePrepDecision
from teleclaude.core.next_machine.worktrees import (
    _ensure_todo_on_remote_main,
    _read_worktree_prep_state,
    _write_worktree_prep_state,
    ensure_worktree_with_policy,
)


def test_worktree_prep_state_round_trips_valid_marker(tmp_path: Path) -> None:
    worktree = tmp_path / "trees" / "slug-a"
    worktree.mkdir(parents=True)

    _write_worktree_prep_state(str(tmp_path), "slug-a", "digest-123")

    assert _read_worktree_prep_state(str(tmp_path), "slug-a") == {"inputs_digest": "digest-123"}


def test_ensure_worktree_with_policy_prepares_when_decision_requires_it(tmp_path: Path) -> None:
    decision = WorktreePrepDecision(should_prepare=True, reason="prep_state_missing", inputs_digest="abc")

    with (
        patch("teleclaude.core.next_machine.worktrees._create_or_attach_worktree", return_value=True),
        patch("teleclaude.core.next_machine.worktrees._decide_worktree_prep", return_value=decision),
        patch("teleclaude.core.next_machine.worktrees._prepare_worktree") as prepare,
        patch("teleclaude.core.next_machine.worktrees._write_worktree_prep_state") as write_state,
    ):
        result = ensure_worktree_with_policy(str(tmp_path), "slug-b")

    assert result.created is True
    assert result.prepared is True
    assert result.prep_reason == "prep_state_missing"
    prepare.assert_called_once_with(str(tmp_path), "slug-b")
    write_state.assert_called_once_with(str(tmp_path), "slug-b", "abc")


def test_ensure_worktree_with_policy_skips_prep_when_inputs_are_unchanged(tmp_path: Path) -> None:
    decision = WorktreePrepDecision(should_prepare=False, reason="unchanged_known_good", inputs_digest="abc")

    with (
        patch("teleclaude.core.next_machine.worktrees._create_or_attach_worktree", return_value=False),
        patch("teleclaude.core.next_machine.worktrees._decide_worktree_prep", return_value=decision),
        patch("teleclaude.core.next_machine.worktrees._prepare_worktree") as prepare,
        patch("teleclaude.core.next_machine.worktrees._write_worktree_prep_state") as write_state,
    ):
        result = ensure_worktree_with_policy(str(tmp_path), "slug-c")

    assert result.created is False
    assert result.prepared is False
    assert result.prep_reason == "unchanged_known_good"
    prepare.assert_not_called()
    write_state.assert_not_called()


def test_ensure_todo_on_remote_main_returns_no_local_artifacts_when_folder_is_missing(tmp_path: Path) -> None:
    assert _ensure_todo_on_remote_main(str(tmp_path), "missing") == (False, "no_local_artifacts")


def test_ensure_todo_on_remote_main_skips_when_remote_already_has_the_todo(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-d"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("content", encoding="utf-8")
    repo = SimpleNamespace(
        git=SimpleNamespace(
            fetch=lambda *_args: None,
            ls_tree=lambda *_args: "100644 blob abc\ttodos/slug-d/requirements.md\n",
        )
    )

    with patch("teleclaude.core.next_machine.worktrees.Repo", return_value=repo):
        result = _ensure_todo_on_remote_main(str(tmp_path), "slug-d")

    assert result == (False, "already_on_remote")
