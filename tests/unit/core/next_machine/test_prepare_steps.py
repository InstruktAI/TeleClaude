"""Tests for v2 prepare phase dispatch behavior.

Output is a verbatim execution script. We snapshot the rendered output to lock
the wording at the boundary and rely on the snapshot diff to catch regressions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

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


@pytest.mark.asyncio
async def test_prd_drafting_loads_intake_skill(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.PRD_DRAFTING)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_architecture_drafting_loads_architecture_skill(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.ARCHITECTURE_DRAFTING)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_architecture_review_dispatches_to_reviewer(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.ARCHITECTURE_REVIEW)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_test_specs_drafting_loads_specs_skill(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.TEST_SPECS_DRAFTING)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_plan_drafting_loads_plan_skill(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.PLAN_DRAFTING)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_test_specs_review_dispatches_to_reviewer(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.TEST_SPECS_REVIEW)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_plan_review_dispatches_to_plan_review(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.PLAN_REVIEW)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_prd_human_approval_emits_stamp_instruction(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.PRD_HUMAN_APPROVAL)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_blocked_pending_drift_dispatches_drift_analyzer(snapshot: SnapshotAssertion) -> None:
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
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_blocked_no_drift_emits_blocker_resolution(snapshot: SnapshotAssertion) -> None:
    db = AsyncMock()
    todos_db = AsyncMock()
    state = {"schema_version": 3, "lifecycle_phase": "blocked", "artifacts": {}}
    with (
        patch(f"{_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
        patch(f"{_STEPS}.derive_prepare_drift", return_value={}),
        patch(
            f"{_STEPS}.prepare_blockers",
            return_value=["architecture artifact is present but required upstream prd is missing"],
        ),
    ):
        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=PreparePhase.BLOCKED,
            state=state,
        )
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_prepared_delegates_to_terminal_formatter() -> None:
    with patch(f"{_STEPS}._prepare_step_prepared", new=AsyncMock(return_value=(False, "PREPARED: my-slug"))):
        keep_going, instruction = await _dispatch(PreparePhase.PREPARED)
    assert keep_going is False
    assert instruction == "PREPARED: my-slug"
