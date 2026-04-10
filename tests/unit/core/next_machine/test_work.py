"""Characterization tests for next-work precondition and routing helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine._types import PhaseStatus
from teleclaude.core.next_machine.work import (
    _dispatch_pre_review,
    _dispatch_review_approved,
    _DispatchState,
    _resolve_explicit_work_slug,
    _validate_work_preconditions,
    next_work,
)


def _mock_todos_db(**overrides: object) -> AsyncMock:
    """Build a mock TodosDb with default method returns."""
    db = AsyncMock()
    db.is_bug_todo = AsyncMock(return_value=overrides.get("is_bug", False))
    db.has_pending_deferrals = AsyncMock(return_value=overrides.get("has_deferrals", False))
    db.slug_in_roadmap = AsyncMock(return_value=overrides.get("in_roadmap", True))
    db.add_to_roadmap = AsyncMock(return_value=True)
    db.load_deps = AsyncMock(return_value=overrides.get("deps", {}))
    db.read_state = AsyncMock(return_value=overrides.get("state", None))
    return db


@pytest.mark.asyncio
async def test_next_work_reports_no_ready_items_when_resolution_finds_nothing() -> None:
    """When the work queue is empty, the state machine must emit NO_READY_ITEMS
    AND `telec sessions end self` to close the orchestrator. Without self-end
    the orchestrator would hang indefinitely at an empty queue."""
    db = AsyncMock()
    todos_db = _mock_todos_db()

    with (
        patch("teleclaude.core.next_machine.work._normalize_next_work_cwd", return_value="/repo"),
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
        patch(
            "teleclaude.core.next_machine.work.resolve_slug_async", side_effect=[(None, False, ""), (None, False, "")]
        ),
    ):
        result = await next_work(db, None, "/repo")

    assert "NO_READY_ITEMS" in result
    assert "telec sessions end self" in result


@pytest.mark.asyncio
async def test_validate_work_preconditions_reports_stash_debt_when_git_stash_exists() -> None:
    with patch("teleclaude.core.next_machine.work.get_stash_entries", return_value=["stash@{0}: WIP on main"]):
        error = await _validate_work_preconditions("/repo", "slug-stash")

    assert error is not None


@pytest.mark.asyncio
async def test_resolve_explicit_work_slug_prefers_worktree_state_for_readiness_checks(tmp_path: Path) -> None:
    worktree_path = tmp_path / "trees" / "slug-review"
    worktree_path.mkdir(parents=True)
    todos_db = _mock_todos_db()

    with (
        patch(
            "teleclaude.core.next_machine.work._resolve_holder_slug",
            new=AsyncMock(return_value=("slug-review", None)),
        ),
        patch(
            "teleclaude.core.next_machine.work._get_item_phase_db",
            new=AsyncMock(return_value="pending"),
        ),
        patch(
            "teleclaude.core.next_machine.work._validate_explicit_slug_readiness",
            new=AsyncMock(return_value=None),
        ),
    ):
        resolved, error = await _resolve_explicit_work_slug(todos_db, "slug-review", "slug-review", 0.0)

    assert (resolved, error) == ("slug-review", None)


@pytest.mark.asyncio
async def test_dispatch_pre_review_routes_incomplete_builds_to_next_build() -> None:
    db = AsyncMock()
    todos_db = _mock_todos_db()
    dispatch_state = _DispatchState(
        state={},
        build_status=PhaseStatus.PENDING.value,
        review_status=PhaseStatus.PENDING.value,
        finalize_state={"status": "pending"},
    )

    with (
        patch("teleclaude.core.next_machine.work._merge_origin_main_into_worktree", return_value=None),
        patch("teleclaude.core.next_machine.work.compose_agent_guidance", return_value="guidance"),
    ):
        result = await _dispatch_pre_review(
            db,
            todos_db,
            "/repo",
            "/repo/trees/slug-build",
            "slug-build",
            "slug-build",
            0.0,
            dispatch_state,
        )

    assert result


@pytest.mark.asyncio
async def test_dispatch_pre_review_routes_completed_builds_to_review_dispatch() -> None:
    db = AsyncMock()
    todos_db = _mock_todos_db()
    dispatch_state = _DispatchState(
        state={"review_round": 0},
        build_status=PhaseStatus.COMPLETE.value,
        review_status=PhaseStatus.PENDING.value,
        finalize_state={"status": "pending"},
    )

    with (
        patch("teleclaude.core.next_machine.work.run_build_gates", return_value=(True, "")),
        patch("teleclaude.core.next_machine.work.verify_artifacts", return_value=(True, "")),
        patch("teleclaude.core.next_machine.work._is_review_round_limit_reached", return_value=(False, 0, 3)),
        patch("teleclaude.core.next_machine.work.compose_agent_guidance", return_value="guidance"),
        patch("teleclaude.core.next_machine.work._review_scope_note", return_value=""),
    ):
        result = await _dispatch_pre_review(
            db,
            todos_db,
            "/repo",
            "/repo/trees/slug-review",
            "slug-review",
            "slug-review",
            0.0,
            dispatch_state,
        )

    assert result


@pytest.mark.asyncio
async def test_dispatch_review_approved_routes_to_finalize_when_no_deferrals_are_pending() -> None:
    db = AsyncMock()
    todos_db = _mock_todos_db()
    emit_review_approved_mock = AsyncMock()
    dispatch_state = _DispatchState(
        state={},
        build_status=PhaseStatus.COMPLETE.value,
        review_status=PhaseStatus.APPROVED.value,
        finalize_state={"status": "pending"},
    )

    with (
        patch("teleclaude.core.next_machine.work.has_uncommitted_changes", return_value=False),
        patch("teleclaude.core.next_machine.work.compose_agent_guidance", return_value="guidance"),
        patch("teleclaude.core.next_machine.work.emit_review_approved", new=emit_review_approved_mock),
        patch("teleclaude.core.next_machine.work.get_session_id", return_value=None),
    ):
        result = await _dispatch_review_approved(
            db,
            todos_db,
            "/repo",
            "/repo/trees/slug-finalize",
            "slug-finalize",
            "slug-finalize",
            0.0,
            dispatch_state,
        )

    emit_review_approved_mock.assert_awaited_once()
    assert result


# ---------------------------------------------------------------------------
# Session lifecycle — fix-forward relay to live builder on review changes
# ---------------------------------------------------------------------------


class _FakeSession:  # pylint: disable=too-few-public-methods
    def __init__(self, session_id: str, title: str, subdir: str) -> None:
        self.session_id = session_id
        self.title = title
        self.subdir = subdir


@pytest.mark.asyncio
async def test_review_changes_requested_relays_findings_to_live_builder() -> None:
    """When the reviewer stamps CHANGES_REQUESTED, the work state machine must send
    findings to the existing builder via telec sessions send instead of dispatching
    a fresh fixer session. Catches the context-loss bug where every review round
    spawned a new fixer."""
    dispatch_state = _DispatchState(
        state={},
        build_status=PhaseStatus.COMPLETE.value,
        review_status=PhaseStatus.CHANGES_REQUESTED.value,
        finalize_state={"status": "pending"},
    )

    builder = _FakeSession("bld-keep", "/next-build slug-relay", "trees/slug-relay")
    reviewer = _FakeSession("rev-keep", "/next-review-build slug-relay", "trees/slug-relay")
    db = AsyncMock()
    db.list_sessions = AsyncMock(return_value=[builder, reviewer])
    todos_db = _mock_todos_db()

    result = await _dispatch_pre_review(
        db,
        todos_db,
        "/repo",
        "/repo/trees/slug-relay",
        "slug-relay",
        "slug-relay",
        0.0,
        dispatch_state,
    )

    # Must relay to the existing builder, not dispatch a fresh fixer
    assert "telec sessions send bld-keep" in result
    assert "telec sessions run" not in result
    # Must reference the fix procedure
    assert "software-development/procedure/lifecycle/fix-review-findings" in result
    # Must NOT end any session — the fix round is iterative, not terminal
    assert "telec sessions end" not in result
    # The reviewer is still alive; the script must wait on its next idle
    assert "rev-keep" in result
