from __future__ import annotations

# guard: no-companion
import importlib
from types import ModuleType
from typing import NotRequired, TypedDict

import pytest

from teleclaude.core.next_machine._types import StateValue

pytestmark = [
    pytest.mark.unit,
]


class _TransitionContext(TypedDict):
    actor_id: str
    at: NotRequired[str]
    metadata: NotRequired[dict[str, StateValue]]


def _load_state_machine_module() -> ModuleType:
    try:
        return importlib.import_module("teleclaude.core.next_machine.state_machine")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing v2 state-machine module: {exc.name}")


def test_fire_advances_current_records_history_and_runs_callable_action() -> None:
    module = _load_state_machine_module()
    action_calls: list[str] = []

    def _action(snapshot: dict[str, StateValue], context: _TransitionContext) -> dict[str, StateValue]:
        action_calls.append(str(context["actor_id"]))
        updated = dict(snapshot)
        updated["action_marker"] = "ran"
        return updated

    machine = module.StateMachine(
        states=["input_assessment", "requirements_review", "test_spec_build", "plan_review"],
        transitions=[
            module.TransitionDefinition(
                name="approve_requirements",
                sources={"requirements_review"},
                target="test_spec_build",
                action=_action,
            )
        ],
    )
    snapshot = {
        "schema_version": 2,
        "current": "requirements_review",
        "history": [],
    }

    updated = machine.fire(
        snapshot=snapshot,
        transition="approve_requirements",
        actor_id="session-123",
        at="2025-01-01T00:00:00+00:00",
        metadata={"verdict": "approve"},
    )

    assert updated["current"] == "test_spec_build"
    assert updated["action_marker"] == "ran"
    assert action_calls == ["session-123"]
    assert updated["history"] == [
        {
            "source": "requirements_review",
            "target": "test_spec_build",
            "transition": "approve_requirements",
            "at": "2025-01-01T00:00:00+00:00",
            "by": "session-123",
            "metadata": {"verdict": "approve"},
        }
    ]


def test_fire_is_a_noop_when_current_state_is_already_past_the_target() -> None:
    module = _load_state_machine_module()
    action_calls: list[str] = []

    def _action(snapshot: dict[str, StateValue], context: _TransitionContext) -> dict[str, StateValue]:
        action_calls.append(str(context["actor_id"]))
        return snapshot

    machine = module.StateMachine(
        states=["input_assessment", "requirements_review", "test_spec_build", "plan_review"],
        transitions=[
            module.TransitionDefinition(
                name="approve_requirements",
                sources={"requirements_review"},
                target="test_spec_build",
                action=_action,
            )
        ],
    )
    snapshot = {
        "schema_version": 2,
        "current": "plan_review",
        "history": [
            {
                "source": "requirements_review",
                "target": "test_spec_build",
                "transition": "approve_requirements",
                "at": "2025-01-01T00:00:00+00:00",
                "by": "session-123",
                "metadata": {"verdict": "approve"},
            }
        ],
    }

    updated = machine.fire(
        snapshot=snapshot,
        transition="approve_requirements",
        actor_id="session-999",
        at="2025-01-02T00:00:00+00:00",
        metadata={"verdict": "approve"},
    )

    assert updated["current"] == "plan_review"
    assert updated["history"] == snapshot["history"]
    assert action_calls == []


def test_fire_rejects_when_transition_source_state_has_not_been_reached() -> None:
    module = _load_state_machine_module()

    def _action(snapshot: dict[str, StateValue], _context: _TransitionContext) -> dict[str, StateValue]:
        return snapshot

    machine = module.StateMachine(
        states=["input_assessment", "requirements_review", "test_spec_build", "plan_review"],
        transitions=[
            module.TransitionDefinition(
                name="approve_requirements",
                sources={"requirements_review"},
                target="test_spec_build",
                action=_action,
            )
        ],
    )
    snapshot = {
        "schema_version": 2,
        "current": "input_assessment",
        "history": [],
    }

    with pytest.raises(module.TransitionRejected) as exc_info:
        machine.fire(
            snapshot=snapshot,
            transition="approve_requirements",
            actor_id="session-123",
            at="2025-01-01T00:00:00+00:00",
            metadata={"verdict": "approve"},
        )

    error = exc_info.value
    assert error.current == "input_assessment"
    assert error.transition == "approve_requirements"
    assert error.required_sources == {"requirements_review"}


def test_rewind_restores_previous_current_value_and_pops_last_history_entry() -> None:
    module = _load_state_machine_module()
    machine = module.StateMachine(
        states=["input_assessment", "requirements_review", "test_spec_build", "plan_review"],
        transitions=[],
    )
    snapshot = {
        "schema_version": 2,
        "current": "plan_review",
        "history": [
            {
                "source": "input_assessment",
                "target": "requirements_review",
                "transition": "produce_requirements",
                "at": "2025-01-01T00:00:00+00:00",
                "by": "session-111",
                "metadata": {"digest": "abc"},
            },
            {
                "source": "requirements_review",
                "target": "plan_review",
                "transition": "approve_requirements",
                "at": "2025-01-01T00:05:00+00:00",
                "by": "session-222",
                "metadata": {"verdict": "approve"},
            },
        ],
    }

    rewound = machine.rewind(snapshot=snapshot)

    assert rewound["current"] == "requirements_review"
    assert rewound["history"] == [
        {
            "source": "input_assessment",
            "target": "requirements_review",
            "transition": "produce_requirements",
            "at": "2025-01-01T00:00:00+00:00",
            "by": "session-111",
            "metadata": {"digest": "abc"},
        }
    ]


def test_rewind_rejects_when_the_machine_has_no_history() -> None:
    module = _load_state_machine_module()
    machine = module.StateMachine(
        states=["input_assessment", "requirements_review"],
        transitions=[],
    )
    snapshot = {
        "schema_version": 2,
        "current": "input_assessment",
        "history": [],
    }

    with pytest.raises(module.RewindRejected) as exc_info:
        machine.rewind(snapshot=snapshot)

    error = exc_info.value
    assert error.current == "input_assessment"
