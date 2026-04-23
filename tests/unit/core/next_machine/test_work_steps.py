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
        "dor": {"score": dor_score, "status": "pass"},
        "lifecycle_phase": lifecycle_phase,
    }


# ── _work_step_build_started: waiting/dispatch ──────────────────────────────


@pytest.mark.asyncio
async def test_build_started_waits_for_explicit_build_complete_stamp_when_gates_pass() -> None:
    """Passing gates do not advance phase until the builder stamps build_complete."""
    state = _base_state()

    with (
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="sess-123")),
        patch(f"{_WORK_STEPS}.has_build_commits_beyond_main", return_value=True),
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

    assert keep_going is False
    assert "build-complete" in instruction
    assert state["lifecycle_phase"] == "build_started"


@pytest.mark.asyncio
async def test_build_started_returns_gate_failure_when_gates_fail() -> None:
    """When builder is dispatched and commits exist but gates fail, return gate failure output."""
    state = _base_state()

    with (
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="sess-123")),
        patch(f"{_WORK_STEPS}.has_build_commits_beyond_main", return_value=True),
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
        patch(f"{_WORK_STEPS}.has_build_commits_beyond_main", return_value=False),
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


@pytest.mark.asyncio
async def test_build_started_bug_skips_dor_gate_and_dispatches() -> None:
    """Bug lanes must dispatch build work even when DOR is not pass."""
    state = {
        "kind": "bug",
        "dor": {"score": 0, "status": "needs_work"},
        "lifecycle_phase": "build_started",
    }
    dispatched = object()
    blocked = object()

    with (
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value=None)),
        patch(f"{_WORK_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
        patch(f"{_WORK_STEPS}.format_tool_call", return_value=dispatched),
        patch(f"{_WORK_STEPS}.format_error", return_value=blocked),
    ):
        keep_going, instruction = await _work_step_build_started(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="bug-slug",
            cwd="/project",
            worktree_cwd="/project/trees/bug-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction is dispatched


# ── _work_step_review_changes_requested: waiting ─────────────────────────────


@pytest.mark.asyncio
async def test_review_changes_requested_waits_for_build_complete_stamp() -> None:
    """Committed fixes alone do not reopen review without an explicit build_complete stamp."""
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
    ):
        keep_going, instruction = await _work_step_review_changes_requested(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert "build-complete" in instruction
