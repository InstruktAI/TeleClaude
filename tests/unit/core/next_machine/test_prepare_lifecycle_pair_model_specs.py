# guard: no-companion
# pyright: reportAttributeAccessIssue=false, reportCallIssue=false
# mypy: disable-error-code="comparison-overlap"
"""Test specs (xfail) for prepare-lifecycle-pair-model.

Pair-based discovery, turn-based writer/reviewer artifact production,
REQUIREMENTS_HUMAN_APPROVAL state, and dissolved gate.

All tests are marked xfail — they document the behavioral contract and fail
cleanly before implementation. Remove ``pytestmark`` xfail once all tests
pass after implementation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.next_machine._types import PreparePhase
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    apply_authoritative_signal,
    normalize_mark_phase,
    phase_is_complete,
)
from teleclaude.core.next_machine.prepare_steps import _prepare_dispatch
from teleclaude.types.todos import TodoState

pytestmark = [
    pytest.mark.unit,
    pytest.mark.timeout(10),
    pytest.mark.xfail(reason="spec: awaiting prepare-lifecycle-pair-model implementation"),
]


# ---------------------------------------------------------------------------
# R1: Pair identity in TodoState
# ---------------------------------------------------------------------------


class TestPairIdentity:
    """Pair slots must exist, persist across phases, survive rewinds, and clear at PREPARED."""

    def test_todo_state_has_prepare_pair_with_two_typed_slots(self) -> None:
        state = TodoState.defaults()

        pair = state.prepare_pair
        assert pair is not None
        assert hasattr(pair, "slot_a")
        assert hasattr(pair, "slot_b")
        # Empty before formation
        assert pair.slot_a is None
        assert pair.slot_b is None

    def test_prepare_pair_persists_across_input_assessment_through_plan_review(self) -> None:
        state = TodoState.defaults()
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a", agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(session_id="sess-b", agent="codex", lens="B")

        # Simulate advancing through phases — pair must survive
        for phase_value in [
            "input_assessment",
            "triangulation",
            "requirements_review",
            "requirements_human_approval",
            "test_spec_build",
            "test_spec_review",
            "plan_drafting",
            "plan_review",
        ]:
            state.lifecycle_phase = phase_value
            assert state.prepare_pair.slot_a.session_id == "sess-a"
            assert state.prepare_pair.slot_b.session_id == "sess-b"

    def test_prepare_pair_survives_mark_phase_rewind(self) -> None:
        state = TodoState.defaults()
        state.lifecycle_phase = LifecyclePhase.PLAN_REVIEW.value
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a", agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(session_id="sess-b", agent="codex", lens="B")

        normalize_mark_phase(state, LifecyclePhase.TRIANGULATION)

        assert state.prepare_pair.slot_a.session_id == "sess-a"
        assert state.prepare_pair.slot_b.session_id == "sess-b"

    def test_prepare_pair_cleared_at_prepared(self) -> None:
        state = TodoState.defaults()
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a")
        state.prepare_pair.slot_b = MagicMock(session_id="sess-b")
        state.lifecycle_phase = LifecyclePhase.GROUNDING_CHECK.value
        state.grounding.valid = True

        apply_authoritative_signal(state, "grounding")

        assert state.lifecycle_phase == LifecyclePhase.PREPARED.value
        assert state.prepare_pair.slot_a is None
        assert state.prepare_pair.slot_b is None


# ---------------------------------------------------------------------------
# R2: Pair formation at first dispatch
# ---------------------------------------------------------------------------


class TestPairFormation:
    """First dispatch must create both workers, keep them unlinked during intake."""

    @pytest.mark.asyncio
    async def test_input_assessment_no_pair_emits_dual_dispatch_and_link(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.INPUT_ASSESSMENT.value
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()
        todos_db.artifact_exists = AsyncMock(return_value=False)

        _keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="test-slug",
            cwd="/repo",
            phase=PreparePhase.INPUT_ASSESSMENT,
            state=raw_state,
        )

        assert not _keep_going
        # Must emit TWO session dispatches (one for each worker)
        assert instruction.count("telec sessions run") == 2
        # Must emit link instruction
        assert "--direct" in instruction

    def test_pair_formation_uses_configurable_lens_agent_mapping(self) -> None:
        state = TodoState.defaults()
        state.prepare_pair.slot_a = MagicMock(agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(agent="codex", lens="B")

        assert state.prepare_pair.slot_a.lens == "A"
        assert state.prepare_pair.slot_b.lens == "B"
        # Agent is the current default, not hardcoded identity
        assert state.prepare_pair.slot_a.agent == "claude"
        assert state.prepare_pair.slot_b.agent == "codex"

    @pytest.mark.asyncio
    async def test_input_assessment_existing_pair_targets_stored_a(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.INPUT_ASSESSMENT.value
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a", agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(session_id="sess-b", agent="codex", lens="B")
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()
        todos_db.artifact_exists = AsyncMock(return_value=False)

        _keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="test-slug",
            cwd="/repo",
            phase=PreparePhase.INPUT_ASSESSMENT,
            state=raw_state,
        )

        assert not _keep_going
        # Must target stored A session, not dispatch fresh
        assert "sess-a" in instruction
        assert instruction.count("telec sessions run") == 0

    @pytest.mark.asyncio
    async def test_workers_not_linked_during_intake(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.INPUT_ASSESSMENT.value
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()
        todos_db.artifact_exists = AsyncMock(return_value=False)

        _, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="test-slug",
            cwd="/repo",
            phase=PreparePhase.INPUT_ASSESSMENT,
            state=raw_state,
        )

        # The link (--direct) must come AFTER both agent_stop signals,
        # not in the same dispatch block
        lines = instruction.split("\n")
        dispatch_lines = [line for line in lines if "telec sessions run" in line]
        link_lines = [line for line in lines if "--direct" in line]
        assert len(dispatch_lines) == 2
        assert len(link_lines) == 1
        # Link instruction must reference waiting for agent_stop
        assert "agent_stop" in instruction.lower() or "wait" in instruction.lower()


# ---------------------------------------------------------------------------
# R4: REQUIREMENTS_HUMAN_APPROVAL state
# ---------------------------------------------------------------------------


class TestRequirementsHumanApproval:
    """Machine pauses for human approval after pair review of requirements."""

    def test_requirements_review_approve_advances_to_human_approval(self) -> None:
        state = TodoState.defaults()
        state.lifecycle_phase = LifecyclePhase.REQUIREMENTS_REVIEW.value
        state.requirements_review.verdict = "approve"
        state.requirements_review.reviewed_at = "2026-01-01T00:00:00+00:00"
        state.artifacts.input.digest = "input-hash"

        result = apply_authoritative_signal(state, "verdict", phase="requirements_review")

        human_approval = LifecyclePhase("requirements_human_approval")
        assert LifecyclePhase(state.lifecycle_phase) is human_approval
        assert result is human_approval

    def test_human_approval_pauses_and_returns_approval_instruction(self) -> None:
        state = TodoState.defaults()
        state.lifecycle_phase = "requirements_human_approval"

        # The machine must not auto-advance from this state

        assert not phase_is_complete(state, LifecyclePhase("requirements_human_approval"))

    def test_human_approval_survives_restart(self) -> None:
        state = TodoState.defaults()
        state.lifecycle_phase = "requirements_human_approval"

        # Re-reading state and checking phase must still return human_approval
        assert state.lifecycle_phase == "requirements_human_approval"

    def test_human_approval_stamp_advances_to_test_spec_build(self) -> None:
        state = TodoState.defaults()
        state.lifecycle_phase = "requirements_human_approval"

        result = apply_authoritative_signal(state, "requirements_human_approved")

        assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.TEST_SPEC_BUILD
        assert result is LifecyclePhase.TEST_SPEC_BUILD


# ---------------------------------------------------------------------------
# R3: Turn-based protocol
# ---------------------------------------------------------------------------


class TestTurnBasedProtocol:
    """Writer is messaged, reviewer observes passively via direct link."""

    @pytest.mark.asyncio
    async def test_writer_messaged_reviewer_not_during_write_phase(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.TEST_SPEC_BUILD.value
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a", agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(session_id="sess-b", agent="codex", lens="B")
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()
        todos_db.artifact_exists = AsyncMock(return_value=False)

        _, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="test-slug",
            cwd="/repo",
            phase=PreparePhase.TEST_SPEC_BUILD,
            state=raw_state,
        )

        # Writer (A) must be targeted
        assert "sess-a" in instruction
        # Reviewer (B) must NOT be messaged in this instruction
        assert "sess-b" not in instruction or "wait" in instruction.lower()

    @pytest.mark.asyncio
    async def test_reviewer_messaged_only_after_writer_agent_stop(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.TEST_SPEC_REVIEW.value
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a", agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(session_id="sess-b", agent="codex", lens="B")
        state.artifacts.test_specs.produced_at = ""
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()

        _, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="test-slug",
            cwd="/repo",
            phase=PreparePhase.TEST_SPEC_REVIEW,
            state=raw_state,
        )

        # Reviewer (B) must be targeted for review
        assert "sess-b" in instruction
        # Must use sessions send, not sessions run
        assert "telec sessions send" in instruction

    @pytest.mark.asyncio
    async def test_needs_work_relays_findings_to_writer_fix_forward(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.REQUIREMENTS_REVIEW.value
        state.requirements_review.verdict = "needs_work"
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a", agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(session_id="sess-b", agent="codex", lens="B")
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()

        _, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="test-slug",
            cwd="/repo",
            phase=PreparePhase.REQUIREMENTS_REVIEW,
            state=raw_state,
        )

        # Must relay to writer (A) for fix-forward
        assert "sess-a" in instruction

    def test_no_back_to_discovery_on_needs_work(self) -> None:
        """Fix-forward: needs_work on requirements does not revert to discovery."""
        state = TodoState.defaults()
        state.lifecycle_phase = LifecyclePhase.REQUIREMENTS_REVIEW.value
        state.requirements_review.verdict = "needs_work"
        state.artifacts.input.digest = "input-hash"

        result = apply_authoritative_signal(state, "verdict", phase="requirements_review")

        # Must go to TRIANGULATION (re-write), not back to INPUT_ASSESSMENT (re-discover)
        assert result is LifecyclePhase.TRIANGULATION


# ---------------------------------------------------------------------------
# R3: Writer/reviewer routing per phase
# ---------------------------------------------------------------------------


class TestWriterReviewerRouting:
    """Correct pair member targeted per phase, with role flip at plan."""

    @pytest.mark.asyncio
    async def _dispatch_for_phase(
        self,
        phase: PreparePhase,
        pair_a_id: str = "sess-a",
        pair_b_id: str = "sess-b",
    ) -> str:

        state = TodoState.defaults()
        state.lifecycle_phase = phase.value
        state.prepare_pair.slot_a = MagicMock(session_id=pair_a_id, agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(session_id=pair_b_id, agent="codex", lens="B")
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()
        todos_db.artifact_exists = AsyncMock(return_value=False)

        _, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="test-slug",
            cwd="/repo",
            phase=phase,
            state=raw_state,
        )
        return instruction

    @pytest.mark.asyncio
    async def test_triangulation_targets_writer_a(self) -> None:
        instruction = await self._dispatch_for_phase(PreparePhase.TRIANGULATION)
        assert "sess-a" in instruction

    @pytest.mark.asyncio
    async def test_requirements_review_targets_reviewer_b(self) -> None:
        instruction = await self._dispatch_for_phase(PreparePhase.REQUIREMENTS_REVIEW)
        assert "sess-b" in instruction

    @pytest.mark.asyncio
    async def test_test_spec_build_targets_writer_a(self) -> None:
        instruction = await self._dispatch_for_phase(PreparePhase.TEST_SPEC_BUILD)
        assert "sess-a" in instruction

    @pytest.mark.asyncio
    async def test_test_spec_review_targets_reviewer_b(self) -> None:
        instruction = await self._dispatch_for_phase(PreparePhase.TEST_SPEC_REVIEW)
        assert "sess-b" in instruction

    @pytest.mark.asyncio
    async def test_plan_drafting_targets_writer_b_role_flip(self) -> None:
        instruction = await self._dispatch_for_phase(PreparePhase.PLAN_DRAFTING)
        assert "sess-b" in instruction

    @pytest.mark.asyncio
    async def test_plan_review_targets_reviewer_a_role_flip(self) -> None:
        instruction = await self._dispatch_for_phase(PreparePhase.PLAN_REVIEW)
        assert "sess-a" in instruction


# ---------------------------------------------------------------------------
# R5: Convergence assessment
# ---------------------------------------------------------------------------


class TestConvergence:
    """Orchestrator receives convergence assessment instruction after discovery."""

    @pytest.mark.asyncio
    async def test_convergence_instruction_emitted_after_discovery(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.INPUT_ASSESSMENT.value
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a", agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(session_id="sess-b", agent="codex", lens="B")
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()
        todos_db.artifact_exists = AsyncMock(return_value=True)
        todos_db.artifact_digest = AsyncMock(return_value="digest")

        _keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="test-slug",
            cwd="/repo",
            phase=PreparePhase.INPUT_ASSESSMENT,
            state=raw_state,
        )

        # When requirements exist, should emit writer/reviewer assignment
        # not a fresh discovery dispatch
        assert "write" in instruction.lower() or "review" in instruction.lower()


# ---------------------------------------------------------------------------
# R6: Pair continuation and recovery
# ---------------------------------------------------------------------------


class TestPairContinuation:
    """Stored pair members targeted before generic lookup."""

    @pytest.mark.asyncio
    async def test_continuation_targets_stored_pair_before_generic_lookup(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.PLAN_DRAFTING.value
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a", agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(session_id="sess-b", agent="codex", lens="B")
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()
        todos_db.artifact_exists = AsyncMock(return_value=False)

        _, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="test-slug",
            cwd="/repo",
            phase=PreparePhase.PLAN_DRAFTING,
            state=raw_state,
        )

        # Must target stored B (writer for plan), not generic dispatch
        assert "sess-b" in instruction

    @pytest.mark.asyncio
    async def test_dead_reviewer_falls_back_to_fresh_dispatch(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.REQUIREMENTS_REVIEW.value
        # Pair exists but reviewer session is dead (not findable)
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a", agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(session_id="dead-sess", agent="codex", lens="B")
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        db.list_sessions = AsyncMock(return_value=[])  # no live sessions
        todos_db = AsyncMock()

        _, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="test-slug",
            cwd="/repo",
            phase=PreparePhase.REQUIREMENTS_REVIEW,
            state=raw_state,
        )

        # Must fall back to fresh dispatch when pair member is dead
        assert "telec sessions run" in instruction or "next-review-requirements" in instruction


# ---------------------------------------------------------------------------
# R7: Worktree deferred to TEST_SPEC_BUILD
# ---------------------------------------------------------------------------


class TestWorktreeDeferred:
    """Requirements-only work runs without worktree. Worktree ensured at specs."""

    @pytest.mark.asyncio
    async def test_input_assessment_no_worktree(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.INPUT_ASSESSMENT.value
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()
        todos_db.artifact_exists = AsyncMock(return_value=False)

        with patch("teleclaude.core.next_machine.prepare_steps.ensure_worktree_with_policy_async") as mock_worktree:
            await _prepare_dispatch(
                db=db,
                todos_db=todos_db,
                slug="test-slug",
                cwd="/repo",
                phase=PreparePhase.INPUT_ASSESSMENT,
                state=raw_state,
            )
            mock_worktree.assert_not_called()

    @pytest.mark.asyncio
    async def test_test_spec_build_ensures_worktree(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.TEST_SPEC_BUILD.value
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a", agent="claude", lens="A")
        state.prepare_pair.slot_b = MagicMock(session_id="sess-b", agent="codex", lens="B")
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()
        todos_db.artifact_exists = AsyncMock(return_value=False)

        with patch("teleclaude.core.next_machine.prepare_steps.ensure_worktree_with_policy_async") as mock_worktree:
            await _prepare_dispatch(
                db=db,
                todos_db=todos_db,
                slug="test-slug",
                cwd="/repo",
                phase=PreparePhase.TEST_SPEC_BUILD,
                state=raw_state,
            )
            mock_worktree.assert_called_once()


# ---------------------------------------------------------------------------
# R8: Gate dissolved
# ---------------------------------------------------------------------------


class TestGateDissolved:
    """Plan review approve goes directly to grounding, no gate dispatch."""

    def test_plan_review_approve_advances_to_grounding_not_gate(self) -> None:
        state = TodoState.defaults()
        state.lifecycle_phase = LifecyclePhase.PLAN_REVIEW.value
        state.plan_review.verdict = "approve"
        state.plan_review.reviewed_at = "2026-01-01T00:00:00+00:00"

        result = apply_authoritative_signal(state, "verdict", phase="plan_review")

        # Must skip GATE and go directly to GROUNDING_CHECK
        assert result is LifecyclePhase.GROUNDING_CHECK
        assert LifecyclePhase(state.lifecycle_phase) is LifecyclePhase.GROUNDING_CHECK

    @pytest.mark.asyncio
    async def test_no_gate_worker_dispatched(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.GATE.value
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()

        _keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="test-slug",
            cwd="/repo",
            phase=PreparePhase.GATE,
            state=raw_state,
        )

        # Gate must auto-advance or be a no-op, not dispatch a worker
        assert "next-prepare-gate" not in instruction


# ---------------------------------------------------------------------------
# R9: Grounding remains mechanical
# ---------------------------------------------------------------------------


class TestGroundingMechanical:
    """Grounding check uses no pair dispatch. Stale update targets plan writer."""

    @pytest.mark.asyncio
    async def test_grounding_check_mechanical_no_pair_dispatch(self) -> None:

        state = TodoState.defaults()
        state.lifecycle_phase = PreparePhase.GROUNDING_CHECK.value
        state.prepare_pair.slot_a = MagicMock(session_id="sess-a")
        state.prepare_pair.slot_b = MagicMock(session_id="sess-b")
        raw_state = state.model_dump(exclude_none=True)

        db = AsyncMock()
        todos_db = AsyncMock()
        todos_db.read_artifact_sync = MagicMock(return_value=None)

        with patch(
            "teleclaude.core.next_machine.prepare_steps.run_git_command",
            return_value=(0, "abc123", ""),
        ):
            keep_going, instruction = await _prepare_dispatch(
                db=db,
                todos_db=todos_db,
                slug="test-slug",
                cwd="/repo",
                phase=PreparePhase.GROUNDING_CHECK,
                state=raw_state,
            )

        # Grounding is mechanical — must not target pair members for the check itself
        # (stale update is different — that dispatches the plan writer)
        if not keep_going:
            # If stale, must target plan writer (B), not generic dispatch
            assert "sess-b" in instruction or "next-prepare-draft" in instruction
