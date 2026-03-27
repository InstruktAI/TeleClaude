"""Unit tests for work_lifecycle on_enter handlers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.state_machine import TargetContext
from teleclaude.core.next_machine.work_lifecycle import (
    _on_enter_finalize_handoff,
    _on_enter_finalize_ready,
    _on_enter_prepared,
    _on_enter_review_approved,
    _on_enter_review_changes,
)

StateData = dict[str, StateValue]


def _ctx(tmp_path: Path, slug: str = "test-slug") -> TargetContext:
    return TargetContext(cwd=str(tmp_path), slug=slug, actor_id="session-x", at="2024-01-01T00:00:00")


# ---------------------------------------------------------------------------
# _on_enter_finalize_ready (I-1)
# ---------------------------------------------------------------------------


def test_finalize_ready_raises_when_worktree_missing(tmp_path: Path) -> None:
    """Raises ValueError when the worktree directory does not exist."""
    with patch("teleclaude.core.next_machine.work_lifecycle.WORKTREE_DIR", "trees"):
        with pytest.raises(ValueError, match="worktree not found"):
            _on_enter_finalize_ready({}, _ctx(tmp_path))


def test_finalize_ready_raises_when_uncommitted_changes(tmp_path: Path) -> None:
    """Raises ValueError when worktree has uncommitted changes."""
    worktree = tmp_path / "trees" / "test-slug"
    worktree.mkdir(parents=True)

    with (
        patch("teleclaude.core.next_machine.work_lifecycle.WORKTREE_DIR", "trees"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=True),
    ):
        with pytest.raises(ValueError, match="uncommitted changes"):
            _on_enter_finalize_ready({}, _ctx(tmp_path))


def test_finalize_ready_raises_when_head_commit_missing(tmp_path: Path) -> None:
    """Raises ValueError when worktree or branch HEAD cannot be resolved."""
    worktree = tmp_path / "trees" / "test-slug"
    worktree.mkdir(parents=True)

    with (
        patch("teleclaude.core.next_machine.work_lifecycle.WORKTREE_DIR", "trees"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=False),
        patch("teleclaude.core.next_machine.work_lifecycle.get_head_commit", return_value=""),
        patch("teleclaude.core.next_machine.work_lifecycle.get_ref_commit", return_value=""),
    ):
        with pytest.raises(ValueError, match="unable to resolve finalized branch head"):
            _on_enter_finalize_ready({}, _ctx(tmp_path))


def test_finalize_ready_raises_when_head_mismatch(tmp_path: Path) -> None:
    """Raises ValueError when worktree HEAD does not match the branch ref."""
    worktree = tmp_path / "trees" / "test-slug"
    worktree.mkdir(parents=True)

    with (
        patch("teleclaude.core.next_machine.work_lifecycle.WORKTREE_DIR", "trees"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=False),
        patch("teleclaude.core.next_machine.work_lifecycle.get_head_commit", return_value="aaa"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_ref_commit", return_value="bbb"),
    ):
        with pytest.raises(ValueError, match="does not match worktree HEAD"):
            _on_enter_finalize_ready({}, _ctx(tmp_path))


def test_finalize_ready_raises_when_remote_missing(tmp_path: Path) -> None:
    """Raises ValueError when origin/<slug> branch is absent."""
    worktree = tmp_path / "trees" / "test-slug"
    worktree.mkdir(parents=True)

    with (
        patch("teleclaude.core.next_machine.work_lifecycle.WORKTREE_DIR", "trees"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=False),
        patch("teleclaude.core.next_machine.work_lifecycle.get_head_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_ref_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_remote_branch_head", return_value=""),
    ):
        with pytest.raises(ValueError, match="origin/test-slug is missing"):
            _on_enter_finalize_ready({}, _ctx(tmp_path))


def test_finalize_ready_raises_when_remote_mismatch(tmp_path: Path) -> None:
    """Raises ValueError when origin HEAD is behind the local branch head."""
    worktree = tmp_path / "trees" / "test-slug"
    worktree.mkdir(parents=True)

    with (
        patch("teleclaude.core.next_machine.work_lifecycle.WORKTREE_DIR", "trees"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=False),
        patch("teleclaude.core.next_machine.work_lifecycle.get_head_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_ref_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_remote_branch_head", return_value="old000"),
    ):
        with pytest.raises(ValueError, match="origin/test-slug is at old000"):
            _on_enter_finalize_ready({}, _ctx(tmp_path))


def test_finalize_ready_happy_path_writes_finalize_dict(tmp_path: Path) -> None:
    """Happy path: writes finalize dict with status=ready."""
    worktree = tmp_path / "trees" / "test-slug"
    worktree.mkdir(parents=True)

    with (
        patch("teleclaude.core.next_machine.work_lifecycle.WORKTREE_DIR", "trees"),
        patch("teleclaude.core.next_machine.work_lifecycle.has_uncommitted_changes", return_value=False),
        patch("teleclaude.core.next_machine.work_lifecycle.get_head_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_ref_commit", return_value="abc123"),
        patch("teleclaude.core.next_machine.work_lifecycle.get_remote_branch_head", return_value="abc123"),
    ):
        result = _on_enter_finalize_ready({}, _ctx(tmp_path))

    finalize = result.get("finalize")
    assert isinstance(finalize, dict)
    assert finalize["status"] == "ready"
    assert finalize["sha"] == "abc123"
    assert finalize["branch"] == "test-slug"
    assert finalize["worker_session_id"] == "session-x"


# ---------------------------------------------------------------------------
# _on_enter_finalize_handoff (I-1)
# ---------------------------------------------------------------------------


def test_finalize_handoff_raises_when_finalize_not_ready(tmp_path: Path) -> None:
    """Raises ValueError when finalize.status is not 'ready'."""
    state: StateData = {"finalize": {"status": "pending"}}
    with pytest.raises(ValueError, match=r"finalize state.*is not ready"):
        _on_enter_finalize_handoff(state, _ctx(tmp_path))


def test_finalize_handoff_raises_when_finalize_absent(tmp_path: Path) -> None:
    """Raises ValueError when finalize key is absent."""
    with pytest.raises(ValueError, match=r"finalize state.*is not ready"):
        _on_enter_finalize_handoff({}, _ctx(tmp_path))


def test_finalize_handoff_happy_path_writes_handed_off(tmp_path: Path) -> None:
    """Happy path: transitions finalize.status from ready → handed_off."""
    state: StateData = {
        "finalize": {
            "status": "ready",
            "sha": "abc123",
            "branch": "test-slug",
            "ready_at": "2024-01-01T00:00:00",
            "worker_session_id": "worker-1",
        }
    }

    result = _on_enter_finalize_handoff(state, _ctx(tmp_path))

    finalize = result.get("finalize")
    assert isinstance(finalize, dict)
    assert finalize["status"] == "handed_off"
    assert finalize["sha"] == "abc123"
    assert finalize["handoff_session_id"] == "session-x"
    assert "handed_off_at" in finalize


# ---------------------------------------------------------------------------
# _on_enter_review_changes (I-10)
# ---------------------------------------------------------------------------

_REVIEW_MODULE = "teleclaude.core.next_machine.work_lifecycle"


def test_review_changes_happy_path(tmp_path: Path) -> None:
    """Happy path: increments review_round, stamps baseline from worktree HEAD, extracts findings."""
    state: StateData = {
        "review_round": 1,
        "resolved_findings": ["R1-F1"],
    }

    with (
        patch(f"{_REVIEW_MODULE}.WORKTREE_DIR", "trees"),
        patch(f"{_REVIEW_MODULE}.get_head_commit", return_value="deadbeef") as mock_head,
        patch(f"{_REVIEW_MODULE}._extract_finding_ids", return_value=["R2-F1", "R2-F2"]) as mock_extract,
    ):
        result = _on_enter_review_changes(state, _ctx(tmp_path))

    assert result["review_round"] == 2
    assert result["review_baseline_commit"] == "deadbeef"
    assert result["unresolved_findings"] == ["R2-F1", "R2-F2"]
    assert result["resolved_findings"] == ["R1-F1"]

    expected_worktree = str(tmp_path / "trees" / "test-slug")
    mock_head.assert_called_once_with(expected_worktree)
    mock_extract.assert_called_once_with(expected_worktree, "test-slug")


def test_review_changes_empty_head_logs_warning(tmp_path: Path) -> None:
    """When get_head_commit returns empty, review_baseline_commit is not stamped and warning is logged."""
    state: StateData = {"review_round": 0, "resolved_findings": []}

    with (
        patch(f"{_REVIEW_MODULE}.WORKTREE_DIR", "trees"),
        patch(f"{_REVIEW_MODULE}.get_head_commit", return_value=""),
        patch(f"{_REVIEW_MODULE}._extract_finding_ids", return_value=[]),
        patch(f"{_REVIEW_MODULE}.logger") as mock_logger,
    ):
        result = _on_enter_review_changes(state, _ctx(tmp_path))

    assert "review_baseline_commit" not in result
    mock_logger.warning.assert_called_once()
    assert result["review_round"] == 1


def test_review_changes_defaults_non_int_round_to_zero(tmp_path: Path) -> None:
    """When review_round is not an int, defaults to 0 and increments to 1."""
    state: StateData = {"review_round": "garbage", "resolved_findings": []}

    with (
        patch(f"{_REVIEW_MODULE}.WORKTREE_DIR", "trees"),
        patch(f"{_REVIEW_MODULE}.get_head_commit", return_value="abc"),
        patch(f"{_REVIEW_MODULE}._extract_finding_ids", return_value=[]),
    ):
        result = _on_enter_review_changes(state, _ctx(tmp_path))

    assert result["review_round"] == 1


# ---------------------------------------------------------------------------
# _on_enter_review_approved (I-10)
# ---------------------------------------------------------------------------


def test_review_approved_happy_path_merges_findings(tmp_path: Path) -> None:
    """Happy path: increments round, stamps baseline, merges unresolved into resolved."""
    state: StateData = {
        "review_round": 1,
        "unresolved_findings": ["R2-F1", "R2-F2"],
        "resolved_findings": ["R1-F1"],
    }

    with (
        patch(f"{_REVIEW_MODULE}.WORKTREE_DIR", "trees"),
        patch(f"{_REVIEW_MODULE}.get_head_commit", return_value="cafebabe") as mock_head,
    ):
        result = _on_enter_review_approved(state, _ctx(tmp_path))

    assert result["review_round"] == 2
    assert result["review_baseline_commit"] == "cafebabe"
    assert result["unresolved_findings"] == []
    resolved = result["resolved_findings"]
    assert isinstance(resolved, list)
    assert "R1-F1" in resolved
    assert "R2-F1" in resolved
    assert "R2-F2" in resolved

    expected_worktree = str(tmp_path / "trees" / "test-slug")
    mock_head.assert_called_once_with(expected_worktree)


def test_review_approved_empty_head_logs_warning(tmp_path: Path) -> None:
    """When get_head_commit returns empty, review_baseline_commit is not stamped and warning is logged."""
    state: StateData = {"review_round": 0, "unresolved_findings": [], "resolved_findings": []}

    with (
        patch(f"{_REVIEW_MODULE}.WORKTREE_DIR", "trees"),
        patch(f"{_REVIEW_MODULE}.get_head_commit", return_value=""),
        patch(f"{_REVIEW_MODULE}.logger") as mock_logger,
    ):
        result = _on_enter_review_approved(state, _ctx(tmp_path))

    assert "review_baseline_commit" not in result
    mock_logger.warning.assert_called_once()
    assert result["review_round"] == 1


def test_review_approved_deduplicates_merged_findings(tmp_path: Path) -> None:
    """Duplicate findings across resolved and unresolved are deduplicated in the merge."""
    state: StateData = {
        "review_round": 0,
        "unresolved_findings": ["R1-F1", "R2-F1"],
        "resolved_findings": ["R1-F1"],
    }

    with (
        patch(f"{_REVIEW_MODULE}.WORKTREE_DIR", "trees"),
        patch(f"{_REVIEW_MODULE}.get_head_commit", return_value="abc"),
    ):
        result = _on_enter_review_approved(state, _ctx(tmp_path))

    resolved = result["resolved_findings"]
    assert isinstance(resolved, list)
    assert resolved.count("R1-F1") == 1
    assert "R2-F1" in resolved
    assert result["unresolved_findings"] == []


# ---------------------------------------------------------------------------
# _on_enter_finalize_ready backward guard (I-11)
# ---------------------------------------------------------------------------


def test_finalize_ready_raises_when_already_handed_off(tmp_path: Path) -> None:
    """Raises ValueError when finalize.status is 'handed_off' — prevents state regression."""
    state: StateData = {
        "finalize": {
            "status": "handed_off",
            "sha": "abc123",
            "branch": "test-slug",
            "handed_off_at": "2024-01-01T00:00:00",
        }
    }
    worktree = tmp_path / "trees" / "test-slug"
    worktree.mkdir(parents=True)

    with patch(f"{_REVIEW_MODULE}.WORKTREE_DIR", "trees"):
        with pytest.raises(ValueError, match=r"cannot regress.*finalize_handed_off.*finalize_ready"):
            _on_enter_finalize_ready(state, _ctx(tmp_path))


# ---------------------------------------------------------------------------
# _on_enter_prepared grounding git failure (I-12)
# ---------------------------------------------------------------------------

_LIFECYCLE_MODULE = "teleclaude.core.next_machine.work_lifecycle"


def test_prepared_raises_when_git_rev_parse_fails(tmp_path: Path) -> None:
    """Raises ValueError when git rev-parse HEAD fails during prepare — grounding cannot be established."""
    todo_dir = tmp_path / "todos" / "test-slug"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("## Req\nContent here\n")
    (todo_dir / "implementation-plan.md").write_text("## Plan\nContent here\n")

    with patch(f"{_LIFECYCLE_MODULE}.run_git_command", return_value=(1, "", "fatal: not a git repo")):
        with pytest.raises(ValueError, match="git rev-parse HEAD failed"):
            _on_enter_prepared({}, _ctx(tmp_path))


def test_prepared_raises_when_git_returns_empty_sha(tmp_path: Path) -> None:
    """Raises ValueError when git rev-parse HEAD returns empty — no baseline to ground against."""
    todo_dir = tmp_path / "todos" / "test-slug"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("## Req\nContent here\n")
    (todo_dir / "implementation-plan.md").write_text("## Plan\nContent here\n")

    with patch(f"{_LIFECYCLE_MODULE}.run_git_command", return_value=(0, "", "")):
        with pytest.raises(ValueError, match="git rev-parse HEAD failed"):
            _on_enter_prepared({}, _ctx(tmp_path))
