"""Tests for prepare step handlers — phase dispatch behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine.prepare_steps import (
    _prepare_step_input_assessment,
    _prepare_step_plan_drafting,
    _prepare_step_re_grounding,
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


# --- INPUT_ASSESSMENT ---


@pytest.mark.asyncio
async def test_input_assessment_dispatches_when_digest_matches_db() -> None:
    """After mark-phase rewind, state digest is hydrated from DB. When it matches
    the DB digest, the artifact is stale — dispatch discovery instead of advancing."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="req-digest")
    todos_db.write_state = AsyncMock()

    # State digest matches DB digest — mark-phase hydration scenario
    state = _base_state(requirements_digest="req-digest", input_digest="input-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
        patch(f"{_STEPS}.prepare_pair_agent_mapping", return_value={"A": "claude", "B": "codex"}),
        patch(f"{_STEPS}._derive_project_root", return_value="/repo"),
    ):
        keep_going, instruction = await _prepare_step_input_assessment(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is False
    assert instruction


@pytest.mark.asyncio
async def test_input_assessment_advances_when_db_digest_differs_from_state() -> None:
    """When a worker writes new requirements (digest differs from state), the handler
    detects the change and advances — the normal re-entry flow."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="new-digest")
    todos_db.write_state = AsyncMock()

    # State has old digest, DB has new — worker wrote new content
    state = _base_state(requirements_digest="old-digest", input_digest="input-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, _ = await _prepare_step_input_assessment(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is True


@pytest.mark.asyncio
async def test_input_assessment_advances_when_state_digest_empty() -> None:
    """When state has no prior digest (fresh todo), any DB artifact is new — advance."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="req-digest")
    todos_db.write_state = AsyncMock()

    state = _base_state(requirements_digest="", input_digest="input-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, _ = await _prepare_step_input_assessment(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is True


@pytest.mark.asyncio
async def test_input_assessment_advances_when_produced_at_is_set() -> None:
    """INPUT_ASSESSMENT advances when requirements.produced_at is set — the phase was
    completed in this lifecycle pass (normal stamp-driven flow)."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.write_state = AsyncMock()

    state = _base_state(
        requirements_produced_at="2026-01-01T00:00:00+00:00",
        requirements_digest="req-digest",
        input_digest="input-digest",
    )

    with patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock):
        keep_going, _ = await _prepare_step_input_assessment(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is True


# --- TRIANGULATION ---


@pytest.mark.asyncio
async def test_triangulation_dispatches_when_digest_matches_db() -> None:
    """TRIANGULATION must dispatch discovery when state digest matches DB digest."""
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
async def test_triangulation_advances_when_db_digest_differs() -> None:
    """TRIANGULATION advances when worker wrote new requirements (digest changed)."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="new-digest")
    todos_db.write_state = AsyncMock()

    state = _base_state(lifecycle_phase="triangulation", requirements_digest="old-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, _ = await _prepare_step_triangulation(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is True


# --- PLAN_DRAFTING ---


@pytest.mark.asyncio
async def test_plan_drafting_dispatches_when_digest_matches_db() -> None:
    """PLAN_DRAFTING must dispatch drafter when state digest matches DB digest."""
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


@pytest.mark.asyncio
async def test_plan_drafting_advances_when_db_digest_differs() -> None:
    """PLAN_DRAFTING advances when worker wrote new plan (digest changed)."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="new-plan-digest")
    todos_db.write_state = AsyncMock()

    state = _base_state(lifecycle_phase="plan_drafting", plan_digest="old-plan-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, _ = await _prepare_step_plan_drafting(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is True


# --- RE_GROUNDING ---


@pytest.mark.asyncio
async def test_re_grounding_dispatches_when_digest_matches_db() -> None:
    """RE_GROUNDING must dispatch drafter when state digest matches DB digest."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="plan-digest")
    todos_db.write_state = AsyncMock()

    state = _base_state(lifecycle_phase="re_grounding", plan_digest="plan-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"),
        patch(f"{_STEPS}._derive_project_root", return_value="/repo"),
    ):
        keep_going, instruction = await _prepare_step_re_grounding(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is False
    assert instruction


@pytest.mark.asyncio
async def test_re_grounding_advances_when_db_digest_differs() -> None:
    """RE_GROUNDING advances when worker updated the plan (digest changed)."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="new-plan-digest")
    todos_db.write_state = AsyncMock()

    state = _base_state(lifecycle_phase="re_grounding", plan_digest="old-plan-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, _ = await _prepare_step_re_grounding(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is True
