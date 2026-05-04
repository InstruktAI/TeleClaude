"""Specs for the pair-based prepare lifecycle model."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from teleclaude.constants import SlashCommand
from teleclaude.core.next_machine._types import PreparePhase
from teleclaude.core.next_machine.lifecycle import LifecyclePhase, apply_authoritative_signal, normalize_mark_phase
from teleclaude.core.next_machine.output_formatting import (
    ConvergenceAssessmentScript,
    HumanApprovalScript,
    PairFormationScript,
    PairTurnScript,
    format_convergence_assessment_script,
    format_human_approval_script,
    format_pair_formation_script,
    format_pair_turn_script,
)
from teleclaude.core.next_machine.prepare_steps import _prepare_dispatch
from teleclaude.core.next_machine.state_io import stamp_verdict
from teleclaude.core.next_machine.worktrees import EnsureWorktreeResult
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import PreparePair, PreparePairSlot, TodoState


def _pair_state() -> TodoState:
    state = TodoState.defaults()
    state.prepare_pair = PreparePair(
        slot_a=PreparePairSlot(session_id="session-a", agent="claude", lens="A"),
        slot_b=PreparePairSlot(session_id="session-b", agent="codex", lens="B"),
    )
    return state


def _pair_state_dict() -> dict[str, StateValue]:
    return cast(dict[str, StateValue], _pair_state().model_dump(exclude_none=True))


async def _stored_pair_state(todos_db: TodosDb, slug: str, phase: PreparePhase) -> dict[str, StateValue]:
    await todos_db.add_to_roadmap(slug)
    state = _pair_state_dict()
    state["phase"] = "in_progress"
    state["lifecycle_phase"] = phase.value
    await todos_db.write_state(slug, state)
    stored = await todos_db.read_state(slug)
    assert stored is not None
    return stored


def _session(
    session_id: str,
    *,
    subdir: str = "trees/convergence",
    title: str = "/next-prepare-discovery convergence",
    agent_stop_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        session_id=session_id,
        subdir=subdir,
        title=title,
        last_activity=agent_stop_at,
        last_message_sent_at=agent_stop_at,
        last_agent_stop_at=agent_stop_at,
    )


def _spy_worktree_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def _spy(project_root: str, slug: str) -> EnsureWorktreeResult:
        calls.append((project_root, slug))
        return EnsureWorktreeResult(created=False, prepared=False, prep_reason="test-spy")

    monkeypatch.setattr(
        "teleclaude.core.next_machine.prepare_steps.ensure_worktree_with_policy_async",
        _spy,
    )
    return calls


def test_todo_state_has_prepare_pair_with_two_typed_slots() -> None:
    state = _pair_state()

    round_tripped = TodoState.model_validate(state.model_dump(exclude_none=True))

    assert round_tripped.prepare_pair is not None
    assert round_tripped.prepare_pair.slot_a is not None
    assert round_tripped.prepare_pair.slot_a.session_id == "session-a"
    assert round_tripped.prepare_pair.slot_a.agent == "claude"
    assert round_tripped.prepare_pair.slot_a.lens == "A"
    assert round_tripped.prepare_pair.slot_b is not None
    assert round_tripped.prepare_pair.slot_b.session_id == "session-b"
    assert round_tripped.prepare_pair.slot_b.agent == "codex"
    assert round_tripped.prepare_pair.slot_b.lens == "B"


def test_prepare_pair_persists_across_input_assessment_through_plan_review() -> None:
    state = _pair_state()

    normalize_mark_phase(state, LifecyclePhase.PLAN_REVIEW)

    assert state.prepare_pair is not None
    assert state.prepare_pair.slot_a is not None
    assert state.prepare_pair.slot_a.session_id == "session-a"
    assert state.prepare_pair.slot_b is not None
    assert state.prepare_pair.slot_b.session_id == "session-b"


def test_prepare_pair_survives_mark_phase_rewind() -> None:
    state = _pair_state()
    state.lifecycle_phase = LifecyclePhase.PLAN_REVIEW.value

    normalize_mark_phase(state, LifecyclePhase.TRIANGULATION)

    assert state.prepare_pair is not None
    assert state.prepare_pair.slot_a is not None
    assert state.prepare_pair.slot_a.session_id == "session-a"
    assert state.prepare_pair.slot_b is not None
    assert state.prepare_pair.slot_b.session_id == "session-b"


def test_prepare_pair_cleared_at_prepared() -> None:
    state = _pair_state()
    state.lifecycle_phase = LifecyclePhase.GROUNDING_CHECK.value
    state.grounding.valid = True

    apply_authoritative_signal(state, "grounding")
    round_tripped = TodoState.model_validate(state.model_dump(exclude_none=True))

    assert LifecyclePhase(round_tripped.lifecycle_phase) is LifecyclePhase.PREPARED
    assert round_tripped.prepare_pair is None


def test_requirements_review_approve_advances_to_human_approval() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.REQUIREMENTS_REVIEW.value
    state.requirements_review.verdict = "approve"

    next_phase = apply_authoritative_signal(state, "verdict", phase="requirements_review")

    assert next_phase is LifecyclePhase.REQUIREMENTS_HUMAN_APPROVAL
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.REQUIREMENTS_HUMAN_APPROVAL


@pytest.mark.asyncio
async def test_human_approval_pauses_and_returns_approval_instruction(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("human-approval")
    await todos_db.write_state(
        "human-approval",
        {
            "schema_version": 2,
            "phase": "in_progress",
            "lifecycle_phase": "requirements_human_approval",
        },
    )
    state = await todos_db.read_state("human-approval")
    assert state is not None

    should_continue, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="human-approval",
        cwd="/repo",
        phase=PreparePhase.REQUIREMENTS_HUMAN_APPROVAL,
        state=state,
    )

    assert should_continue is False
    assert "requirements" in instruction
    assert "human" in instruction.lower()
    assert "telec todo stamp human-approval --verdict approve --phase requirements_human_approval" in instruction


@pytest.mark.asyncio
async def test_human_approval_survives_restart(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("human-approval-restart")
    await todos_db.write_state(
        "human-approval-restart",
        {
            "schema_version": 2,
            "phase": "in_progress",
            "lifecycle_phase": "requirements_human_approval",
        },
    )
    first_state = await todos_db.read_state("human-approval-restart")
    second_state = await todos_db.read_state("human-approval-restart")
    assert first_state is not None
    assert second_state is not None

    _, first_instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="human-approval-restart",
        cwd="/repo",
        phase=PreparePhase.REQUIREMENTS_HUMAN_APPROVAL,
        state=first_state,
    )
    _, second_instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="human-approval-restart",
        cwd="/repo",
        phase=PreparePhase.REQUIREMENTS_HUMAN_APPROVAL,
        state=second_state,
    )

    assert second_instruction == first_instruction


@pytest.mark.asyncio
async def test_human_approval_stamp_advances_to_test_spec_build(tmp_path: Path) -> None:
    db_path = tmp_path / ".teleclaude" / "todos.db"
    db_path.parent.mkdir()
    db = TodosDb(str(db_path))
    await db.initialize()
    await db.add_to_roadmap("human-approved")
    await db.write_state(
        "human-approved",
        {
            "schema_version": 2,
            "phase": "in_progress",
            "lifecycle_phase": "requirements_human_approval",
            "requirements_review": {"verdict": "approve"},
            "artifacts": {"requirements": {"digest": "digest", "produced_at": "now"}},
        },
    )

    stamp_verdict(str(tmp_path), "human-approved", "requirements_human_approval", "approve")
    state = await db.read_state("human-approved")

    assert state is not None
    assert state["lifecycle_phase"] == LifecyclePhase.TEST_SPEC_BUILD.value
    artifacts = state["artifacts"]
    assert isinstance(artifacts, dict)
    requirements = artifacts["requirements"]
    assert isinstance(requirements, dict)
    assert requirements["approved"] is True


@pytest.mark.asyncio
async def test_input_assessment_no_pair_emits_dual_dispatch_and_link(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("pair-dispatch")
    await todos_db.write_state(
        "pair-dispatch",
        {"schema_version": 2, "phase": "in_progress", "lifecycle_phase": "input_assessment"},
    )
    state = await todos_db.read_state("pair-dispatch")
    assert state is not None
    db = AsyncMock()
    db.list_sessions.return_value = [_session("session-a", subdir="trees/pair-existing")]

    should_continue, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="pair-dispatch",
        cwd="/repo",
        phase=PreparePhase.INPUT_ASSESSMENT,
        state=state,
    )

    assert should_continue is False
    assert instruction.count("telec sessions run") == 2
    assert '--agent "claude"' in instruction
    assert '--agent "codex"' in instruction
    # Workers are linked A↔B (not orchestrator↔A): A is told to --direct to B
    assert "telec sessions send <A_id>" in instruction
    assert "telec sessions send <B_id>" in instruction


@pytest.mark.asyncio
async def test_input_assessment_no_worktree(monkeypatch: pytest.MonkeyPatch, todos_db: TodosDb) -> None:
    calls = _spy_worktree_calls(monkeypatch)
    await todos_db.add_to_roadmap("input-no-worktree")
    await todos_db.write_state(
        "input-no-worktree",
        {"schema_version": 2, "phase": "in_progress", "lifecycle_phase": "input_assessment"},
    )
    state = await todos_db.read_state("input-no-worktree")
    assert state is not None
    db = AsyncMock()
    db.list_sessions.return_value = []

    await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="input-no-worktree",
        cwd="/repo",
        phase=PreparePhase.INPUT_ASSESSMENT,
        state=state,
    )

    assert calls == []


@pytest.mark.asyncio
async def test_input_assessment_existing_pair_targets_stored_a(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("pair-existing")
    await todos_db.write_state("pair-existing", _pair_state_dict())
    state = await todos_db.read_state("pair-existing")
    assert state is not None
    db = AsyncMock()
    db.list_sessions.return_value = [_session("session-a", subdir="trees/pair-existing")]

    should_continue, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="pair-existing",
        cwd="/repo",
        phase=PreparePhase.INPUT_ASSESSMENT,
        state=state,
    )

    assert should_continue is False
    assert "telec sessions send session-a" in instruction
    assert "telec sessions run" not in instruction


@pytest.mark.asyncio
async def test_pair_formation_uses_configurable_lens_agent_mapping(
    monkeypatch: pytest.MonkeyPatch,
    todos_db: TodosDb,
) -> None:
    monkeypatch.setenv("TELECLAUDE_PREPARE_PAIR_A_AGENT", "gemini")
    monkeypatch.setenv("TELECLAUDE_PREPARE_PAIR_B_AGENT", "claude")
    await todos_db.add_to_roadmap("pair-config")
    await todos_db.write_state(
        "pair-config",
        {"schema_version": 2, "phase": "in_progress", "lifecycle_phase": "input_assessment"},
    )
    state = await todos_db.read_state("pair-config")
    assert state is not None
    db = AsyncMock()
    db.list_sessions.return_value = []

    _, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="pair-config",
        cwd="/repo",
        phase=PreparePhase.INPUT_ASSESSMENT,
        state=state,
    )

    assert '--agent "gemini"' in instruction
    assert '--agent "claude"' in instruction


@pytest.mark.asyncio
async def test_workers_not_linked_during_intake(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("pair-independent")
    await todos_db.write_state(
        "pair-independent",
        {"schema_version": 2, "phase": "in_progress", "lifecycle_phase": "input_assessment"},
    )
    state = await todos_db.read_state("pair-independent")
    assert state is not None
    db = AsyncMock()
    db.list_sessions.return_value = []

    _, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="pair-independent",
        cwd="/repo",
        phase=PreparePhase.INPUT_ASSESSMENT,
        state=state,
    )

    run_lines = [line for line in instruction.splitlines() if line.startswith("telec sessions run")]
    assert len(run_lines) == 2
    assert all("--direct" not in line for line in run_lines)


@pytest.mark.asyncio
async def test_writer_messaged_reviewer_not_during_write_phase(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "writer-only", PreparePhase.TEST_SPEC_BUILD)

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="writer-only",
        cwd="/repo",
        phase=PreparePhase.TEST_SPEC_BUILD,
        state=state,
    )

    # Only the writer (A) is messaged during a write turn
    assert "telec sessions send session-a" in instruction
    assert "telec sessions send session-b" not in instruction


@pytest.mark.asyncio
async def test_requirements_review_dispatch_includes_diff_command_when_digest_changed(
    todos_db: TodosDb,
) -> None:
    """When requirements_review is dispatched after a digest change, the message includes the diff command."""
    await todos_db.add_to_roadmap("digest-changed")
    await todos_db.write_artifact("digest-changed", "requirements", "# v1\n")
    old_digest = await todos_db.artifact_digest("digest-changed", "requirements")
    await todos_db.write_artifact("digest-changed", "requirements", "# v2\n")
    new_digest = await todos_db.artifact_digest("digest-changed", "requirements")

    state = _pair_state_dict()
    state["phase"] = "in_progress"
    state["lifecycle_phase"] = PreparePhase.REQUIREMENTS_REVIEW.value
    # Reviewer previously approved at old_digest; verdict is empty so dispatch fires.
    state["requirements_review"] = {"verdict": "", "approved_digest": old_digest}
    state["artifacts"] = {
        "requirements": {"digest": old_digest, "produced_at": "2026-01-01T00:00:00+00:00"},
    }
    await todos_db.write_state("digest-changed", state)
    stored = await todos_db.read_state("digest-changed")
    assert stored is not None

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="digest-changed",
        cwd="/repo",
        phase=PreparePhase.REQUIREMENTS_REVIEW,
        state=stored,
    )

    assert f"telec todo artifacts diff digest-changed requirements {old_digest} {new_digest}" in instruction


@pytest.mark.asyncio
async def test_requirements_review_approve_clears_when_digest_no_longer_matches(
    todos_db: TodosDb,
) -> None:
    """A stale approve verdict (digest mismatch) is cleared and reviewer is re-dispatched."""
    await todos_db.add_to_roadmap("stale-approve")
    await todos_db.write_artifact("stale-approve", "requirements", "# v1\n")
    old_digest = await todos_db.artifact_digest("stale-approve", "requirements")
    await todos_db.write_artifact("stale-approve", "requirements", "# v2\n")
    new_digest = await todos_db.artifact_digest("stale-approve", "requirements")

    state = _pair_state_dict()
    state["phase"] = "in_progress"
    state["lifecycle_phase"] = PreparePhase.REQUIREMENTS_REVIEW.value
    # Approve verdict bound to the old digest
    state["requirements_review"] = {"verdict": "approve", "approved_digest": old_digest}
    state["artifacts"] = {
        "requirements": {"digest": old_digest, "produced_at": "2026-01-01T00:00:00+00:00"},
    }
    await todos_db.write_state("stale-approve", state)
    stored = await todos_db.read_state("stale-approve")
    assert stored is not None

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="stale-approve",
        cwd="/repo",
        phase=PreparePhase.REQUIREMENTS_REVIEW,
        state=stored,
    )

    # Should not return APPROVED — should dispatch reviewer with diff context
    assert "REQUIREMENTS REVIEW APPROVED" not in instruction
    assert f"telec todo artifacts diff stale-approve requirements {old_digest} {new_digest}" in instruction


@pytest.mark.asyncio
async def test_test_spec_build_dispatch_includes_upstream_diff_command(todos_db: TodosDb) -> None:
    """When test_spec_build is dispatched after upstream change, the message includes the requirements diff command."""
    await todos_db.add_to_roadmap("upstream-build")
    await todos_db.write_artifact("upstream-build", "requirements", "# req v1\n")
    old_req_digest = await todos_db.artifact_digest("upstream-build", "requirements")
    await todos_db.write_artifact("upstream-build", "requirements", "# req v2\n")
    new_req_digest = await todos_db.artifact_digest("upstream-build", "requirements")

    state = _pair_state_dict()
    state["phase"] = "in_progress"
    state["lifecycle_phase"] = PreparePhase.TEST_SPEC_BUILD.value
    # Specs were built against old requirements
    state["artifacts"] = {
        "requirements": {"digest": new_req_digest, "produced_at": "2026-01-01T00:00:00+00:00"},
        "test_specs": {
            "produced_at": "2026-01-01T00:00:00+00:00",
            "upstream_digests": {"requirements": old_req_digest},
        },
    }
    await todos_db.write_state("upstream-build", state)
    stored = await todos_db.read_state("upstream-build")
    assert stored is not None

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="upstream-build",
        cwd="/repo",
        phase=PreparePhase.TEST_SPEC_BUILD,
        state=stored,
    )

    assert f"telec todo artifacts diff upstream-build requirements {old_req_digest} {new_req_digest}" in instruction


@pytest.mark.asyncio
async def test_reviewer_messaged_only_after_writer_agent_stop(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "writer-stop", PreparePhase.PLAN_DRAFTING)

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="writer-stop",
        cwd="/repo",
        phase=PreparePhase.PLAN_DRAFTING,
        state=state,
    )

    assert "agent_stop" in instruction
    assert "telec sessions send session-b" in instruction
    assert "telec sessions send session-a" not in instruction


@pytest.mark.asyncio
async def test_needs_work_relays_findings_to_writer_fix_forward(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "requirements-fix", PreparePhase.REQUIREMENTS_REVIEW)
    state["requirements_review"] = {
        "verdict": "needs_work",
        "reviewed_at": "2026-04-25T00:00:00+00:00",
        "findings_count": 1,
        "rounds": 0,
        "baseline_commit": "",
        "findings": [{"id": "R1", "severity": "Important", "summary": "gap", "status": "open"}],
    }

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="requirements-fix",
        cwd="/repo",
        phase=PreparePhase.REQUIREMENTS_REVIEW,
        state=state,
    )

    assert "telec sessions send session-a" in instruction
    assert "/next-prepare-discovery" not in instruction
    persisted = await todos_db.read_state("requirements-fix")
    assert persisted is not None
    assert persisted["lifecycle_phase"] == PreparePhase.REQUIREMENTS_REVIEW.value


def test_no_back_to_discovery_on_needs_work() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.REQUIREMENTS_REVIEW.value
    state.requirements_review.verdict = "needs_work"

    next_phase = apply_authoritative_signal(state, "verdict", phase="requirements_review")

    assert next_phase is LifecyclePhase.REQUIREMENTS_REVIEW
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.REQUIREMENTS_REVIEW


def test_plan_review_approve_advances_to_grounding_not_gate() -> None:
    state = TodoState.defaults()
    state.lifecycle_phase = LifecyclePhase.PLAN_REVIEW.value
    state.plan_review.verdict = "approve"

    next_phase = apply_authoritative_signal(state, "verdict", phase="plan_review")

    assert next_phase is LifecyclePhase.GROUNDING_CHECK
    assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.GROUNDING_CHECK


@pytest.mark.asyncio
async def test_triangulation_targets_writer_a(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "triangulation-writer", PreparePhase.TRIANGULATION)

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="triangulation-writer",
        cwd="/repo",
        phase=PreparePhase.TRIANGULATION,
        state=state,
    )

    assert "telec sessions send session-a" in instruction


@pytest.mark.asyncio
async def test_triangulation_no_worktree(monkeypatch: pytest.MonkeyPatch, todos_db: TodosDb) -> None:
    calls = _spy_worktree_calls(monkeypatch)
    state = await _stored_pair_state(todos_db, "triangulation-no-worktree", PreparePhase.TRIANGULATION)

    await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="triangulation-no-worktree",
        cwd="/repo",
        phase=PreparePhase.TRIANGULATION,
        state=state,
    )

    assert calls == []


@pytest.mark.asyncio
async def test_requirements_review_targets_reviewer_b(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "requirements-reviewer", PreparePhase.REQUIREMENTS_REVIEW)

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="requirements-reviewer",
        cwd="/repo",
        phase=PreparePhase.REQUIREMENTS_REVIEW,
        state=state,
    )

    assert "telec sessions send session-b" in instruction
    assert "telec sessions run" not in instruction


@pytest.mark.asyncio
async def test_test_spec_build_targets_writer_a(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "spec-writer", PreparePhase.TEST_SPEC_BUILD)

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="spec-writer",
        cwd="/repo",
        phase=PreparePhase.TEST_SPEC_BUILD,
        state=state,
    )

    assert "telec sessions send session-a" in instruction


@pytest.mark.asyncio
async def test_test_spec_build_ensures_worktree(monkeypatch: pytest.MonkeyPatch, todos_db: TodosDb) -> None:
    calls = _spy_worktree_calls(monkeypatch)
    state = await _stored_pair_state(todos_db, "spec-worktree", PreparePhase.TEST_SPEC_BUILD)
    db = AsyncMock()
    db.list_sessions.return_value = [_session("session-a", subdir="trees/spec-worktree")]

    await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="spec-worktree",
        cwd="/repo",
        phase=PreparePhase.TEST_SPEC_BUILD,
        state=state,
    )

    assert calls == [("/repo", "spec-worktree")]


@pytest.mark.asyncio
async def test_test_spec_review_targets_reviewer_b(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "spec-reviewer", PreparePhase.TEST_SPEC_REVIEW)

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="spec-reviewer",
        cwd="/repo",
        phase=PreparePhase.TEST_SPEC_REVIEW,
        state=state,
    )

    assert "telec sessions send session-b" in instruction
    assert "telec sessions run" not in instruction


@pytest.mark.asyncio
async def test_plan_drafting_targets_writer_b_role_flip(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "plan-writer", PreparePhase.PLAN_DRAFTING)

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="plan-writer",
        cwd="/repo",
        phase=PreparePhase.PLAN_DRAFTING,
        state=state,
    )

    assert "telec sessions send session-b" in instruction
    assert "telec sessions send session-a" not in instruction


@pytest.mark.asyncio
async def test_plan_review_targets_reviewer_a_role_flip(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "plan-reviewer", PreparePhase.PLAN_REVIEW)

    _, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="plan-reviewer",
        cwd="/repo",
        phase=PreparePhase.PLAN_REVIEW,
        state=state,
    )

    assert "telec sessions send session-a" in instruction
    assert "telec sessions run" not in instruction


@pytest.mark.asyncio
async def test_convergence_instruction_emitted_after_discovery(todos_db: TodosDb) -> None:
    stopped_at = datetime(2026, 4, 25, tzinfo=UTC)
    state = await _stored_pair_state(todos_db, "convergence", PreparePhase.INPUT_ASSESSMENT)
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session("session-a", agent_stop_at=stopped_at),
        _session("session-b", agent_stop_at=stopped_at),
    ]

    _, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="convergence",
        cwd="/repo",
        phase=PreparePhase.INPUT_ASSESSMENT,
        state=state,
    )

    assert "CONVERGENCE ASSESSMENT" in instruction
    assert "telec sessions tail session-a" in instruction
    assert "telec sessions tail session-b" in instruction
    # Convergence script instructs orchestrator to tell A to close link and write
    assert "Close your direct link" in instruction
    assert "--close-link" in instruction


@pytest.mark.asyncio
async def test_continuation_targets_stored_pair_before_generic_lookup(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "stored-first", PreparePhase.TEST_SPEC_BUILD)
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session("session-a", subdir="trees/stored-first", title="/next-build-specs stored-first"),
        _session("generic-spec-worker", subdir="trees/stored-first", title="/next-build-specs stored-first"),
    ]

    _, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="stored-first",
        cwd="/repo",
        phase=PreparePhase.TEST_SPEC_BUILD,
        state=state,
    )

    assert "telec sessions send session-a" in instruction
    assert "generic-spec-worker" not in instruction


@pytest.mark.asyncio
async def test_revive_attempted_before_fresh_dispatch(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "revive-writer", PreparePhase.TEST_SPEC_BUILD)
    db = AsyncMock()
    db.list_sessions.return_value = []

    _, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="revive-writer",
        cwd="/repo",
        phase=PreparePhase.TEST_SPEC_BUILD,
        state=state,
    )

    assert instruction.index("telec sessions revive session-a") < instruction.index("telec sessions run")


@pytest.mark.asyncio
async def test_fresh_replacement_updates_pair_slot(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "replace-writer", PreparePhase.PLAN_DRAFTING)
    db = AsyncMock()
    db.list_sessions.return_value = []

    _, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="replace-writer",
        cwd="/repo",
        phase=PreparePhase.PLAN_DRAFTING,
        state=state,
    )

    # After dispatching the replacement, the orchestrator must atomically re-register
    # the pair via the stamp surface so state.prepare_pair sees the new session_id
    # alongside the surviving one. PLAN_DRAFTING uses the (B, A) writer/reviewer
    # role pair, so when the writer (B) is dead the surviving slot is A (session-a).
    assert "telec todo stamp replace-writer" in instruction
    assert "--agent-a session-a --agent-b <new_id>" in instruction


@pytest.mark.asyncio
async def test_native_revive_branch_carries_new_id_forward(todos_db: TodosDb) -> None:
    """When a slot stores native_session_id, recovery must instruct the orchestrator
    to revive natively, save the NEW TC id the API mints, send the pending message
    to it, and atomically re-stamp the pair with that new id. Without this, the
    stored slot stays stale and the next prepare re-entry loops back into recovery.
    """
    await todos_db.add_to_roadmap("native-revive")
    state_obj = TodoState.defaults()
    state_obj.prepare_pair = PreparePair(
        slot_a=PreparePairSlot(
            session_id="session-a",
            native_session_id="native-a-uuid",
            agent="claude",
            lens="A",
        ),
        slot_b=PreparePairSlot(
            session_id="session-b",
            native_session_id="native-b-uuid",
            agent="codex",
            lens="B",
        ),
    )
    state_obj.lifecycle_phase = PreparePhase.PLAN_DRAFTING.value
    state_dict = cast(dict[str, StateValue], state_obj.model_dump(exclude_none=True))
    state_dict["phase"] = "in_progress"
    await todos_db.write_state("native-revive", state_dict)
    stored = await todos_db.read_state("native-revive")
    assert stored is not None

    db = AsyncMock()
    db.list_sessions.return_value = []  # writer (B) is dead

    _, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="native-revive",
        cwd="/repo",
        phase=PreparePhase.PLAN_DRAFTING,
        state=stored,
    )

    # Native revive branch must be present and correctly wired:
    assert "telec sessions revive native-b-uuid --agent codex" in instruction
    # The API mints a fresh TC id — orchestrator must save it and use it forward:
    assert "Save the returned session_id as <new_id>" in instruction
    # Pending message must be sent to the NEW id, not the old (stale) one:
    assert "telec sessions send <new_id>" in instruction
    # And the pair must be re-stamped atomically with the surviving + new id:
    assert "telec todo stamp native-revive" in instruction
    assert "--agent-a session-a --agent-b <new_id>" in instruction


@pytest.mark.asyncio
async def test_legacy_slot_without_native_session_id_skips_native_revive(todos_db: TodosDb) -> None:
    """Slots created before the durability fix have no native_session_id. The
    recovery script must surface that explicitly and skip straight to fresh dispatch.
    """
    state = await _stored_pair_state(todos_db, "legacy-slot", PreparePhase.PLAN_DRAFTING)
    db = AsyncMock()
    db.list_sessions.return_value = []

    _, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="legacy-slot",
        cwd="/repo",
        phase=PreparePhase.PLAN_DRAFTING,
        state=state,
    )

    assert "no native_session_id stored" in instruction
    assert "skip native revival" in instruction
    # Fresh dispatch path is still emitted so recovery is possible:
    assert "telec sessions run --command" in instruction


@pytest.mark.asyncio
async def test_dead_reviewer_falls_back_to_fresh_dispatch(todos_db: TodosDb) -> None:
    state = await _stored_pair_state(todos_db, "dead-reviewer", PreparePhase.REQUIREMENTS_REVIEW)
    db = AsyncMock()
    db.list_sessions.return_value = []

    _, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="dead-reviewer",
        cwd="/repo",
        phase=PreparePhase.REQUIREMENTS_REVIEW,
        state=state,
    )

    assert "telec sessions revive session-b" in instruction
    assert 'telec sessions run --command "/next-review-requirements"' in instruction


@pytest.mark.asyncio
async def test_no_gate_worker_dispatched(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("gate-dissolved")
    await todos_db.write_state(
        "gate-dissolved",
        {"schema_version": 2, "phase": "in_progress", "lifecycle_phase": "gate"},
    )
    state = await todos_db.read_state("gate-dissolved")
    assert state is not None

    should_continue, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="gate-dissolved",
        cwd="/repo",
        phase=PreparePhase.GATE,
        state=state,
    )

    assert should_continue is True
    assert "/next-prepare-gate" not in instruction


@pytest.mark.asyncio
async def test_grounding_check_mechanical_no_pair_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    todos_db: TodosDb,
) -> None:
    def _run_git_command(args: list[str], cwd: str) -> tuple[int, str, str]:
        return (0, "head\n", "")

    monkeypatch.setattr("teleclaude.core.next_machine.prepare_steps.run_git_command", _run_git_command)
    state = await _stored_pair_state(todos_db, "grounding-fresh", PreparePhase.GROUNDING_CHECK)

    should_continue, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        todos_db=todos_db,
        slug="grounding-fresh",
        cwd="/repo",
        phase=PreparePhase.GROUNDING_CHECK,
        state=state,
    )

    assert should_continue is True
    assert instruction == ""
    persisted = await todos_db.read_state("grounding-fresh")
    assert persisted is not None
    assert persisted["lifecycle_phase"] == PreparePhase.PREPARED.value


@pytest.mark.asyncio
async def test_stale_grounding_targets_plan_writer_b(
    monkeypatch: pytest.MonkeyPatch,
    todos_db: TodosDb,
) -> None:
    def _run_git_command(args: list[str], cwd: str) -> tuple[int, str, str]:
        if args[0] == "diff":
            return (0, "teleclaude/core/example.py\n", "")
        return (0, "head\n", "")

    monkeypatch.setattr("teleclaude.core.next_machine.prepare_steps.run_git_command", _run_git_command)
    state = await _stored_pair_state(todos_db, "grounding-stale", PreparePhase.GROUNDING_CHECK)
    state["grounding"] = {
        "valid": True,
        "base_sha": "base",
        "input_digest": "",
        "referenced_paths": ["teleclaude/core/example.py"],
    }
    await todos_db.write_state("grounding-stale", state)
    stored = await todos_db.read_state("grounding-stale")
    assert stored is not None
    db = AsyncMock()
    db.list_sessions.return_value = [
        _session("session-a", subdir="trees/grounding-stale"),
        _session("session-b", subdir="trees/grounding-stale"),
    ]

    _, instruction = await _prepare_dispatch(
        db=db,
        todos_db=todos_db,
        slug="grounding-stale",
        cwd="/repo",
        phase=PreparePhase.GROUNDING_CHECK,
        state=stored,
    )

    # Stale grounding targets the plan writer (B), not a fresh dispatch
    assert "PAIR WRITE TURN" in instruction
    assert "telec sessions send session-b" in instruction
    assert "telec sessions run" not in instruction


def test_pair_formation_script_formats_dual_dispatch_and_link() -> None:
    instruction = format_pair_formation_script(
        PairFormationScript(
            command=SlashCommand.NEXT_PREPARE_DISCOVERY,
            args="format-pair",
            project="/repo",
            subfolder="trees/format-pair",
            agent_a="claude",
            agent_b="codex",
            slug="format-pair",
        )
    )

    assert instruction.count("telec sessions run") == 2
    # Workers are linked A↔B: A is told to --direct to B, B waits
    assert "telec sessions send <A_id>" in instruction
    assert "telec sessions send <B_id>" in instruction
    # The formation script registers the pair via stamp so the state machine
    # can see it on next re-entry. Without this step the formation script
    # would loop forever.
    assert "telec todo stamp format-pair --agent-a <A_id> --agent-b <B_id>" in instruction
    # Universal idle invariant prevents premature re-entry into the state machine
    assert "INVARIANT" in instruction
    # Discovery idleness clause must come before the re-enter step
    assert "Wait for BOTH <A_id> AND <B_id>" in instruction


def test_convergence_assessment_script_formats_tail_checks() -> None:
    instruction = format_convergence_assessment_script(
        ConvergenceAssessmentScript(slug="format-converge", slot_a="session-a", slot_b="session-b")
    )

    assert "CONVERGENCE ASSESSMENT" in instruction
    assert "telec sessions tail session-a" in instruction
    assert "telec sessions tail session-b" in instruction


def test_pair_turn_script_uses_send_for_review_not_run() -> None:
    instruction = format_pair_turn_script(
        PairTurnScript(
            slug="format-review",
            turn="review",
            session_id="session-b",
            message="Review now.",
            next_step="telec todo prepare format-review",
        )
    )

    assert "PAIR REVIEW TURN" in instruction
    assert 'telec sessions send session-b "Review now."' in instruction
    assert "telec sessions run" not in instruction


def test_human_approval_script_formats_stamp_instruction() -> None:
    instruction = format_human_approval_script(HumanApprovalScript(slug="format-human"))

    assert "HUMAN APPROVAL" in instruction
    assert "telec todo artifacts read format-human requirements" in instruction
    assert "telec todo stamp format-human --verdict approve --phase requirements_human_approval" in instruction
