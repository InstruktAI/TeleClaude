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
    _validate_required_artifacts,
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
async def test_validate_required_artifacts_returns_none_for_bug_with_bug_artifact() -> None:
    todos_db = _mock_todos_db()
    todos_db.artifact_exists = AsyncMock(return_value=True)

    error = await _validate_required_artifacts(todos_db, "bug-slug", True)

    assert error is None


@pytest.mark.asyncio
async def test_validate_required_artifacts_returns_error_for_bug_without_bug_artifact() -> None:
    todos_db = _mock_todos_db()
    todos_db.artifact_exists = AsyncMock(return_value=False)

    error = await _validate_required_artifacts(todos_db, "bug-slug", True)

    assert error is not None


@pytest.mark.asyncio
async def test_next_work_reports_no_ready_items_when_resolution_finds_nothing() -> None:
    db = AsyncMock()
    todos_db = _mock_todos_db()

    with (
        patch("teleclaude.core.next_machine.work._normalize_next_work_cwd", return_value="/repo"),
        patch("teleclaude.core.todos_db.get_todos_db", return_value=todos_db),
        patch("teleclaude.core.next_machine.work.sweep_completed_groups"),
        patch(
            "teleclaude.core.next_machine.work.resolve_slug_async", side_effect=[(None, False, ""), (None, False, "")]
        ),
    ):
        result = await next_work(db, None, "/repo")

    assert result


@pytest.mark.asyncio
async def test_validate_work_preconditions_reports_stash_debt_when_git_stash_exists() -> None:
    todos_db = _mock_todos_db()

    with patch("teleclaude.core.next_machine.work.get_stash_entries", return_value=["stash@{0}: WIP on main"]):
        error = await _validate_work_preconditions(todos_db, "/repo", "slug-stash", "slug-stash")

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
        patch("teleclaude.core.next_machine.work.get_item_phase", return_value="pending") as get_item_phase,
        patch(
            "teleclaude.core.next_machine.work._validate_explicit_slug_readiness",
            new=AsyncMock(return_value=None),
        ) as validate_readiness,
    ):
        resolved, error = await _resolve_explicit_work_slug(todos_db, str(tmp_path), "slug-review", "slug-review", 0.0)

    assert (resolved, error) == ("slug-review", None)
    get_item_phase.assert_called_once_with(str(worktree_path), "slug-review")
    validate_readiness.assert_awaited_once_with(
        str(worktree_path),
        "slug-review",
        "pending",
        {},
        False,
        "slug-review",
        0.0,
    )


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
