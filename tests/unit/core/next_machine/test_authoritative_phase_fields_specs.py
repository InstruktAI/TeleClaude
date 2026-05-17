"""Canonical lifecycle phase contract tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from teleclaude.cli.telec.handlers import todo as todo_handler
from teleclaude.core.next_machine._types import ItemPhase, PreparePhase, WorkPhase
from teleclaude.core.next_machine.state_io import apply_prepared_state
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def test_todo_state_has_canonical_lifecycle_phase_default() -> None:
    state = TodoState.defaults()

    assert state.lifecycle_phase == PreparePhase.DRAFT.value
    assert state.schema_version == 3


def test_item_phase_remains_independent_of_lifecycle_phase() -> None:
    state = TodoState.defaults()
    state.phase = ItemPhase.IN_PROGRESS.value
    state.lifecycle_phase = PreparePhase.PREPARED.value

    assert state.phase == ItemPhase.IN_PROGRESS.value
    assert state.lifecycle_phase == PreparePhase.PREPARED.value


def test_todo_state_strips_legacy_current_field_on_validation() -> None:
    raw = TodoState.defaults().model_dump(exclude_none=True)
    raw["current"] = PreparePhase.PREPARED.value
    raw["integration_phase"] = "candidate_delivered"

    validated = TodoState.model_validate(raw)
    dumped = validated.model_dump(exclude_none=True)

    assert "current" not in dumped
    assert dumped["integration_phase"] == "candidate_delivered"
    assert dumped["lifecycle_phase"] == PreparePhase.DRAFT.value


def test_apply_prepared_state_writes_lifecycle_phase_prepared_with_plan_review_approved() -> None:
    captured_state: dict[str, StateValue] = {}

    def _fake_write_state_sync(_slug: str, state: dict[str, StateValue]) -> None:
        captured_state.update(state)

    db_stub = MagicMock()
    db_stub.write_state_sync = _fake_write_state_sync
    conn_stub = MagicMock()
    conn_stub.execute.return_value.fetchone.return_value = None
    db_stub._sync_conn.return_value = conn_stub  # pyright: ignore[reportPrivateUsage]

    with (
        patch("teleclaude.core.next_machine.state_io.get_todos_db_sync", return_value=db_stub),
        patch("teleclaude.core.next_machine.state_io.read_phase_state", return_value={"kind": "prepped"}),
        patch("teleclaude.core.next_machine.state_io._has_artifact_content", return_value=True),
        patch("teleclaude.core.next_machine.state_io._artifact_digest", return_value="plan-digest"),
        patch("teleclaude.core.next_machine.state_io.run_git_command", return_value=(0, "abc1234\n", "")),
    ):
        apply_prepared_state("/tmp/cwd", "slug")

    assert captured_state.get("lifecycle_phase") == PreparePhase.PREPARED.value
    plan_review = captured_state.get("plan_review")
    assert isinstance(plan_review, dict)
    assert plan_review.get("verdict") == "approve"
    assert "prepare_phase" not in captured_state


def test_mark_phase_cli_writes_lifecycle_phase_for_prepare_target() -> None:
    with patch(
        "teleclaude.cli.telec.handlers.todo.mark_phase_state",
        return_value={"lifecycle_phase": PreparePhase.PREPARED.value},
    ) as mock_mark:
        exit_code = todo_handler.handle_mark_phase(slug="slug", phase=PreparePhase.PREPARED.value, cwd="/tmp/cwd")

    assert exit_code == 0
    mock_mark.assert_called_once_with("/tmp/cwd", "slug", PreparePhase.PREPARED.value)


def test_mark_phase_cli_writes_lifecycle_phase_for_work_target() -> None:
    with patch(
        "teleclaude.cli.telec.handlers.todo.mark_phase_state",
        return_value={"lifecycle_phase": WorkPhase.BUILD_STARTED.value},
    ) as mock_mark:
        exit_code = todo_handler.handle_mark_phase(slug="slug", phase=WorkPhase.BUILD_STARTED.value, cwd="/tmp/cwd")

    assert exit_code == 0
    mock_mark.assert_called_once_with("/tmp/cwd", "slug", WorkPhase.BUILD_STARTED.value)


def test_mark_phase_cli_rejects_invalid_phase_value_with_listing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = todo_handler.handle_mark_phase(slug="slug", phase="not_a_real_phase", cwd="/tmp/cwd")

    assert exit_code != 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert PreparePhase.PREPARED.value in combined
