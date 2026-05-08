"""Tests for prepare step handlers — phase dispatch behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine.prepare_grounding_steps import (
    prepare_step_grounding_check as _prepare_step_grounding_check,
)
from teleclaude.core.next_machine.prepare_grounding_steps import prepare_step_re_grounding as _prepare_step_re_grounding
from teleclaude.core.next_machine.prepare_steps import (
    _prepare_step_input_assessment,
    _prepare_step_plan_drafting,
    _prepare_step_plan_review,
    _prepare_step_requirements_review,
    _prepare_step_test_spec_build,
    _prepare_step_test_spec_review,
    _prepare_step_triangulation,
)

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]

_STEPS = "teleclaude.core.next_machine.prepare_steps"
_GROUNDING = "teleclaude.core.next_machine.prepare_grounding_steps"


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
        "requirements_review": {"verdict": "", "reviewed_at": "", "rounds": 0},
        "test_spec_review": {"verdict": "", "reviewed_at": "", "rounds": 0},
        "plan_review": {"verdict": "", "reviewed_at": "", "rounds": 0},
        "grounding": {"valid": False, "base_sha": "", "input_digest": "", "referenced_paths": []},
    }


# --- INPUT_ASSESSMENT ---


@pytest.mark.asyncio
async def test_input_assessment_dispatches_when_produced_at_empty() -> None:
    """After mark-phase rewind, produced_at is cleared. The handler must dispatch
    discovery even when artifacts exist in the DB — produced_at is the sole gate."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.write_state = AsyncMock()

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
async def test_input_assessment_advances_when_produced_at_set() -> None:
    """When produced_at is set (by a requirements_ready stamp), the handler applies
    the authoritative signal and advances."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_digest = AsyncMock(return_value="input-digest")
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


# --- TRIANGULATION ---


@pytest.mark.asyncio
async def test_triangulation_dispatches_when_produced_at_empty() -> None:
    """TRIANGULATION dispatches discovery when produced_at is empty."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=False)
    todos_db.write_state = AsyncMock()

    state = _base_state(lifecycle_phase="triangulation", requirements_digest="req-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"),
        patch(f"{_STEPS}._derive_project_root", return_value="/repo"),
    ):
        keep_going, instruction = await _prepare_step_triangulation(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is False
    assert instruction


@pytest.mark.asyncio
async def test_triangulation_advances_when_produced_at_set() -> None:
    """TRIANGULATION advances when produced_at is set (stamp received)."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.write_state = AsyncMock()

    state = _base_state(
        lifecycle_phase="triangulation",
        requirements_produced_at="2026-01-01T00:00:00+00:00",
        requirements_digest="req-digest",
    )

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, _ = await _prepare_step_triangulation(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is True


# --- PLAN_DRAFTING ---


@pytest.mark.asyncio
async def test_plan_drafting_dispatches_when_produced_at_empty() -> None:
    """PLAN_DRAFTING dispatches drafter when produced_at is empty."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.write_state = AsyncMock()

    state = _base_state(lifecycle_phase="plan_drafting", plan_digest="plan-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"),
        patch(f"{_STEPS}._derive_project_root", return_value="/repo"),
    ):
        keep_going, instruction = await _prepare_step_plan_drafting(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is False
    assert instruction


@pytest.mark.asyncio
async def test_plan_drafting_advances_when_produced_at_set() -> None:
    """PLAN_DRAFTING advances when produced_at is set, upstream_digests are
    populated, and recorded matches current — i.e. the artifact is fresh
    against its upstreams."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_digest = AsyncMock(
        side_effect=lambda _slug, name: {"requirements": "req", "test-specs": "spec"}.get(name, "")
    )
    todos_db.write_state = AsyncMock()

    state = _base_state(
        lifecycle_phase="plan_drafting",
        plan_produced_at="2026-01-01T00:00:00+00:00",
        plan_digest="plan-digest",
    )
    state["artifacts"]["implementation_plan"]["upstream_digests"] = {
        "requirements": "req",
        "test_specs": "spec",
    }

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, _ = await _prepare_step_plan_drafting(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is True


# --- RE_GROUNDING ---


@pytest.mark.asyncio
async def test_re_grounding_dispatches_when_produced_at_empty() -> None:
    """RE_GROUNDING dispatches drafter when produced_at is empty."""
    db = AsyncMock()
    todos_db = AsyncMock()
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
async def test_re_grounding_advances_when_produced_at_set() -> None:
    """RE_GROUNDING advances when produced_at is set (stamp received)."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.write_state = AsyncMock()

    state = _base_state(
        lifecycle_phase="re_grounding",
        plan_produced_at="2026-01-01T00:00:00+00:00",
        plan_digest="plan-digest",
    )

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, _ = await _prepare_step_re_grounding(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is True


# --- GROUNDING_CHECK: worktree-scoped baseline ---


def _make_worktree_layout(tmp_path: Path, slug: str) -> tuple[str, str]:
    """Create a fake parent-root + worktree directory pair under *tmp_path*.

    Returns ``(parent_root, worktree_path)`` so tests can assert which one the
    grounding step uses for its git baseline.
    """
    parent_root = tmp_path / "repo"
    worktree_path = parent_root / "trees" / slug
    worktree_path.mkdir(parents=True)
    return str(parent_root), str(worktree_path)


@pytest.mark.asyncio
async def test_grounding_check_captures_worktree_head_when_worktree_exists(tmp_path: Path) -> None:
    """First grounding for a slug with a worktree must anchor to the worktree HEAD.

    Anchoring to the parent-root HEAD lets unrelated deliveries on main bump
    the baseline, which then trips the freshness check on later iterations and
    re-enters the plan-drafting loop. The grounding baseline must scope to the
    todo's worktree so progress on this todo is decoupled from main.
    """
    parent_root, worktree_path = _make_worktree_layout(tmp_path, "my-slug")

    captured_cwds: list[str] = []

    def _run_git_command(_args: list[str], cwd: str) -> tuple[int, str, str]:
        captured_cwds.append(cwd)
        if cwd == worktree_path:
            return 0, "worktree-head\n", ""
        return 0, "parent-head\n", ""

    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.write_state = AsyncMock()
    todos_db.read_artifact_sync = lambda *_args, **_kwargs: ""

    state = _base_state(lifecycle_phase="grounding_check")

    with (
        patch(f"{_GROUNDING}._emit_prepare_event"),
        patch(f"{_GROUNDING}.run_git_command", side_effect=_run_git_command),
    ):
        keep_going, _ = await _prepare_step_grounding_check(db, todos_db, "my-slug", parent_root, state)

    assert keep_going is True
    assert worktree_path in captured_cwds, (
        f"grounding_check ran git only against {captured_cwds!r}; expected the worktree path"
    )
    assert state["grounding"]["base_sha"] == "worktree-head"


@pytest.mark.asyncio
async def test_grounding_check_stays_fresh_when_only_parent_head_advances(tmp_path: Path) -> None:
    """A delivery on main must not invalidate a todo whose worktree is unchanged.

    Reproduces the production loop: after plan_review approves and base_sha is
    captured, an unrelated delivery bumps parent-root HEAD. On the next
    grounding_check the baseline must still match the worktree HEAD, otherwise
    the step invalidates grounding and re_grounding clears plan_review.verdict
    via the grounding_invalidated signal.
    """
    parent_root, worktree_path = _make_worktree_layout(tmp_path, "my-slug")

    def _run_git_command(_args: list[str], cwd: str) -> tuple[int, str, str]:
        if cwd == worktree_path:
            return 0, "worktree-head\n", ""
        # Parent root advanced because some other todo was delivered.
        return 0, "parent-head-advanced\n", ""

    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.write_state = AsyncMock()
    todos_db.read_artifact_sync = lambda *_args, **_kwargs: ""

    state = _base_state(lifecycle_phase="grounding_check")
    state["grounding"] = {
        "valid": True,
        "base_sha": "worktree-head",
        "input_digest": "",
        "referenced_paths": [],
        "last_grounded_at": "",
        "invalidated_at": "",
        "invalidation_reason": "",
        "changed_paths": [],
    }
    state["plan_review"] = {
        "verdict": "approve",
        "reviewed_at": "2026-01-01T00:00:00+00:00",
        "rounds": 0,
        "baseline_commit": "",
        "approved_digest": "plan-digest",
    }

    with (
        patch(f"{_GROUNDING}._emit_prepare_event"),
        patch(f"{_GROUNDING}.run_git_command", side_effect=_run_git_command),
    ):
        keep_going, _ = await _prepare_step_grounding_check(db, todos_db, "my-slug", parent_root, state)

    assert keep_going is True
    assert state["grounding"]["valid"] is True
    assert state["plan_review"]["verdict"] == "approve"


@pytest.mark.asyncio
async def test_grounding_check_falls_back_to_parent_root_when_no_worktree(tmp_path: Path) -> None:
    """Without a worktree, grounding_check uses the parent root (current contract)."""
    parent_root = str(tmp_path / "repo")
    Path(parent_root).mkdir()

    captured_cwds: list[str] = []

    def _run_git_command(_args: list[str], cwd: str) -> tuple[int, str, str]:
        captured_cwds.append(cwd)
        return 0, "parent-head\n", ""

    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.write_state = AsyncMock()
    todos_db.read_artifact_sync = lambda *_args, **_kwargs: ""

    state = _base_state(lifecycle_phase="grounding_check")

    with (
        patch(f"{_GROUNDING}._emit_prepare_event"),
        patch(f"{_GROUNDING}.run_git_command", side_effect=_run_git_command),
    ):
        keep_going, _ = await _prepare_step_grounding_check(db, todos_db, "my-slug", parent_root, state)

    assert keep_going is True
    assert captured_cwds == [parent_root]
    assert state["grounding"]["base_sha"] == "parent-head"


# --- DispatchReason: every dispatch carries an explicit reason header ---


@pytest.mark.asyncio
async def test_plan_drafting_dispatch_marks_fresh_when_no_prior_artifact() -> None:
    """A first plan-drafting dispatch with no produced_at must surface ``fresh``."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_digest = AsyncMock(return_value="")
    todos_db.write_state = AsyncMock()

    state = _base_state(lifecycle_phase="plan_drafting", plan_digest="plan-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"),
        patch(f"{_STEPS}._derive_project_root", return_value="/repo"),
    ):
        keep_going, instruction = await _prepare_step_plan_drafting(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is False
    assert "Dispatch reason: fresh" in instruction


@pytest.mark.asyncio
async def test_plan_drafting_dispatch_marks_provenance_missing_when_upstream_digests_empty() -> None:
    """An existing plan with empty upstream_digests must dispatch with
    ``provenance-missing``. The plan-drafting auto-advance is gated on
    non-empty upstream_digests so this dispatch path is reachable.
    """
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_digest = AsyncMock(return_value="current-req")
    todos_db.write_state = AsyncMock()

    state = _base_state(
        lifecycle_phase="plan_drafting",
        plan_produced_at="2026-04-25T20:46:12+00:00",
        plan_digest="plan-digest",
    )
    # Explicitly empty upstream_digests — the legacy provenance-missing state.
    state["artifacts"]["implementation_plan"]["upstream_digests"] = {}

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"),
        patch(f"{_STEPS}._derive_project_root", return_value="/repo"),
    ):
        keep_going, instruction = await _prepare_step_plan_drafting(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is False
    assert "Dispatch reason: provenance-missing" in instruction


@pytest.mark.asyncio
async def test_test_spec_build_dispatch_marks_provenance_missing_when_upstream_digests_empty() -> None:
    """An existing test_specs artifact with empty upstream_digests is the
    legacy state — ``provenance-missing`` tells the worker to verify alignment
    against current requirements instead of overwriting valid prior specs.

    Reachable in test_spec_build because that step compares recorded vs current
    directly: empty recorded != non-empty current → dispatch (not auto-advance).
    """
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_digest = AsyncMock(return_value="current-req")
    todos_db.write_state = AsyncMock()

    state = _base_state(lifecycle_phase="test_spec_build")
    state["artifacts"]["test_specs"]["produced_at"] = "2026-04-25T20:46:11+00:00"
    state["artifacts"]["test_specs"]["digest"] = "specs-digest"

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"),
        patch(f"{_STEPS}._derive_project_root", return_value="/repo"),
        patch(f"{_STEPS}.ensure_worktree_with_policy_async", new_callable=AsyncMock),
    ):
        keep_going, instruction = await _prepare_step_test_spec_build(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is False
    assert "Dispatch reason: provenance-missing" in instruction


@pytest.mark.asyncio
async def test_plan_drafting_dispatch_marks_upstream_changed_when_recorded_digest_differs() -> None:
    """Recorded upstream digest != current → upstream-changed."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_digest = AsyncMock(return_value="current-req")
    todos_db.write_state = AsyncMock()

    state = _base_state(
        lifecycle_phase="plan_drafting",
        plan_produced_at="2026-04-25T20:46:12+00:00",
        plan_digest="plan-digest",
    )
    state["artifacts"]["implementation_plan"]["upstream_digests"] = {
        "requirements": "old-req",
        "test_specs": "old-spec",
    }

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"),
        patch(f"{_STEPS}._derive_project_root", return_value="/repo"),
    ):
        keep_going, instruction = await _prepare_step_plan_drafting(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is False
    assert "Dispatch reason: upstream-changed" in instruction


@pytest.mark.asyncio
async def test_re_grounding_dispatch_marks_upstream_changed() -> None:
    """RE_GROUNDING is always reached after grounding invalidation — upstream-changed."""
    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.write_state = AsyncMock()

    state = _base_state(lifecycle_phase="re_grounding", plan_digest="plan-digest")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_GROUNDING}.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"),
        patch(f"{_GROUNDING}._derive_project_root", return_value="/repo"),
    ):
        keep_going, instruction = await _prepare_step_re_grounding(db, todos_db, "my-slug", "/repo", state)

    assert keep_going is False
    assert "Dispatch reason: upstream-changed" in instruction


# --- REVIEW NEEDS WORK: direct-link dispatch must be unconditional ---


@pytest.mark.asyncio
async def test_requirements_review_needs_work_emits_direct_link_script_with_pair_stamped() -> None:
    """Pair stamp must not redirect needs_work to pair-member send; direct link wins."""
    state = _base_state(lifecycle_phase="requirements_review")
    state["requirements_review"] = {"verdict": "needs_work", "reviewed_at": "", "rounds": 0}
    state["prepare_pair"] = {
        "slot_a": {"session_id": "worker-1", "agent": "claude", "lens": "A"},
        "slot_b": {"session_id": "reviewer-1", "agent": "codex", "lens": "B"},
    }

    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_digest = AsyncMock(return_value="")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, instruction = await _prepare_step_requirements_review(db, todos_db, "test-slug", "/repo", state)

    command_lines = [
        line.strip() for line in instruction.splitlines() if line.strip().startswith("telec sessions send")
    ]
    assert keep_going is False
    assert instruction.startswith("REVIEW NEEDS WORK: test-slug")
    assert command_lines[0].startswith('telec sessions send reviewer-1 "A fixer is active at worker-1.')
    assert "telec sessions send worker-1 '<your findings summary>' --direct" in command_lines[0]
    assert not command_lines[0].endswith(" --direct")
    assert "Wait for reviewer session reviewer-1 to report idle." in instruction


@pytest.mark.asyncio
async def test_test_spec_review_needs_work_emits_direct_link_script_with_pair_stamped() -> None:
    """Pair stamp must not redirect test-spec needs_work to pair-member send; direct link wins."""
    state = _base_state(lifecycle_phase="test_spec_review")
    state["test_spec_review"] = {"verdict": "needs_work", "reviewed_at": "", "rounds": 0}
    state["prepare_pair"] = {
        "slot_a": {"session_id": "worker-1", "agent": "claude", "lens": "A"},
        "slot_b": {"session_id": "reviewer-1", "agent": "codex", "lens": "B"},
    }

    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_digest = AsyncMock(return_value="")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, instruction = await _prepare_step_test_spec_review(db, todos_db, "test-slug", "/repo", state)

    command_lines = [
        line.strip() for line in instruction.splitlines() if line.strip().startswith("telec sessions send")
    ]
    assert keep_going is False
    assert instruction.startswith("REVIEW NEEDS WORK: test-slug")
    assert command_lines[0].startswith('telec sessions send reviewer-1 "A fixer is active at worker-1.')
    assert "telec sessions send worker-1 '<your findings summary>' --direct" in command_lines[0]
    assert not command_lines[0].endswith(" --direct")
    assert "Wait for reviewer session reviewer-1 to report idle." in instruction


@pytest.mark.asyncio
async def test_plan_review_needs_work_emits_direct_link_script_with_pair_stamped() -> None:
    """Pair stamp must not redirect plan needs_work to pair-member send; direct link wins.

    In plan_review the roles are flipped: B is the writer/fixer, A is the reviewer.
    """
    state = _base_state(lifecycle_phase="plan_review")
    state["plan_review"] = {"verdict": "needs_work", "reviewed_at": "", "rounds": 0}
    state["prepare_pair"] = {
        "slot_a": {"session_id": "reviewer-1", "agent": "claude", "lens": "A"},  # A = reviewer in plan_review
        "slot_b": {"session_id": "worker-1", "agent": "codex", "lens": "B"},  # B = worker/fixer in plan_review
    }

    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_digest = AsyncMock(return_value="")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        keep_going, instruction = await _prepare_step_plan_review(db, todos_db, "test-slug", "/repo", state)

    command_lines = [
        line.strip() for line in instruction.splitlines() if line.strip().startswith("telec sessions send")
    ]
    assert keep_going is False
    assert instruction.startswith("REVIEW NEEDS WORK: test-slug")
    assert command_lines[0].startswith('telec sessions send reviewer-1 "A fixer is active at worker-1.')
    assert "telec sessions send worker-1 '<your findings summary>' --direct" in command_lines[0]
    assert not command_lines[0].endswith(" --direct")
    assert "Wait for reviewer session reviewer-1 to report idle." in instruction


@pytest.mark.asyncio
async def test_review_needs_work_emits_same_script_with_or_without_pair_stamped() -> None:
    """Pair-stamping must not change the dispatch shape — identical scripts either way."""
    state_with_pair = _base_state(lifecycle_phase="requirements_review")
    state_with_pair["requirements_review"] = {"verdict": "needs_work", "reviewed_at": "", "rounds": 0}
    state_with_pair["prepare_pair"] = {
        "slot_a": {"session_id": "worker-1", "agent": "claude", "lens": "A"},
        "slot_b": {"session_id": "reviewer-1", "agent": "codex", "lens": "B"},
    }

    state_no_pair = _base_state(lifecycle_phase="requirements_review")
    state_no_pair["requirements_review"] = {"verdict": "needs_work", "reviewed_at": "", "rounds": 0}

    db = AsyncMock()
    todos_db = AsyncMock()
    todos_db.artifact_digest = AsyncMock(return_value="")

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
    ):
        _, instruction_with_pair = await _prepare_step_requirements_review(
            db, todos_db, "test-slug", "/repo", state_with_pair
        )

    with (
        patch(f"{_STEPS}._commit_writer", new_callable=AsyncMock),
        patch(f"{_STEPS}._emit_prepare_event"),
        patch(
            f"{_STEPS}._find_live_session_for_slug",
            new=AsyncMock(side_effect=["reviewer-1", "worker-1"]),
        ),
    ):
        _, instruction_no_pair = await _prepare_step_requirements_review(
            db, todos_db, "test-slug", "/repo", state_no_pair
        )

    assert instruction_with_pair == instruction_no_pair
