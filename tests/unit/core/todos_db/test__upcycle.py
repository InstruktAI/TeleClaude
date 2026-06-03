"""Tests for lazy todo state upcycling."""

from __future__ import annotations

import pytest

from teleclaude.core.todos_db._upcycle import LATEST_TODO_STATE_SCHEMA_VERSION, upcycle_state_dict
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue

pytestmark = pytest.mark.unit


def _upcycle_v2_phase(old_phase: str) -> dict[str, StateValue]:
    result = upcycle_state_dict(
        {
            "schema_version": 2,
            "phase": "pending",
            "kind": "todo",
            "lifecycle_phase": old_phase,
            "prepare_pair": {"slot_a": {"session_id": "a"}},
            "grounding": {"valid": True},
        }
    )

    assert result["schema_version"] == LATEST_TODO_STATE_SCHEMA_VERSION
    assert result["kind"] == "feature"
    assert "prepare_pair" not in result
    assert "grounding" not in result
    assert "approvals" in result
    return result


def test_upcycle_v2_discovery_phase_maps_to_draft() -> None:
    assert _upcycle_v2_phase("input_assessment")["lifecycle_phase"] == "draft"


def test_upcycle_v2_requirements_review_maps_to_prd_drafting() -> None:
    assert _upcycle_v2_phase("requirements_review")["lifecycle_phase"] == "prd_drafting"


def test_upcycle_v2_test_spec_review_maps_to_architecture_review() -> None:
    assert _upcycle_v2_phase("test_spec_review")["lifecycle_phase"] == "architecture_review"


def test_upcycle_v2_plan_review_maps_to_plan_drafting() -> None:
    assert _upcycle_v2_phase("plan_review")["lifecycle_phase"] == "plan_drafting"


def test_upcycle_v2_grounding_check_maps_to_prepared() -> None:
    assert _upcycle_v2_phase("grounding_check")["lifecycle_phase"] == "prepared"


def test_upcycle_v2_work_phase_is_preserved() -> None:
    assert _upcycle_v2_phase("build_started")["lifecycle_phase"] == "build_started"


def test_upcycle_v2_legacy_handed_off_maps_to_finalize_ready() -> None:
    assert _upcycle_v2_phase("handed_off")["lifecycle_phase"] == LifecyclePhase.FINALIZE_READY.value


def test_upcycle_v1_pending_todo_without_lifecycle_phase_maps_to_latest_draft() -> None:
    result = upcycle_state_dict(
        {
            "schema_version": 1,
            "phase": "pending",
            "kind": "todo",
        }
    )

    assert result["schema_version"] == LATEST_TODO_STATE_SCHEMA_VERSION
    assert result["lifecycle_phase"] == "draft"


def test_upcycle_v1_delivered_row_without_lifecycle_phase_maps_to_finalize_ready() -> None:
    result = upcycle_state_dict(
        {
            "schema_version": 1,
            "phase": "delivered",
            "kind": "todo",
            "finalize": {"status": "handed_off", "handed_off_at": "2026-03-01T00:00:00+00:00"},
            "build_review": {"verdict": "approve"},
        }
    )

    assert result["schema_version"] == LATEST_TODO_STATE_SCHEMA_VERSION
    assert result["lifecycle_phase"] == LifecyclePhase.FINALIZE_READY.value
    finalize = result["finalize"]
    assert isinstance(finalize, dict)
    assert finalize["status"] == "ready"
    assert "handed_off_at" not in finalize


def test_upcycle_v3_legacy_handed_off_contract_maps_to_finalize_ready() -> None:
    result = upcycle_state_dict(
        {
            "schema_version": 3,
            "phase": "pending",
            "kind": "feature",
            "lifecycle_phase": "handed_off",
            "finalize": {
                "status": "handed_off",
                "branch": "ready-branch",
                "sha": "abc123",
                "ready_at": "2026-03-01T00:00:00+00:00",
                "handed_off_at": "2026-03-01T00:05:00+00:00",
            },
        }
    )

    assert result["schema_version"] == LATEST_TODO_STATE_SCHEMA_VERSION
    assert result["lifecycle_phase"] == LifecyclePhase.FINALIZE_READY.value
    finalize = result["finalize"]
    assert isinstance(finalize, dict)
    assert finalize["status"] == "ready"
    assert finalize["branch"] == "ready-branch"
    assert "handed_off_at" not in finalize
