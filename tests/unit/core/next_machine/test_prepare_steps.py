"""Characterization tests for prepare step handlers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from teleclaude.core.next_machine._types import DOR_READY_THRESHOLD, PreparePhase, StateValue
from teleclaude.core.next_machine.prepare_steps import (
    _derive_project_root,
    _prepare_dispatch,
    _prepare_step_grounding_check,
    _prepare_step_input_assessment,
    _prepare_step_plan_drafting,
    _prepare_step_plan_review,
    _prepare_step_re_grounding,
    _prepare_step_requirements_review,
    _prepare_step_test_spec_build,
    _prepare_step_triangulation,
    _restamp_artifact_digest,
)


def _write_state(todo_dir: Path, state: dict[object, object]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def test_prepare_step_grounding_check_first_pass_captures_baseline_and_marks_prepared(tmp_path: Path) -> None:
    """First grounding check stamps baseline SHA and input digest, then marks prepared."""
    todo_dir = tmp_path / "todos" / "slug-a"
    todo_dir.mkdir(parents=True)
    (todo_dir / "input.md").write_text("hello", encoding="utf-8")
    state: dict[str, StateValue] = {"grounding": {}}

    with (
        patch("teleclaude.core.next_machine.prepare_steps.run_git_command", return_value=(0, "abc123\n", "")),
        patch("teleclaude.core.next_machine.prepare_steps._emit_prepare_event"),
    ):
        keep_going, instruction = _prepare_step_grounding_check("slug-a", str(tmp_path), state)

    prepare_phase = state.get("current")
    grounding = state.get("grounding")
    assert isinstance(grounding, dict)
    assert keep_going is True
    assert instruction == ""
    assert prepare_phase == PreparePhase.PREPARED.value
    assert grounding["base_sha"] == "abc123"
    assert grounding["input_digest"] == hashlib.sha256(b"hello").hexdigest()
    assert grounding["valid"] is True


def test_prepare_step_grounding_check_invalidates_when_input_digest_changes(tmp_path: Path) -> None:
    """Grounding check transitions to RE_GROUNDING when input.md digest changes."""
    todo_dir = tmp_path / "todos" / "slug-b"
    todo_dir.mkdir(parents=True)
    (todo_dir / "input.md").write_text("changed", encoding="utf-8")
    state: dict[str, StateValue] = {
        "grounding": {
            "base_sha": "abc123",
            "input_digest": hashlib.sha256(b"original").hexdigest(),
            "referenced_paths": [],
        }
    }

    with (
        patch("teleclaude.core.next_machine.prepare_steps.run_git_command", return_value=(0, "abc123\n", "")),
        patch("teleclaude.core.next_machine.prepare_steps._emit_prepare_event"),
    ):
        keep_going, instruction = _prepare_step_grounding_check("slug-b", str(tmp_path), state)

    prepare_phase = state.get("current")
    grounding = state.get("grounding")
    assert isinstance(grounding, dict)
    assert keep_going is True
    assert instruction == ""
    assert prepare_phase == PreparePhase.RE_GROUNDING.value
    assert grounding["valid"] is False
    assert grounding["invalidation_reason"] == "input_updated"


@pytest.mark.asyncio
async def test_prepare_step_re_grounding_resets_plan_review_and_dispatches_redraft(tmp_path: Path) -> None:
    """Re-grounding clears plan_review verdict and dispatches a re-draft worker."""
    todo_dir = tmp_path / "todos" / "slug-c"
    _write_state(todo_dir, {})
    state: dict[str, StateValue] = {
        "grounding": {"changed_paths": ["src/app.py"]},
        "plan_review": {"verdict": "approve"},
    }
    db = AsyncMock()

    with (
        patch("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance", return_value="guidance"),
        patch("teleclaude.core.next_machine.prepare_steps._emit_prepare_event"),
    ):
        keep_going, instruction = await _prepare_step_re_grounding(db, "slug-c", str(tmp_path), state)

    prepare_phase = state.get("current")
    plan_review = state.get("plan_review")
    assert isinstance(plan_review, dict)
    assert keep_going is False
    assert prepare_phase == PreparePhase.PLAN_REVIEW.value
    assert plan_review["verdict"] == ""
    assert "Changed files: src/app.py" in instruction
    assert 'telec sessions run --command "/next-prepare-draft" --args "slug-c"' in instruction


@pytest.mark.asyncio
async def test_prepare_dispatch_returns_blocked_message_for_blocked_phase() -> None:
    """BLOCKED phase returns a message identifying the slug and invalidation reason."""
    with patch("teleclaude.core.next_machine.prepare_steps._emit_prepare_event"):
        keep_going, instruction = await _prepare_dispatch(
            db=AsyncMock(),
            slug="slug-d",
            cwd="/repo",
            phase=PreparePhase.BLOCKED,
            state={"grounding": {"invalidation_reason": "files_changed"}},
        )

    assert keep_going is False
    assert "BLOCKED:" in instruction
    assert "slug-d" in instruction
    assert "files_changed" in instruction


@pytest.mark.asyncio
async def test_prepare_dispatch_advances_approved_spec_review_to_plan_drafting(tmp_path: Path) -> None:
    """Approved test spec review transitions state to PLAN_DRAFTING."""
    todo_dir = tmp_path / "todos" / "slug-e"
    _write_state(todo_dir, {})
    state: dict[str, StateValue] = {"test_spec_review": {"verdict": "approve"}}

    with patch("teleclaude.core.next_machine.prepare_steps._emit_prepare_event"):
        keep_going, instruction = await _prepare_dispatch(
            db=AsyncMock(),
            slug="slug-e",
            cwd=str(tmp_path),
            phase=PreparePhase.TEST_SPEC_REVIEW,
            state=state,
        )

    persisted = yaml.safe_load((todo_dir / "state.yaml").read_text(encoding="utf-8"))
    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.PLAN_DRAFTING.value
    assert persisted["current"] == PreparePhase.PLAN_DRAFTING.value


@pytest.mark.asyncio
async def test_prepare_dispatch_advances_approved_plan_review_to_gate(tmp_path: Path) -> None:
    """Approved plan review transitions state to GATE."""
    todo_dir = tmp_path / "todos" / "slug-f"
    _write_state(todo_dir, {})
    state: dict[str, StateValue] = {"plan_review": {"verdict": "approve"}}

    with patch("teleclaude.core.next_machine.prepare_steps._emit_prepare_event"):
        keep_going, instruction = await _prepare_dispatch(
            db=AsyncMock(),
            slug="slug-f",
            cwd=str(tmp_path),
            phase=PreparePhase.PLAN_REVIEW,
            state=state,
        )

    persisted = yaml.safe_load((todo_dir / "state.yaml").read_text(encoding="utf-8"))
    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.GATE.value
    assert persisted["current"] == PreparePhase.GATE.value


@pytest.mark.asyncio
async def test_prepare_dispatch_records_baseline_and_dispatches_plan_review(tmp_path: Path) -> None:
    """Plan review without a verdict stamps baseline SHA and dispatches the review worker."""
    todo_dir = tmp_path / "todos" / "slug-g"
    _write_state(todo_dir, {})
    state: dict[str, StateValue] = {}

    with (
        patch("teleclaude.core.next_machine.prepare_steps.run_git_command", return_value=(0, "abc123\n", "")),
        patch("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance", return_value="guidance"),
    ):
        keep_going, instruction = await _prepare_dispatch(
            db=AsyncMock(),
            slug="slug-g",
            cwd=str(tmp_path),
            phase=PreparePhase.PLAN_REVIEW,
            state=state,
        )

    persisted = yaml.safe_load((todo_dir / "state.yaml").read_text(encoding="utf-8"))
    plan_review = state.get("plan_review")
    assert isinstance(plan_review, dict)
    assert keep_going is False
    assert plan_review["baseline_commit"] == "abc123"
    assert persisted["plan_review"]["baseline_commit"] == "abc123"
    assert 'telec sessions run --command "/next-review-plan" --args "slug-g"' in instruction


@pytest.mark.asyncio
async def test_prepare_dispatch_advances_gate_to_grounding_check_when_dor_is_ready(tmp_path: Path) -> None:
    """GATE phase with DOR score at threshold transitions to GROUNDING_CHECK."""
    todo_dir = tmp_path / "todos" / "slug-h"
    _write_state(todo_dir, {})
    state: dict[str, StateValue] = {"dor": {"score": DOR_READY_THRESHOLD}}

    keep_going, instruction = await _prepare_dispatch(
        db=AsyncMock(),
        slug="slug-h",
        cwd=str(tmp_path),
        phase=PreparePhase.GATE,
        state=state,
    )

    persisted = yaml.safe_load((todo_dir / "state.yaml").read_text(encoding="utf-8"))
    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.GROUNDING_CHECK.value
    assert persisted["current"] == PreparePhase.GROUNDING_CHECK.value


@pytest.mark.asyncio
async def test_prepare_dispatch_requests_gate_worker_when_dor_is_below_threshold(tmp_path: Path) -> None:
    """GATE phase with DOR score below threshold dispatches a gate worker."""
    state: dict[str, StateValue] = {"dor": {"score": DOR_READY_THRESHOLD - 1}}

    with patch("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance", return_value="guidance"):
        keep_going, instruction = await _prepare_dispatch(
            db=AsyncMock(),
            slug="slug-i",
            cwd=str(tmp_path),
            phase=PreparePhase.GATE,
            state=state,
        )

    assert keep_going is False
    assert 'telec sessions run --command "/next-prepare-gate" --args "slug-i"' in instruction
    assert f"state.yaml.dor.score >= {DOR_READY_THRESHOLD}" in instruction


@pytest.mark.asyncio
async def test_requirements_on_disk_advances_input_assessment_v2(tmp_path: Path) -> None:
    """v2: current is authoritative — file existence is sufficient to advance past input_assessment."""
    todo_dir = tmp_path / "todos" / "slug-req1"
    todo_dir.mkdir(parents=True)
    (todo_dir / "input.md").write_text("input content here", encoding="utf-8")
    (todo_dir / "requirements.md").write_text(
        "Authored requirements that are long enough to pass the scaffold check gate.\n",
        encoding="utf-8",
    )
    _write_state(todo_dir, {})
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "current": "input_assessment",
        "artifacts": {
            "requirements": {"digest": "", "produced_at": "", "stale": False},
        },
    }

    keep_going, instruction = await _prepare_step_input_assessment(AsyncMock(), "slug-req1", str(tmp_path), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.REQUIREMENTS_REVIEW.value


@pytest.mark.asyncio
async def test_requirements_on_disk_advances_triangulation_v2(tmp_path: Path) -> None:
    """v2: current is authoritative — file existence is sufficient to advance past triangulation."""
    todo_dir = tmp_path / "todos" / "slug-req2"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text(
        "Authored requirements that are long enough to pass the scaffold check gate.\n",
        encoding="utf-8",
    )
    _write_state(todo_dir, {})
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "current": "triangulation",
        "artifacts": {
            "requirements": {"digest": "", "produced_at": "", "stale": False},
        },
    }

    keep_going, instruction = await _prepare_step_triangulation(AsyncMock(), "slug-req2", str(tmp_path), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.REQUIREMENTS_REVIEW.value


@pytest.mark.asyncio
async def test_test_specs_on_disk_advances_test_spec_build_v2(tmp_path: Path) -> None:
    """v2: current is authoritative — xfail test file existence is sufficient to advance."""
    todo_dir = tmp_path / "todos" / "slug-spec1"
    _write_state(todo_dir, {})
    worktree = tmp_path / "trees" / "slug-spec1" / "tests"
    worktree.mkdir(parents=True)
    (worktree / "test_example.py").write_text("pytestmark = pytest.mark.xfail\n", encoding="utf-8")
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "current": "test_spec_build",
        "artifacts": {
            "test_specs": {"digest": "", "produced_at": "", "stale": False},
        },
    }

    keep_going, instruction = await _prepare_step_test_spec_build(AsyncMock(), "slug-spec1", str(tmp_path), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.TEST_SPEC_REVIEW.value


@pytest.mark.asyncio
async def test_plan_on_disk_advances_plan_drafting_v2(tmp_path: Path) -> None:
    """v2: current is authoritative — file existence is sufficient to advance past plan_drafting."""
    todo_dir = tmp_path / "todos" / "slug-plan1"
    todo_dir.mkdir(parents=True)
    (todo_dir / "implementation-plan.md").write_text(
        "Authored implementation plan that is long enough to pass the scaffold check gate.\n",
        encoding="utf-8",
    )
    _write_state(todo_dir, {})
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "current": "plan_drafting",
        "artifacts": {
            "implementation_plan": {"digest": "", "produced_at": "", "stale": False},
        },
    }

    keep_going, instruction = await _prepare_step_plan_drafting(AsyncMock(), "slug-plan1", str(tmp_path), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.PLAN_REVIEW.value


@pytest.mark.asyncio
async def test_requirements_in_worktree_advances_input_assessment(tmp_path: Path) -> None:
    """Step receives worktree-resolved cwd from dispatcher and reads artifacts from worktree."""
    slug = "slug-wt-ia"
    worktree = tmp_path / "trees" / slug
    worktree_todos = worktree / "todos" / slug
    worktree_todos.mkdir(parents=True)
    (worktree_todos / "requirements.md").write_text(
        "Authored requirements long enough to pass the scaffold check gate.\n",
        encoding="utf-8",
    )
    _write_state(worktree_todos, {})
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "current": "input_assessment",
        "artifacts": {"requirements": {"digest": "", "produced_at": "", "stale": False}},
    }

    keep_going, instruction = await _prepare_step_input_assessment(AsyncMock(), slug, str(worktree), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.REQUIREMENTS_REVIEW.value


@pytest.mark.asyncio
async def test_requirements_in_worktree_advances_triangulation(tmp_path: Path) -> None:
    """Step receives worktree-resolved cwd from dispatcher and reads artifacts from worktree."""
    slug = "slug-wt-tri"
    worktree = tmp_path / "trees" / slug
    worktree_todos = worktree / "todos" / slug
    worktree_todos.mkdir(parents=True)
    (worktree_todos / "requirements.md").write_text(
        "Authored requirements long enough to pass the scaffold check gate.\n",
        encoding="utf-8",
    )
    _write_state(worktree_todos, {})
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "current": "triangulation",
        "artifacts": {"requirements": {"digest": "", "produced_at": "", "stale": False}},
    }

    keep_going, instruction = await _prepare_step_triangulation(AsyncMock(), slug, str(worktree), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.REQUIREMENTS_REVIEW.value


@pytest.mark.asyncio
async def test_plan_in_worktree_advances_plan_drafting(tmp_path: Path) -> None:
    """Step receives worktree-resolved cwd from dispatcher and reads artifacts from worktree."""
    slug = "slug-wt-plan"
    worktree = tmp_path / "trees" / slug
    worktree_todos = worktree / "todos" / slug
    worktree_todos.mkdir(parents=True)
    (worktree_todos / "implementation-plan.md").write_text(
        "Authored plan long enough to pass the scaffold check gate.\n",
        encoding="utf-8",
    )
    _write_state(worktree_todos, {})
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "current": "plan_drafting",
        "artifacts": {"implementation_plan": {"digest": "", "produced_at": "", "stale": False}},
    }

    keep_going, instruction = await _prepare_step_plan_drafting(AsyncMock(), slug, str(worktree), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.PLAN_REVIEW.value


def test_restamp_artifact_digest_updates_when_file_changed(tmp_path: Path) -> None:
    """Re-stamp updates the stored digest when the file on disk has changed."""
    todo_dir = tmp_path / "todos" / "slug-rs1"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("original content", encoding="utf-8")
    original_digest = hashlib.sha256(b"original content").hexdigest()
    state: dict[str, StateValue] = {
        "artifacts": {"requirements": {"digest": original_digest, "produced_at": "2026-01-01T00:00:00Z"}},
    }

    # Simulate reviewer modifying the file
    (todo_dir / "requirements.md").write_text("reviewer-modified content", encoding="utf-8")
    expected_digest = hashlib.sha256(b"reviewer-modified content").hexdigest()

    _restamp_artifact_digest(state, str(tmp_path), "slug-rs1", "requirements", "requirements.md")

    artifacts = state["artifacts"]
    assert isinstance(artifacts, dict)
    req = artifacts["requirements"]
    assert isinstance(req, dict)
    assert req["digest"] == expected_digest


def test_restamp_artifact_digest_noop_when_unchanged(tmp_path: Path) -> None:
    """Re-stamp is a no-op when the file digest matches the stored digest."""
    todo_dir = tmp_path / "todos" / "slug-rs2"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("same content", encoding="utf-8")
    same_digest = hashlib.sha256(b"same content").hexdigest()
    state: dict[str, StateValue] = {
        "artifacts": {"requirements": {"digest": same_digest, "produced_at": "2026-01-01T00:00:00Z"}},
    }

    _restamp_artifact_digest(state, str(tmp_path), "slug-rs2", "requirements", "requirements.md")

    artifacts = state["artifacts"]
    assert isinstance(artifacts, dict)
    req = artifacts["requirements"]
    assert isinstance(req, dict)
    assert req["digest"] == same_digest


@pytest.mark.asyncio
async def test_requirements_review_approve_restamps_digest_when_reviewer_modified_artifact(tmp_path: Path) -> None:
    """When reviewer modifies requirements.md and approves, the digest is updated before advancing."""
    todo_dir = tmp_path / "todos" / "slug-rv1"
    todo_dir.mkdir(parents=True)
    # File on disk has been modified by reviewer
    (todo_dir / "requirements.md").write_text("reviewer-modified requirements", encoding="utf-8")
    _write_state(todo_dir, {})
    old_digest = hashlib.sha256(b"original requirements").hexdigest()
    new_digest = hashlib.sha256(b"reviewer-modified requirements").hexdigest()
    state: dict[str, StateValue] = {
        "requirements_review": {"verdict": "approve"},
        "artifacts": {"requirements": {"digest": old_digest, "produced_at": "2026-01-01T00:00:00Z"}},
    }

    with patch("teleclaude.core.next_machine.prepare_steps._emit_prepare_event"):
        keep_going, instruction = await _prepare_step_requirements_review(AsyncMock(), "slug-rv1", str(tmp_path), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.TEST_SPEC_BUILD.value
    artifacts = state["artifacts"]
    assert isinstance(artifacts, dict)
    req = artifacts["requirements"]
    assert isinstance(req, dict)
    assert req["digest"] == new_digest


@pytest.mark.asyncio
async def test_plan_review_approve_restamps_digest_when_reviewer_modified_artifact(tmp_path: Path) -> None:
    """When reviewer modifies implementation-plan.md and approves, the digest is updated before advancing."""
    todo_dir = tmp_path / "todos" / "slug-rv2"
    todo_dir.mkdir(parents=True)
    (todo_dir / "implementation-plan.md").write_text("reviewer-modified plan", encoding="utf-8")
    _write_state(todo_dir, {})
    old_digest = hashlib.sha256(b"original plan").hexdigest()
    new_digest = hashlib.sha256(b"reviewer-modified plan").hexdigest()
    state: dict[str, StateValue] = {
        "plan_review": {"verdict": "approve"},
        "artifacts": {"implementation_plan": {"digest": old_digest, "produced_at": "2026-01-01T00:00:00Z"}},
    }

    with patch("teleclaude.core.next_machine.prepare_steps._emit_prepare_event"):
        keep_going, instruction = await _prepare_step_plan_review(AsyncMock(), "slug-rv2", str(tmp_path), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.GATE.value
    artifacts = state["artifacts"]
    assert isinstance(artifacts, dict)
    plan = artifacts["implementation_plan"]
    assert isinstance(plan, dict)
    assert plan["digest"] == new_digest


def test_grounding_check_reads_input_from_worktree_cwd(tmp_path: Path) -> None:
    """Grounding check reads input.md from effective cwd (worktree), not project root."""
    slug = "slug-gc-wt"
    worktree = tmp_path / "trees" / slug
    worktree_todos = worktree / "todos" / slug
    worktree_todos.mkdir(parents=True)
    (worktree_todos / "input.md").write_text("worktree input", encoding="utf-8")

    # Project root has a DIFFERENT input.md (scaffold)
    root_todos = tmp_path / "todos" / slug
    root_todos.mkdir(parents=True)
    (root_todos / "input.md").write_text("scaffold", encoding="utf-8")

    state: dict[str, StateValue] = {"grounding": {}}

    with (
        patch("teleclaude.core.next_machine.prepare_steps.run_git_command", return_value=(0, "abc123\n", "")),
        patch("teleclaude.core.next_machine.prepare_steps._emit_prepare_event"),
    ):
        keep_going, _ = _prepare_step_grounding_check(slug, str(worktree), state)

    grounding = state.get("grounding")
    assert isinstance(grounding, dict)
    assert keep_going is True
    # Digest must match the worktree input, not the project root scaffold
    assert grounding["input_digest"] == hashlib.sha256(b"worktree input").hexdigest()


def test_restamp_reads_artifact_from_worktree_cwd(tmp_path: Path) -> None:
    """_restamp_artifact_digest reads from worktree cwd, not project root."""
    slug = "slug-rs-wt"
    worktree = tmp_path / "trees" / slug
    worktree_todos = worktree / "todos" / slug
    worktree_todos.mkdir(parents=True)
    (worktree_todos / "requirements.md").write_text("worktree content", encoding="utf-8")

    # Project root has stale content
    root_todos = tmp_path / "todos" / slug
    root_todos.mkdir(parents=True)
    (root_todos / "requirements.md").write_text("scaffold", encoding="utf-8")

    old_digest = hashlib.sha256(b"old").hexdigest()
    state: dict[str, StateValue] = {
        "artifacts": {"requirements": {"digest": old_digest, "produced_at": "2026-01-01T00:00:00Z"}},
    }

    _restamp_artifact_digest(state, str(worktree), slug, "requirements", "requirements.md")

    artifacts = state["artifacts"]
    assert isinstance(artifacts, dict)
    req = artifacts["requirements"]
    assert isinstance(req, dict)
    assert req["digest"] == hashlib.sha256(b"worktree content").hexdigest()


@pytest.mark.asyncio
async def test_plan_drafting_restamps_digest_when_worker_modified_artifact(tmp_path: Path) -> None:
    """Re-grounding worker modifies implementation-plan.md; plan_drafting restamps digest to prevent staleness loop."""
    slug = "slug-reground"
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    plan_content = "Worker-modified implementation plan that is long enough to pass the scaffold check gate.\n"
    (todo_dir / "implementation-plan.md").write_text(plan_content, encoding="utf-8")
    _write_state(todo_dir, {})
    stale_digest = hashlib.sha256(b"original plan content").hexdigest()
    expected_digest = hashlib.sha256(plan_content.encode()).hexdigest()
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "current": "plan_drafting",
        "artifacts": {"implementation_plan": {"digest": stale_digest, "produced_at": "2026-01-01T00:00:00Z"}},
    }

    keep_going, instruction = await _prepare_step_plan_drafting(AsyncMock(), slug, str(tmp_path), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.PLAN_REVIEW.value
    artifacts = state["artifacts"]
    assert isinstance(artifacts, dict)
    plan = artifacts["implementation_plan"]
    assert isinstance(plan, dict)
    assert plan["digest"] == expected_digest


@pytest.mark.asyncio
async def test_input_assessment_restamps_requirements_digest(tmp_path: Path) -> None:
    """Discovery worker modifies requirements.md; input_assessment restamps digest to prevent staleness loop."""
    slug = "slug-ia-restamp"
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    (todo_dir / "input.md").write_text("input", encoding="utf-8")
    (todo_dir / "requirements.md").write_text(
        "Worker-revised requirements that are long enough to pass the scaffold check gate.\n",
        encoding="utf-8",
    )
    _write_state(todo_dir, {})
    stale_digest = hashlib.sha256(b"old requirements").hexdigest()
    expected_digest = hashlib.sha256(
        b"Worker-revised requirements that are long enough to pass the scaffold check gate.\n"
    ).hexdigest()
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "current": "input_assessment",
        "artifacts": {"requirements": {"digest": stale_digest, "produced_at": "2026-01-01T00:00:00Z"}},
    }

    keep_going, instruction = await _prepare_step_input_assessment(AsyncMock(), slug, str(tmp_path), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.REQUIREMENTS_REVIEW.value
    artifacts = state["artifacts"]
    assert isinstance(artifacts, dict)
    req = artifacts["requirements"]
    assert isinstance(req, dict)
    assert req["digest"] == expected_digest


@pytest.mark.asyncio
async def test_triangulation_restamps_requirements_digest(tmp_path: Path) -> None:
    """Discovery worker modifies requirements.md; triangulation restamps digest to prevent staleness loop."""
    slug = "slug-tri-restamp"
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text(
        "Worker-revised requirements that are long enough to pass the scaffold check gate.\n",
        encoding="utf-8",
    )
    _write_state(todo_dir, {})
    stale_digest = hashlib.sha256(b"old requirements").hexdigest()
    expected_digest = hashlib.sha256(
        b"Worker-revised requirements that are long enough to pass the scaffold check gate.\n"
    ).hexdigest()
    state: dict[str, StateValue] = {
        "schema_version": 2,
        "current": "triangulation",
        "artifacts": {"requirements": {"digest": stale_digest, "produced_at": "2026-01-01T00:00:00Z"}},
    }

    keep_going, instruction = await _prepare_step_triangulation(AsyncMock(), slug, str(tmp_path), state)

    assert keep_going is True
    assert instruction == ""
    assert state["current"] == PreparePhase.REQUIREMENTS_REVIEW.value
    artifacts = state["artifacts"]
    assert isinstance(artifacts, dict)
    req = artifacts["requirements"]
    assert isinstance(req, dict)
    assert req["digest"] == expected_digest


def test_derive_project_root_strips_worktree_suffix() -> None:
    """_derive_project_root extracts project root from worktree path."""
    assert _derive_project_root("/project/trees/my-slug", "my-slug") == "/project"
    assert _derive_project_root("/project", "my-slug") == "/project"
    assert _derive_project_root("/a/b/c/trees/slug", "slug") == "/a/b/c"
