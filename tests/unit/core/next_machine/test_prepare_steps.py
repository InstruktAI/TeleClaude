"""Tests for v2 prepare phase dispatch behavior."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine._types import PreparePhase
from teleclaude.core.next_machine.prepare_steps import _prepare_dispatch

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]

_STEPS = "teleclaude.core.next_machine.prepare_steps"


async def _dispatch(phase: PreparePhase) -> tuple[bool, str]:
    db = AsyncMock()
    todos_db = AsyncMock()
    with patch(f"{_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")):
        return await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=phase,
            state={"lifecycle_phase": phase.value},
        )


async def _assert_dispatches(phase: PreparePhase, command: str) -> None:
    keep_going, instruction = await _dispatch(phase)
    payload = json.loads(instruction)

    assert keep_going is False
    assert payload["recommended_command"] == command
    assert payload["recommended_args"] == "my-slug"


@pytest.mark.asyncio
async def test_prd_drafting_dispatches_to_intake_without_worktree_subfolder() -> None:
    await _assert_dispatches(PreparePhase.PRD_DRAFTING, "/next-prepare-intake")


@pytest.mark.asyncio
async def test_architecture_drafting_dispatches_to_architecture_without_worktree_subfolder() -> None:
    await _assert_dispatches(PreparePhase.ARCHITECTURE_DRAFTING, "/next-prepare-architecture")


@pytest.mark.asyncio
async def test_test_specs_drafting_dispatches_to_specs_without_worktree_subfolder() -> None:
    await _assert_dispatches(PreparePhase.TEST_SPECS_DRAFTING, "/next-prepare-specs")


@pytest.mark.asyncio
async def test_plan_review_dispatches_to_plan_review_without_worktree_subfolder() -> None:
    await _assert_dispatches(PreparePhase.PLAN_REVIEW, "/next-review-plan")


async def _assert_human_approval_instruction(phase: PreparePhase, artifact: str, stamp: str) -> None:
    keep_going, instruction = await _dispatch(phase)
    payload = json.loads(instruction)

    assert keep_going is False
    assert payload["recommended_command"] == "telec todo stamp"
    assert payload["recommended_args"] == f"my-slug {stamp}"
    assert payload["required_reads"] == [f"telec todo artifacts read my-slug {artifact}"]


@pytest.mark.asyncio
async def test_prd_human_approval_returns_prd_stamp_instruction() -> None:
    await _assert_human_approval_instruction(PreparePhase.PRD_HUMAN_APPROVAL, "prd", "--prd-approved")


@pytest.mark.asyncio
async def test_plan_human_approval_returns_plan_stamp_instruction() -> None:
    await _assert_human_approval_instruction(PreparePhase.PLAN_HUMAN_APPROVAL, "implementation-plan", "--plan-approved")


@pytest.mark.asyncio
async def test_blocked_pending_drift_dispatches_drift_analyzer() -> None:
    db = AsyncMock()
    todos_db = AsyncMock()
    state = {
        "schema_version": 3,
        "lifecycle_phase": "blocked",
        "artifacts": {
            "prd": {
                "digest": "prd",
                "codebase_sha_at_write": "base",
                "referenced_paths": ["src/app.py"],
            }
        },
    }
    with (
        patch(f"{_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
        patch(f"{_STEPS}.derive_prepare_drift", return_value={"prd": "pending"}),
        patch(f"{_STEPS}.prepare_blockers", return_value=["prd drift is pending; run drift analysis before prepared"]),
    ):
        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=PreparePhase.BLOCKED,
            state=state,
        )

    payload = json.loads(instruction)
    assert keep_going is False
    assert payload["recommended_command"] == "/next-drift-analyze"
    assert payload["blockers"] == ["prd drift is pending; run drift analysis before prepared"]


@pytest.mark.asyncio
async def test_prepared_delegates_to_terminal_formatter() -> None:
    with patch(f"{_STEPS}._prepare_step_prepared", new=AsyncMock(return_value=(False, "PREPARED: my-slug"))):
        keep_going, instruction = await _dispatch(PreparePhase.PREPARED)

    assert keep_going is False
    assert instruction == "PREPARED: my-slug"
