"""Characterization tests for prepare step handlers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from teleclaude.core.next_machine._types import DOR_READY_THRESHOLD, PreparePhase, StateValue
from teleclaude.core.next_machine.prepare_steps import (
    _prepare_dispatch,
    _prepare_step_grounding_check,
    _prepare_step_re_grounding,
)


def _write_state(todo_dir: Path, state: dict[object, object]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def test_prepare_step_grounding_check_first_pass_captures_baseline_and_marks_prepared(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-a"
    todo_dir.mkdir(parents=True)
    (todo_dir / "input.md").write_text("hello", encoding="utf-8")
    state: dict[str, StateValue] = {"grounding": {}}

    with (
        patch("teleclaude.core.next_machine.prepare_steps._run_git_prepare", return_value=(0, "abc123\n", "")),
        patch("teleclaude.core.next_machine.prepare_steps._emit_prepare_event"),
    ):
        keep_going, instruction = _prepare_step_grounding_check("slug-a", str(tmp_path), state)

    prepare_phase = state.get("prepare_phase")
    grounding = state.get("grounding")
    assert isinstance(grounding, dict)
    assert keep_going is True
    assert instruction == ""
    assert prepare_phase == PreparePhase.PREPARED.value
    assert grounding["base_sha"] == "abc123"
    assert grounding["input_digest"] == hashlib.sha256(b"hello").hexdigest()
    assert grounding["valid"] is True


def test_prepare_step_grounding_check_invalidates_when_input_digest_changes(tmp_path: Path) -> None:
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
        patch("teleclaude.core.next_machine.prepare_steps._run_git_prepare", return_value=(0, "abc123\n", "")),
        patch("teleclaude.core.next_machine.prepare_steps._emit_prepare_event"),
    ):
        keep_going, instruction = _prepare_step_grounding_check("slug-b", str(tmp_path), state)

    prepare_phase = state.get("prepare_phase")
    grounding = state.get("grounding")
    assert isinstance(grounding, dict)
    assert keep_going is True
    assert instruction == ""
    assert prepare_phase == PreparePhase.RE_GROUNDING.value
    assert grounding["valid"] is False
    assert grounding["invalidation_reason"] == "input_updated"


@pytest.mark.asyncio
async def test_prepare_step_re_grounding_resets_plan_review_and_dispatches_redraft(tmp_path: Path) -> None:
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

    prepare_phase = state.get("prepare_phase")
    plan_review = state.get("plan_review")
    assert isinstance(plan_review, dict)
    assert keep_going is False
    assert prepare_phase == PreparePhase.PLAN_REVIEW.value
    assert plan_review["verdict"] == ""
    assert "Changed files: src/app.py" in instruction
    assert 'telec sessions run --command "/next-prepare-draft" --args "slug-c"' in instruction


@pytest.mark.asyncio
async def test_prepare_dispatch_returns_blocked_message_for_blocked_phase() -> None:
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
    assert state["prepare_phase"] == PreparePhase.PLAN_DRAFTING.value
    assert persisted["prepare_phase"] == PreparePhase.PLAN_DRAFTING.value


@pytest.mark.asyncio
async def test_prepare_dispatch_advances_approved_plan_review_to_gate(tmp_path: Path) -> None:
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
    assert state["prepare_phase"] == PreparePhase.GATE.value
    assert persisted["prepare_phase"] == PreparePhase.GATE.value


@pytest.mark.asyncio
async def test_prepare_dispatch_records_baseline_and_dispatches_plan_review(tmp_path: Path) -> None:
    todo_dir = tmp_path / "todos" / "slug-g"
    _write_state(todo_dir, {})
    state: dict[str, StateValue] = {}

    with (
        patch("teleclaude.core.next_machine.prepare_steps._run_git_prepare", return_value=(0, "abc123\n", "")),
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
    assert state["prepare_phase"] == PreparePhase.GROUNDING_CHECK.value
    assert persisted["prepare_phase"] == PreparePhase.GROUNDING_CHECK.value


@pytest.mark.asyncio
async def test_prepare_dispatch_requests_gate_worker_when_dor_is_below_threshold(tmp_path: Path) -> None:
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
