"""Unit tests for work state machine step handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine.work_steps import (
    _work_step_build_complete,
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
async def test_build_started_waits_for_builder_completion_stamp() -> None:
    """A live builder owns the explicit build_complete stamp."""
    state = _base_state()

    with patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="sess-123")):
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
    assert "telec todo stamp test-slug --build-complete" in instruction


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
async def test_review_changes_requested_waits_for_fix_completion_stamp_after_commits() -> None:
    """Committed fixes are evidence only until the builder stamps completion."""
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
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="builder-1")),
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
    assert "FIX WORK NOT STAMPED" in instruction
    assert "telec todo stamp test-slug --build-complete" in instruction


@pytest.mark.asyncio
async def test_review_changes_requested_relay_message_addresses_every_finding() -> None:
    """Relay to a live builder names every finding tier and forbids the Suggestion bucket.

    Pins the Severity tier overhaul: the message must instruct the builder to address
    every finding (no "non-Suggestion" qualifier), reference the three-tier schema,
    and direct the builder to the build-complete stamp on completion.
    """
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
        patch(f"{_WORK_STEPS}.get_head_commit", return_value="aaa111"),
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="builder-1")),
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
    assert "REVIEW CHANGES REQUESTED: test-slug" in instruction
    assert "Requirement-Violation, Critical, and Important" in instruction
    assert "Suggestion" not in instruction


@pytest.mark.asyncio
async def test_build_complete_round_limit_message_has_no_suggestion_floor() -> None:
    """Round-limit message must not promise approval for Suggestion-only findings.

    Pins the orchestration round-limit overhaul: the message must state that round
    limit is not an escape hatch, reference the three-tier schema, and direct the
    orchestrator to escalate to the human if the loop is stuck — never to approve
    on a Suggestion floor.
    """
    state: dict = {
        "lifecycle_phase": "build_complete",
        "build_review": {"round": 99},  # exceeds DEFAULT_MAX_REVIEW_ROUNDS
    }

    keep_going, instruction = await _work_step_build_complete(
        db=_mock_db(),
        todos_db=_mock_todos_db(),
        slug="test-slug",
        cwd="/project",
        worktree_cwd="/project/trees/test-slug",
        state=state,
        head_before_merge="aaa111",
        head_after_merge="aaa111",
    )

    assert keep_going is False
    assert "REVIEW_ROUND_LIMIT" in instruction
    assert "Suggestion" not in instruction
