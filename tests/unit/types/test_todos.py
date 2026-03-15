"""Characterization tests for teleclaude.types.todos."""

from __future__ import annotations

from teleclaude.types.todos import BreakdownState, DorActions, DorState, TodoState


def test_dor_actions_allows_extra_fields_and_keeps_declared_defaults() -> None:
    actions = DorActions.model_validate({"notes": "updated during review"})

    assert actions.model_extra == {"notes": "updated during review"}
    assert actions.model_dump() == {
        "requirements_updated": False,
        "implementation_plan_updated": False,
        "notes": "updated during review",
    }


def test_dor_state_defaults_to_empty_lists_and_embedded_dor_actions() -> None:
    state = DorState()

    assert state.last_assessed_at is None
    assert state.score == 0
    assert state.status == "needs_work"
    assert state.schema_version == 1
    assert state.blockers == []
    assert isinstance(state.actions_taken, DorActions)
    assert state.actions_taken.model_dump() == {
        "requirements_updated": False,
        "implementation_plan_updated": False,
    }


def test_dor_state_preserves_legacy_action_lists() -> None:
    state = DorState(actions_taken=["requirements.md", "implementation-plan.md"])

    assert state.actions_taken == ["requirements.md", "implementation-plan.md"]


def test_breakdown_state_defaults_to_unassessed_with_no_todos() -> None:
    breakdown = BreakdownState()

    assert breakdown.assessed is False
    assert breakdown.todos == []


def test_todo_state_uses_fresh_nested_defaults_per_instance() -> None:
    left = TodoState(dor=DorState())
    right = TodoState(dor=DorState())

    left.breakdown.todos.append("Write tests")
    left.unresolved_findings.append("R1-F1")
    assert left.dor is not None
    left.dor.blockers.append("Need fixture coverage")

    assert right.breakdown.todos == []
    assert right.unresolved_findings == []
    assert right.dor is not None
    assert right.dor.blockers == []


def test_todo_state_defaults_match_pending_review_workflow() -> None:
    state = TodoState()

    assert state.model_dump() == {
        "kind": "todo",
        "build": "pending",
        "review": "pending",
        "deferrals_processed": False,
        "breakdown": {"assessed": False, "todos": []},
        "dor": None,
        "review_round": 0,
        "max_review_rounds": 3,
        "review_baseline_commit": "",
        "unresolved_findings": [],
        "resolved_findings": [],
        "schema_version": 1,
    }
