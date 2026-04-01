"""Unit tests for the StateMachine engine — pure target-based transitions."""

from __future__ import annotations

# guard: no-companion
import pytest

from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.state_machine import State, StateMachine, TargetContext

pytestmark = [
    pytest.mark.unit,
]


def test_target_advances_current_records_history_and_runs_on_enter() -> None:
    """Targeting a state sets current, appends history, and calls on_enter."""
    on_enter_calls: list[str] = []

    def _on_enter(snapshot: dict[str, StateValue], context: TargetContext) -> dict[str, StateValue]:
        on_enter_calls.append(context.actor_id)
        updated = dict(snapshot)
        updated["on_enter_marker"] = "ran"
        return updated

    machine = StateMachine(
        states=[
            State("input_assessment"),
            State("requirements_review"),
            State("test_spec_build", on_enter=_on_enter),
            State("plan_review"),
        ],
    )
    snapshot = {
        "schema_version": 2,
        "current": "requirements_review",
        "history": [],
    }

    ctx = TargetContext(
        worktree_path="/repo",
        project_root="/repo",
        slug="test-slug",
        actor_id="session-123",
        at="2025-01-01T00:00:00+00:00",
    )
    updated = machine.target(snapshot, "test_spec_build", ctx)

    assert updated["current"] == "test_spec_build"
    assert updated["on_enter_marker"] == "ran"
    assert on_enter_calls == ["session-123"]
    assert updated["history"] == [
        {
            "source": "requirements_review",
            "target": "test_spec_build",
            "by": "session-123",
            "at": "2025-01-01T00:00:00+00:00",
            "metadata": {},
        }
    ]


def test_target_is_noop_when_already_at_target() -> None:
    """Targeting the current state is a no-op — no history, no on_enter."""
    on_enter_calls: list[str] = []

    def _on_enter(snapshot: dict[str, StateValue], context: TargetContext) -> dict[str, StateValue]:
        on_enter_calls.append(context.actor_id)
        return snapshot

    machine = StateMachine(
        states=[
            State("input_assessment"),
            State("test_spec_build", on_enter=_on_enter),
        ],
    )
    snapshot = {
        "schema_version": 2,
        "current": "test_spec_build",
        "history": [],
    }

    ctx = TargetContext(
        worktree_path="/repo",
        project_root="/repo",
        slug="test-slug",
        actor_id="session-999",
        at="2025-01-02T00:00:00+00:00",
    )
    updated = machine.target(snapshot, "test_spec_build", ctx)

    assert updated["current"] == "test_spec_build"
    assert not updated["history"]
    assert not on_enter_calls


def test_target_raises_for_unknown_state() -> None:
    """Targeting an unknown state raises ValueError."""
    machine = StateMachine(
        states=[
            State("input_assessment"),
            State("requirements_review"),
        ],
    )
    snapshot = {
        "schema_version": 2,
        "current": "input_assessment",
        "history": [],
    }

    ctx = TargetContext(
        worktree_path="/repo",
        project_root="/repo",
        slug="test-slug",
        actor_id="session-123",
        at="2025-01-01T00:00:00+00:00",
    )

    with pytest.raises(ValueError, match="unknown state"):
        machine.target(snapshot, "nonexistent_state", ctx)


def test_target_without_on_enter_just_advances() -> None:
    """State without on_enter still advances current and records history."""
    machine = StateMachine(
        states=[
            State("input_assessment"),
            State("requirements_review"),
            State("test_spec_build"),
        ],
    )
    snapshot = {
        "schema_version": 2,
        "current": "input_assessment",
        "history": [],
    }

    ctx = TargetContext(
        worktree_path="/repo",
        project_root="/repo",
        slug="test-slug",
        actor_id="session-123",
        at="2025-01-01T00:00:00+00:00",
    )
    updated = machine.target(snapshot, "test_spec_build", ctx)

    assert updated["current"] == "test_spec_build"
    assert len(updated["history"]) == 1
