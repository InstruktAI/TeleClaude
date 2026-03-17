"""Characterization tests for teleclaude.core.integration.formatters."""

from __future__ import annotations

from teleclaude.core.integration.formatters import (
    _format_commit_decision,
    _format_conflict_decision,
    _format_error,
    _format_lease_busy,
    _format_pull_blocked,
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


def test_format_pull_blocked_returns_string():
    result = _format_pull_blocked("dirty files", "slug-a")
    assert isinstance(result, str)
    assert "slug-a" in result
    assert "dirty files" in result


def test_format_queue_empty_returns_string():
    result = _format_queue_empty(3, 1, 5000)
    assert isinstance(result, str)
    assert "3" in result
    assert "1" in result


def test_format_error_returns_string_with_code():
    result = _format_error("INVALID_STATE", "checkpoint missing candidate")
    assert isinstance(result, str)
    assert "INVALID_STATE" in result
