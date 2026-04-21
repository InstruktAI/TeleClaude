"""Unit tests for work state machine step handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine.work_steps import (
    _work_step_build_started,
    _work_step_review_changes_requested,
)

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]

_WORK_STEPS = "teleclaude.core.next_machine.work_steps"


def _mock_db() -> AsyncMock:
    return AsyncMock()


def _mock_todos_db() -> AsyncMock:
    db = AsyncMock()
    db.is_bug_todo = AsyncMock(return_value=False)
    return db


def _base_state(*, kind: str = "todo", dor_score: int = 8, lifecycle_phase: str = "build_started") -> dict:
    return {
        "kind": kind,
        "dor": {"score": dor_score},
        "lifecycle_phase": lifecycle_phase,
    }


# ── _work_step_build_started: advancement ────────────────────────────────────


@pytest.mark.asyncio
async def test_build_started_advances_when_builder_exists_and_gates_pass() -> None:
    """When builder is active, commits exist, and gates pass, loop to build_complete."""
    state = _base_state()

    with (
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="sess-123")),
        patch(f"{_WORK_STEPS}._has_build_commits_beyond_main", return_value=True),
        patch(f"{_WORK_STEPS}.run_build_gates", return_value=(True, "GATE PASSED")),
    ):
        keep_going, instruction = await _work_step_build_started(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is True
    assert instruction == ""
    assert state["lifecycle_phase"] == "build_started"


@pytest.mark.asyncio
async def test_build_started_returns_gate_failure_when_gates_fail() -> None:
    """When builder is dispatched and commits exist but gates fail, return gate failure output."""
    state = _base_state()

    with (
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="sess-123")),
        patch(f"{_WORK_STEPS}._has_build_commits_beyond_main", return_value=True),
        patch(f"{_WORK_STEPS}.run_build_gates", return_value=(False, "GATE FAILED: scoped tests")),
    ):
        keep_going, instruction = await _work_step_build_started(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert "BUILD GATES FAILED" in instruction


@pytest.mark.asyncio
async def test_build_started_waits_when_builder_has_no_commits() -> None:
    """When builder exists but hasn't committed, return wait instruction."""
    state = _base_state()

    with (
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="sess-123")),
        patch(f"{_WORK_STEPS}._has_build_commits_beyond_main", return_value=False),
    ):
        keep_going, instruction = await _work_step_build_started(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert "BUILDER ACTIVE" in instruction
    assert "no commits beyond main" in instruction


@pytest.mark.asyncio
async def test_build_started_dispatches_when_no_builder_exists() -> None:
    """When no builder session exists, dispatch a fresh one."""
    state = _base_state()

    with (
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value=None)),
        patch(f"{_WORK_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
    ):
        keep_going, instruction = await _work_step_build_started(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert "STEP 1 - DISPATCH" in instruction


# ── _work_step_review_changes_requested: clearing ────────────────────────────


@pytest.mark.asyncio
async def test_review_changes_requested_clears_verdict_on_round_advance() -> None:
    """When builder committed fixes (HEAD != baseline), clear the review verdict and advance the round."""
    state: dict = {
        "lifecycle_phase": "review_changes_requested",
        "build_review": {
            "verdict": "changes_requested",
            "baseline_commit": "aaa111",
            "dispatch_head": "aaa111",
            "round": 0,
        },
    }

    with (
        patch(f"{_WORK_STEPS}.get_head_commit", return_value="bbb222"),
        patch(f"{_WORK_STEPS}._commit_writer", new=AsyncMock()) as mock_commit,
    ):
        keep_going, instruction = await _work_step_review_changes_requested(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is True
    assert instruction == ""
    writer_arg = mock_commit.call_args[0][0]
    assert writer_arg.state.build_review.verdict == ""
    assert writer_arg.state.build_review.reviewed_at == ""
    assert writer_arg.state.build_review.round == 1
