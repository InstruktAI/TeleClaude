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
    _select_precondition_root,
    _validate_required_artifacts,
    _validate_work_preconditions,
    next_work,
)


def test_select_precondition_root_prefers_worktree_when_required_artifacts_are_present(tmp_path: Path) -> None:
    worktree_todo = tmp_path / "trees" / "slug-a" / "todos" / "slug-a"
    worktree_todo.mkdir(parents=True)
    (worktree_todo / "requirements.md").write_text(
        "Real requirements content that passes scaffold checks.\n", encoding="utf-8"
    )
    (worktree_todo / "implementation-plan.md").write_text(
        "Real implementation plan content that passes checks.\n", encoding="utf-8"
    )

    root = _select_precondition_root(str(tmp_path), "slug-a", False)

    assert root == str(tmp_path / "trees" / "slug-a")


def test_validate_required_artifacts_returns_none_for_bug_with_bug_report(tmp_path: Path) -> None:
    bug_dir = tmp_path / "todos" / "bug-slug"
    bug_dir.mkdir(parents=True)
    (bug_dir / "bug.md").write_text(
        "Bug reproduction steps with enough concrete detail to pass the content gate.\n",
        encoding="utf-8",
    )

    error = _validate_required_artifacts(str(tmp_path), "bug-slug", True)

    assert error is None


def test_validate_required_artifacts_reports_not_prepared_for_missing_plan_in_repo_root(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-b"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text(
        "Real requirements content that passes scaffold checks.\n", encoding="utf-8"
    )

    error = _validate_required_artifacts(str(tmp_path), "slug-b", False)

    assert error is not None
    assert "ERROR: NOT_PREPARED" in error
    assert "telec todo prepare slug-b" in error


@pytest.mark.asyncio
async def test_next_work_reports_no_ready_items_when_resolution_finds_nothing() -> None:
    db = AsyncMock()

    with (
        patch("teleclaude.core.next_machine.work._normalize_next_work_cwd", return_value="/repo"),
        patch("teleclaude.core.next_machine.work.sweep_completed_groups"),
        patch(
            "teleclaude.core.next_machine.work.resolve_slug_async", side_effect=[(None, False, ""), (None, False, "")]
        ),
        patch("teleclaude.core.next_machine.work.load_roadmap_deps", return_value={}),
    ):
        result = await next_work(db, None, "/repo")

    assert "ERROR: NO_READY_ITEMS" in result


@pytest.mark.asyncio
async def test_validate_work_preconditions_reports_stash_debt_when_git_stash_exists() -> None:
    with patch("teleclaude.core.next_machine.work.get_stash_entries", return_value=["stash@{0}: WIP on main"]):
        error = await _validate_work_preconditions("/repo", "slug-stash", "slug-stash")

    assert error is not None
    assert "ERROR: STASH_DEBT" in error
    assert "1 git stash entry" in error


@pytest.mark.asyncio
async def test_dispatch_pre_review_routes_incomplete_builds_to_next_build() -> None:
    db = AsyncMock()
    dispatch_state = _DispatchState(
        state={},
        build_status=PhaseStatus.PENDING.value,
        review_status=PhaseStatus.PENDING.value,
        finalize_state={"status": "pending"},
    )

    with (
        patch("teleclaude.core.next_machine.work._merge_origin_main_into_worktree", return_value=None),
        patch("teleclaude.core.next_machine.work.compose_agent_guidance", return_value="guidance"),
        patch("teleclaude.core.next_machine.work.is_bug_todo", return_value=False),
    ):
        result = await _dispatch_pre_review(
            db,
            "/repo",
            "/repo/trees/slug-build",
            "slug-build",
            "slug-build",
            0.0,
            dispatch_state,
        )

    assert 'telec sessions run --command "/next-build" --args "slug-build"' in result
    assert "telec todo mark-phase slug-build --phase build --status started" in result


@pytest.mark.asyncio
async def test_dispatch_pre_review_routes_completed_builds_to_review_dispatch() -> None:
    db = AsyncMock()
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
        patch("teleclaude.core.next_machine.work.is_bug_todo", return_value=False),
    ):
        result = await _dispatch_pre_review(
            db,
            "/repo",
            "/repo/trees/slug-review",
            "slug-review",
            "slug-review",
            0.0,
            dispatch_state,
        )

    assert 'telec sessions run --command "/next-review-build" --args "slug-review"' in result
    assert "Review iteration: round 1/3." in result


@pytest.mark.asyncio
async def test_dispatch_review_approved_routes_to_finalize_when_no_deferrals_are_pending() -> None:
    db = AsyncMock()
    emit_review_approved = AsyncMock()
    dispatch_state = _DispatchState(
        state={},
        build_status=PhaseStatus.COMPLETE.value,
        review_status=PhaseStatus.APPROVED.value,
        finalize_state={"status": "pending"},
    )

    with (
        patch("teleclaude.core.next_machine.work.has_pending_deferrals", return_value=False),
        patch("teleclaude.core.next_machine.work.has_uncommitted_changes", return_value=False),
        patch("teleclaude.core.next_machine.work.compose_agent_guidance", return_value="guidance"),
        patch("teleclaude.core.next_machine.work.emit_review_approved", new=emit_review_approved),
        patch("teleclaude.core.next_machine.work.is_bug_todo", return_value=False),
    ):
        result = await _dispatch_review_approved(
            db,
            "/repo",
            "/repo/trees/slug-finalize",
            "slug-finalize",
            "slug-finalize",
            0.0,
            dispatch_state,
        )

    emit_review_approved.assert_awaited_once_with(
        slug="slug-finalize",
        reviewer_session_id="unknown",
        review_round=1,
    )
    assert 'telec sessions run --command "/next-finalize" --args "slug-finalize"' in result
