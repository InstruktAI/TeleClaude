"""Tests for prepare step handlers — phase dispatch behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine.prepare_steps import (
    _prepare_step_input_assessment,
    _prepare_step_plan_drafting,
    _prepare_step_triangulation,
)

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]

_STEPS = "teleclaude.core.next_machine.prepare_steps"


def _base_state(
    lifecycle_phase: str = "input_assessment",
    *,
    requirements_produced_at: str = "",
    requirements_digest: str = "",
    input_digest: str = "",
    plan_produced_at: str = "",
    plan_digest: str = "",
) -> dict:
    return {
        "schema_version": 2,
        "phase": "pending",
        "lifecycle_phase": lifecycle_phase,
        "kind": "todo",
        "artifacts": {
            "input": {"digest": input_digest, "produced_at": "", "stale": False, "approved": False, "confirmed": False},
            "requirements": {
                "digest": requirements_digest,
                "produced_at": requirements_produced_at,
                "stale": False,
                "approved": False,
                "confirmed": False,
            },
            "test_specs": {"digest": "", "produced_at": "", "stale": False, "approved": False, "confirmed": False},
            "implementation_plan": {
                "digest": plan_digest,
                "produced_at": plan_produced_at,
                "stale": False,
                "approved": False,
                "confirmed": False,
            },
        },
        "requirements_review": {"verdict": "", "reviewed_at": "", "findings_count": 0, "rounds": 0},
        "test_spec_review": {"verdict": "", "reviewed_at": "", "findings_count": 0, "rounds": 0},
        "plan_review": {"verdict": "", "reviewed_at": "", "findings_count": 0, "rounds": 0},
        "grounding": {"valid": False, "base_sha": "", "input_digest": "", "referenced_paths": []},
    }


@pytest.mark.asyncio
async def test_input_assessment_dispatches_discovery_when_produced_at_empty() -> None:
    """INPUT_ASSESSMENT must dispatch discovery when requirements.produced_at is empty,
    even when the requirements artifact exists in the DB. This is the mark-phase rewind
    scenario: produced_at was cleared but the artifact content still exists."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="req-digest")
    todos_db.write_state = AsyncMock()

    state = _base_state(requirements_digest="req-digest", input_digest="input-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
        patch(f"{_STEPS}.prepare_pair_agent_mapping", return_value={"A": "claude", "B": "codex"}),
        patch(f"{_STEPS}._derive_project_root", return_value="/repo"),
    ):
        keep_going, instruction = await _prepare_step_input_assessment(db, todos_db, "my-slug", "/repo", state)

    # Must NOT auto-advance — must dispatch discovery
    assert keep_going is False
    assert instruction  # non-empty dispatch instruction


@pytest.mark.asyncio
async def test_input_assessment_advances_when_produced_at_is_set() -> None:
    """INPUT_ASSESSMENT advances when requirements.produced_at is set — the phase was
    completed in this lifecycle pass (normal stamp-driven flow)."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="req-digest")
    todos_db.write_state = AsyncMock()

    state = _base_state(
        requirements_produced_at="2026-01-01T00:00:00+00:00",
        requirements_digest="req-digest",
        input_digest="input-digest",
    )

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, _ = await _prepare_step_input_assessment(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is True


@pytest.mark.asyncio
async def test_triangulation_dispatches_discovery_when_produced_at_empty() -> None:
    """TRIANGULATION must dispatch discovery when requirements.produced_at is empty,
    even when the requirements artifact exists in the DB."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="req-digest")
    todos_db.write_state = AsyncMock()

    state = _base_state(lifecycle_phase="triangulation", requirements_digest="req-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
        patch(f"{_STEPS}.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"),
        patch(f"{_STEPS}._derive_project_root", return_value="/repo"),
    ):
        keep_going, instruction = await _prepare_step_triangulation(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is False
    assert instruction


@pytest.mark.asyncio
async def test_plan_drafting_dispatches_drafter_when_produced_at_empty() -> None:
    """PLAN_DRAFTING must dispatch drafter when implementation_plan.produced_at is empty,
    even when the plan artifact exists in the DB."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="plan-digest")
    todos_db.write_state = AsyncMock()

    state = _base_state(lifecycle_phase="plan_drafting", plan_digest="plan-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
        patch(f"{_STEPS}.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"),
        patch(f"{_STEPS}._derive_project_root", return_value="/repo"),
    ):
        keep_going, instruction = await _prepare_step_plan_drafting(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is False
    assert instruction
