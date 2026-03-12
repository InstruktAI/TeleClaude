"""Tests for Task 6: audit trail stamping in prepare phase handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LONG = "This content is long enough to pass the scaffold content threshold check for tests."


def _make_todo(tmp_path: Path, slug: str = "test-slug") -> tuple[str, str]:
    todo_dir = tmp_path / "todos" / slug
    todo_dir.mkdir(parents=True)
    return str(tmp_path), slug


def _write_file(todo_dir: Path, name: str, content: str = _LONG) -> Path:
    p = todo_dir / name
    p.write_text(content)
    return p


def _build_state(phase: str = "") -> dict[str, Any]:
    return {
        "schema_version": 2,
        "prepare_phase": phase,
        "artifacts": {
            "input": {"digest": "", "produced_at": "", "stale": False},
            "requirements": {"digest": "", "produced_at": "", "stale": False},
            "implementation_plan": {"digest": "", "produced_at": "", "stale": False},
        },
        "requirements_review": {
            "verdict": "",
            "reviewed_at": "",
            "findings_count": 0,
            "rounds": 0,
            "baseline_commit": "",
            "findings": [],
        },
        "plan_review": {
            "verdict": "",
            "reviewed_at": "",
            "findings_count": 0,
            "rounds": 0,
            "baseline_commit": "",
            "findings": [],
        },
        "audit": {
            "input_assessment": {"started_at": "", "completed_at": ""},
            "triangulation": {"started_at": "", "completed_at": ""},
            "requirements_review": {
                "started_at": "",
                "completed_at": "",
                "baseline_commit": "",
                "verdict": "",
                "rounds": 0,
                "findings": [],
            },
            "plan_drafting": {"started_at": "", "completed_at": ""},
            "plan_review": {
                "started_at": "",
                "completed_at": "",
                "baseline_commit": "",
                "verdict": "",
                "rounds": 0,
                "findings": [],
            },
            "gate": {"started_at": "", "completed_at": ""},
        },
        "grounding": {
            "valid": False,
            "base_sha": "",
            "input_digest": "",
            "referenced_paths": [],
            "last_grounded_at": "",
            "invalidated_at": "",
            "invalidation_reason": "",
        },
    }


# ---------------------------------------------------------------------------
# input_assessment audit stamping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_input_assessment_stamps_started_at(mock_emit: MagicMock, tmp_path: Path) -> None:
    """_prepare_step_input_assessment stamps audit.input_assessment.started_at on entry."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_input_assessment,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md")

    state = _build_state("input_assessment")
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()
    with patch("teleclaude.core.next_machine.core.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"):
        await _prepare_step_input_assessment(mock_db, slug, cwd, state)

    audit = state.get("audit", {})
    assert isinstance(audit, dict)
    started = audit.get("input_assessment", {}).get("started_at", "")
    assert started, f"expected started_at to be populated, got {started!r}"


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_input_assessment_stamps_completed_at_on_transition(
    mock_emit: MagicMock, tmp_path: Path
) -> None:
    """_prepare_step_input_assessment stamps completed_at when transitioning to requirements_review."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_input_assessment,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "input.md")
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    state = _build_state("input_assessment")
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()
    with patch("teleclaude.core.next_machine.prepare_helpers._emit_prepare_event"):
        keep_going, _ = await _prepare_step_input_assessment(mock_db, slug, cwd, state)

    assert keep_going is True
    audit = state.get("audit", {})
    assert isinstance(audit, dict)
    completed = audit.get("input_assessment", {}).get("completed_at", "")
    assert completed, f"expected completed_at on transition, got {completed!r}"


# ---------------------------------------------------------------------------
# requirements_review audit stamping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_requirements_review_stamps_started_at(mock_emit: MagicMock, tmp_path: Path) -> None:
    """_prepare_step_requirements_review stamps audit.requirements_review.started_at on entry."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_requirements_review,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    state = _build_state("requirements_review")
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()
    with patch("teleclaude.core.next_machine.core.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"):
        await _prepare_step_requirements_review(mock_db, slug, cwd, state)

    audit = state.get("audit", {})
    assert isinstance(audit, dict)
    started = audit.get("requirements_review", {}).get("started_at", "")
    assert started, f"expected started_at to be populated, got {started!r}"


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_requirements_review_stamps_verdict_and_completed_on_approve(
    mock_emit: MagicMock, tmp_path: Path
) -> None:
    """Approving requirements stamps audit.requirements_review.verdict and completed_at."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_requirements_review,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    state = _build_state("requirements_review")
    state["requirements_review"]["verdict"] = "approve"  # type: ignore[index]
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()
    keep_going, _ = await _prepare_step_requirements_review(mock_db, slug, cwd, state)

    assert keep_going is True
    audit = state.get("audit", {})
    assert isinstance(audit, dict)
    rr_audit = audit.get("requirements_review", {})
    assert rr_audit.get("completed_at"), "expected completed_at on approval"
    assert rr_audit.get("verdict") == "approve"


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_requirements_review_stamps_rounds_on_needs_work(
    mock_emit: MagicMock, tmp_path: Path
) -> None:
    """needs_work verdict stamps audit.requirements_review.rounds."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_requirements_review,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    state = _build_state("requirements_review")
    state["requirements_review"]["verdict"] = "needs_work"  # type: ignore[index]
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()
    with patch("teleclaude.core.next_machine.core.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"):
        keep_going, _ = await _prepare_step_requirements_review(mock_db, slug, cwd, state)

    assert keep_going is False
    audit = state.get("audit", {})
    assert isinstance(audit, dict)
    rr_audit = audit.get("requirements_review", {})
    assert rr_audit.get("rounds") == 1
