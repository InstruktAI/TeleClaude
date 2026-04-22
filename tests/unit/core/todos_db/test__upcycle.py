"""Tests for lazy v1->v2 todo state upcycling."""

from __future__ import annotations

import pytest

from teleclaude.core.todos_db._upcycle import upcycle_state_dict

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def test_upcycle_v1_pending_todo_without_lifecycle_phase_maps_to_input_assessment() -> None:
    result = upcycle_state_dict(
        {
            "schema_version": 1,
            "phase": "pending",
            "kind": "todo",
        }
    )

    assert result["schema_version"] == 2
    assert result["lifecycle_phase"] == "input_assessment"


def test_upcycle_v1_prepare_progress_without_lifecycle_phase_maps_from_authority() -> None:
    result = upcycle_state_dict(
        {
            "schema_version": 1,
            "phase": "pending",
            "kind": "todo",
            "requirements_review": {"verdict": "approve"},
            "dor": {"status": "pass", "score": 8, "schema_version": 1, "blockers": []},
            "grounding": {"valid": False},
            "artifacts": {
                "requirements": {"produced_at": ""},
                "test_specs": {"produced_at": ""},
                "implementation_plan": {"produced_at": ""},
            },
        }
    )

    assert result["schema_version"] == 2
    assert result["lifecycle_phase"] == "grounding_check"


def test_upcycle_v1_delivered_row_without_lifecycle_phase_maps_to_handed_off() -> None:
    result = upcycle_state_dict(
        {
            "schema_version": 1,
            "phase": "delivered",
            "kind": "todo",
            "finalize": {"status": "handed_off"},
            "build_review": {"verdict": "approve"},
        }
    )

    assert result["schema_version"] == 2
    assert result["lifecycle_phase"] == "handed_off"
