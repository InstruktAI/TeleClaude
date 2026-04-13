"""Unit tests for phase derivation pure functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine._types import PreparePhase, WorkPhase
from teleclaude.core.next_machine.phase_derivation import (
    derive_prepare_phase,
    derive_work_phase,
    is_prepared,
)

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


# ── derive_prepare_phase ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_derive_prepare_phase_returns_input_assessment_when_no_requirements() -> None:
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=False)

    result = await derive_prepare_phase({}, todos_db, "slug")

    assert result == PreparePhase.INPUT_ASSESSMENT


@pytest.mark.asyncio
async def test_derive_prepare_phase_returns_prepared_when_all_primitives_satisfied() -> None:
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)

    state = {
        "requirements_review": {"verdict": "approve"},
        "artifacts": {"test_specs": {"produced_at": "2026-01-01"}},
        "test_spec_review": {"verdict": "approve"},
        "plan_review": {"verdict": "approve"},
        "dor": {"score": 8},
        "grounding": {"valid": True},
    }

    result = await derive_prepare_phase(state, todos_db, "slug")

    assert result == PreparePhase.PREPARED


@pytest.mark.asyncio
async def test_derive_prepare_phase_prepped_todo_skips_requirements() -> None:
    """Prepped todos with requirements_review.verdict='skipped' bypass requirements artifact."""
    todos_db = AsyncMock()

    # requirements artifact does NOT exist, but verdict is "skipped"
    async def _artifact_exists(_slug: str, name: str) -> bool:
        return name != "requirements"

    todos_db.artifact_exists = _artifact_exists

    state = {
        "requirements_review": {"verdict": "skipped"},
        "artifacts": {"test_specs": {"produced_at": "2026-01-01"}},
        "test_spec_review": {"verdict": "approve"},
        "plan_review": {"verdict": "approve"},
        "dor": {"score": 8},
        "grounding": {"valid": True},
    }

    result = await derive_prepare_phase(state, todos_db, "slug")

    assert result == PreparePhase.PREPARED


@pytest.mark.asyncio
async def test_derive_prepare_phase_bug_todo_skips_requirements_and_specs() -> None:
    """Bug todos with all verdicts 'skipped' bypass requirements, specs, and plan."""
    todos_db = AsyncMock()

    async def _artifact_exists(_slug: str, name: str) -> bool:
        return name not in ("requirements", "implementation-plan")

    todos_db.artifact_exists = _artifact_exists

    state = {
        "requirements_review": {"verdict": "skipped"},
        "artifacts": {"test_specs": {"produced_at": "2026-01-01"}},
        "test_spec_review": {"verdict": "skipped"},
        "plan_review": {"verdict": "skipped"},
        "dor": {"score": 8},
        "grounding": {"valid": True},
    }

    result = await derive_prepare_phase(state, todos_db, "slug")

    assert result == PreparePhase.PREPARED


@pytest.mark.asyncio
async def test_derive_prepare_phase_returns_gate_when_dor_below_threshold() -> None:
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)

    state = {
        "requirements_review": {"verdict": "approve"},
        "artifacts": {"test_specs": {"produced_at": "2026-01-01"}},
        "test_spec_review": {"verdict": "approve"},
        "plan_review": {"verdict": "approve"},
        "dor": {"score": 5},
        "grounding": {"valid": True},
    }

    result = await derive_prepare_phase(state, todos_db, "slug")

    assert result == PreparePhase.GATE


@pytest.mark.asyncio
async def test_is_prepared_returns_true_when_all_satisfied() -> None:
    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)

    state = {
        "requirements_review": {"verdict": "approve"},
        "artifacts": {"test_specs": {"produced_at": "2026-01-01"}},
        "test_spec_review": {"verdict": "approve"},
        "plan_review": {"verdict": "approve"},
        "dor": {"score": 8},
        "grounding": {"valid": True},
    }

    assert await is_prepared(state, todos_db, "slug") is True


# ── derive_work_phase ─────────────────────────────────────────────────────────


def test_derive_work_phase_returns_build_started_for_empty_state() -> None:
    with patch(
        "teleclaude.core.next_machine.phase_derivation._has_build_commits_beyond_main",
        return_value=False,
    ):
        result = derive_work_phase({}, "/tmp/wt", "slug")

    assert result == WorkPhase.BUILD_STARTED


def test_derive_work_phase_returns_build_complete_when_gates_pass() -> None:
    with patch(
        "teleclaude.core.next_machine.phase_derivation._has_build_commits_beyond_main",
        return_value=True,
    ):
        result = derive_work_phase({}, "/tmp/wt", "slug", gates_checker=lambda *_: (True, ""))

    assert result == WorkPhase.BUILD_COMPLETE


def test_derive_work_phase_returns_review_approved_when_verdict_stamped() -> None:
    state = {"build_review": {"verdict": "approve"}}
    result = derive_work_phase(state, "/tmp/wt", "slug")

    assert result == WorkPhase.REVIEW_APPROVED


def test_derive_work_phase_returns_finalize_ready_when_stamped() -> None:
    state = {"finalize": {"status": "ready"}}
    result = derive_work_phase(state, "/tmp/wt", "slug")

    assert result == WorkPhase.FINALIZE_READY


def test_derive_work_phase_returns_handed_off_when_stamped() -> None:
    state = {"finalize": {"status": "handed_off"}}
    result = derive_work_phase(state, "/tmp/wt", "slug")

    assert result == WorkPhase.HANDED_OFF


def test_derive_work_phase_returns_changes_requested_when_verdict_stamped() -> None:
    state = {"build_review": {"verdict": "changes_requested"}}
    result = derive_work_phase(state, "/tmp/wt", "slug")

    assert result == WorkPhase.REVIEW_CHANGES_REQUESTED
