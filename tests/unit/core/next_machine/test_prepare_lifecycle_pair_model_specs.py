"""Specs for the pair-based prepare lifecycle model.

# guard: no-companion
"""

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
    assert "telec sessions send <A_id> --direct" in instruction


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

    assert "telec sessions send session-a" in instruction
    assert "session-b" in instruction
    assert "telec sessions send session-b" not in instruction


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
    assert "telec sessions send session-a" not in instruction


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

    assert "update prepare_pair slot B" in instruction


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

    assert "PAIR WRITE TURN" in instruction
    assert "telec sessions send session-b" in instruction
    assert "session-a" in instruction
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
    assert "telec sessions send <A_id> --direct" in instruction
    assert "Store the prepare pair identity" in instruction


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

    assert "REQUIREMENTS HUMAN APPROVAL" in instruction
    assert "telec todo artifacts read format-human requirements" in instruction
    assert "telec todo stamp format-human --verdict approve --phase requirements_human_approval" in instruction
