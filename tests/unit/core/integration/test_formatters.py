"""Characterization tests for teleclaude.core.integration.formatters."""

from __future__ import annotations

from teleclaude.core.integration.formatters import (
    _format_anomalies,
    _format_autostash_orphaned,
    _format_commit_decision,
    _format_conflict_decision,
    _format_error,
    _format_lease_busy,
    _format_push_rejected,
    _format_queue_empty,
)

# Formatters produce structured agent instruction text.
# We assert behavioral contracts: correct type, non-empty, and
# execution-significant tokens that agents parse.


def test_format_commit_decision_returns_non_empty_string():
    result = _format_commit_decision("slug-a", "branch-a", "5 files changed", "commit log", "requirements", "plan")
    assert isinstance(result, str)
    assert "slug-a" in result
    assert "branch-a" in result


def test_format_commit_decision_contains_candidate_slug():
    result = _format_commit_decision("my-slug", "my-branch", "", "", "", "")
    assert "my-slug" in result


def test_format_conflict_decision_returns_string():
    result = _format_conflict_decision("slug-a", "branch-a", ["file1.py", "file2.py"])
    assert isinstance(result, str)
    assert "slug-a" in result
    assert "file1.py" in result
    assert "file2.py" in result


def test_format_conflict_decision_contains_conflicted_files():
    result = _format_conflict_decision("slug-a", "branch-a", ["src/foo.py"])
    assert "src/foo.py" in result


def test_format_conflict_decision_handles_empty_file_list():
    result = _format_conflict_decision("slug-a", "branch-a", [])
    assert isinstance(result, str)
    assert "slug-a" in result


def test_format_push_rejected_returns_string():
    result = _format_push_rejected("remote rejected", "slug-a")
    assert isinstance(result, str)
    assert "slug-a" in result
    assert "remote rejected" in result


def test_format_lease_busy_returns_string():
    result = _format_lease_busy("session-xyz")
    assert isinstance(result, str)
    assert "session-xyz" in result


def test_format_autostash_orphaned_targets_project_root():
    result = _format_autostash_orphaned("stash@{0}: WIP", "/home/user/project")
    assert isinstance(result, str)
    assert "git -C /home/user/project stash pop" in result


def test_format_queue_empty_returns_string():
    result = _format_queue_empty(3, 1, 5000)
    assert isinstance(result, str)
    assert "3" in result
    assert "1" in result


def test_format_anomalies_empty_returns_empty_string():
    assert _format_anomalies([]) == ""


def test_format_anomalies_non_empty_returns_string_with_items():
    result = _format_anomalies(["deliver_to_delivered failed for my-slug"])
    assert isinstance(result, str)
    assert len(result) > 0
    assert "deliver_to_delivered failed for my-slug" in result


def test_format_anomalies_multiple_items_all_present():
    result = _format_anomalies(["warning A", "warning B"])
    assert "warning A" in result
    assert "warning B" in result


def test_format_queue_empty_with_warnings_includes_warning_text():
    result = _format_queue_empty(3, 1, 5000, warnings=["bookkeeping commit failed"])
    assert "bookkeeping commit failed" in result


def test_format_error_returns_string_with_code():
    result = _format_error("INVALID_STATE", "checkpoint missing candidate")
    assert isinstance(result, str)
    assert "INVALID_STATE" in result


def test_commit_decision_emits_plain_git_commands():
    """Agent runs from the worktree — commands must not contain -C trees/_integration."""
    result = _format_commit_decision("s", "b", "", "", "", "")
    assert "git commit -m" in result
    assert "-C trees/_integration" not in result


def test_conflict_decision_emits_plain_git_commands():
    result = _format_conflict_decision("s", "b", ["f.py"])
    assert "git add" in result
    assert "-C trees/_integration" not in result


def test_push_rejected_emits_plain_git_commands():
    result = _format_push_rejected("rejected", "s")
    assert "git fetch origin" in result
    assert "git rebase origin/main" in result
    assert "-C trees/_integration" not in result
