"""Tests for Task 5: structured findings and severity-based verdict in review step handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml


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


def _build_state(findings: list[dict[str, Any]], verdict: str = "") -> dict[str, Any]:
    return {
        "schema_version": 2,
        "prepare_phase": "requirements_review",
        "artifacts": {
            "input": {"digest": "", "produced_at": "2025-01-01", "stale": False},
            "requirements": {"digest": "", "produced_at": "2025-01-01", "stale": False},
            "implementation_plan": {"digest": "", "produced_at": "", "stale": False},
        },
        "requirements_review": {
            "verdict": verdict,
            "reviewed_at": "",
            "findings_count": len(findings),
            "rounds": 0,
            "baseline_commit": "",
            "findings": findings,
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
# Auto-remediation closes the loop (R2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_all_findings_resolved_yields_approve(mock_emit: MagicMock, tmp_path: Path) -> None:
    """All findings resolved (no open) → verdict APPROVE, transitions to PLAN_DRAFTING."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_requirements_review,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    findings = [
        {"id": "f1", "severity": "trivial", "summary": "formatting", "status": "resolved", "resolved_at": "2025-01-01"},
        {"id": "f2", "severity": "substantive", "summary": "coverage", "status": "resolved", "resolved_at": "2025-01-01"},
    ]
    state = _build_state(findings, verdict="approve")
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()
    keep_going, instruction = await _prepare_step_requirements_review(mock_db, slug, cwd, state)

    assert keep_going is True  # transitions to PLAN_DRAFTING
    assert instruction == ""


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_unresolved_substantive_yields_needs_work(mock_emit: MagicMock, tmp_path: Path) -> None:
    """Unresolved substantive finding → NEEDS_WORK, note includes count and file pointer."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_requirements_review,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    findings = [
        {"id": "f1", "severity": "substantive", "summary": "missing coverage", "status": "open"},
    ]
    state = _build_state(findings, verdict="needs_work")
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()

    with patch("teleclaude.core.next_machine.core.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"):
        keep_going, instruction = await _prepare_step_requirements_review(mock_db, slug, cwd, state)

    assert keep_going is False
    # Note must contain count-and-pointer, not markdown content
    assert "1 unresolved" in instruction or "unresolved" in instruction.lower()
    assert "requirements-review-findings.md" in instruction
    # No markdown file content should appear in instruction
    assert "missing coverage" not in instruction  # no content injection


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_unresolved_architectural_yields_blocked(mock_emit: MagicMock, tmp_path: Path) -> None:
    """Unresolved architectural finding → NEEDS_DECISION, BLOCKED output."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_requirements_review,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    findings = [
        {"id": "f1", "severity": "architectural", "summary": "contract mismatch", "status": "open"},
    ]
    state = _build_state(findings, verdict="needs_decision")
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()
    keep_going, instruction = await _prepare_step_requirements_review(mock_db, slug, cwd, state)

    assert keep_going is False
    assert "BLOCKED" in instruction
    assert "architectural" in instruction.lower() or "requirements-review-findings.md" in instruction


@pytest.mark.asyncio
@patch("teleclaude.core.next_machine.core._emit_prepare_event")
async def test_v1_state_no_findings_key_does_not_raise(mock_emit: MagicMock, tmp_path: Path) -> None:
    """v1 state without findings key must not raise KeyError."""
    from teleclaude.core.next_machine.core import (
        _prepare_step_requirements_review,
        write_phase_state,
    )

    cwd, slug = _make_todo(tmp_path)
    _write_file(tmp_path / "todos" / slug, "requirements.md")

    # v1-style state: no findings key
    state: dict[str, Any] = {
        "schema_version": 1,
        "prepare_phase": "requirements_review",
        "requirements_review": {
            "verdict": "",
            "reviewed_at": "",
            "findings_count": 0,
            "rounds": 0,
        },
        "plan_review": {"verdict": "", "findings_count": 0, "rounds": 0},
        "grounding": {
            "valid": False, "base_sha": "", "input_digest": "",
            "referenced_paths": [], "last_grounded_at": "", "invalidated_at": "", "invalidation_reason": "",
        },
    }
    write_phase_state(cwd, slug, state)

    mock_db = MagicMock()
    with patch("teleclaude.core.next_machine.core.compose_agent_guidance", new_callable=AsyncMock, return_value="guidance"):
        keep_going, instruction = await _prepare_step_requirements_review(mock_db, slug, cwd, state)

    # Should dispatch reviewer without raising
    assert keep_going is False
    assert instruction  # some instruction returned


# ---------------------------------------------------------------------------
# needs_decision added to _PREPARE_VERDICT_VALUES
# ---------------------------------------------------------------------------


def test_needs_decision_in_verdict_values() -> None:
    from teleclaude.core.next_machine.core import _PREPARE_VERDICT_VALUES

    assert "needs_decision" in _PREPARE_VERDICT_VALUES


def test_mark_prepare_verdict_accepts_needs_decision(tmp_path: Path) -> None:
    from teleclaude.core.next_machine.core import mark_prepare_verdict

    cwd = str(tmp_path)
    slug = "test"
    (tmp_path / "todos" / slug).mkdir(parents=True)

    # Should not raise
    state = mark_prepare_verdict(cwd, slug, "requirements_review", "needs_decision")
    assert state["requirements_review"]["verdict"] == "needs_decision"  # type: ignore[index]
