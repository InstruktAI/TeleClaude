"""Canonical lifecycle phase contract tests.

# guard: no-companion
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from teleclaude.cli.telec.handlers import todo as todo_handler
from teleclaude.core.next_machine._types import ItemPhase, PreparePhase, WorkPhase
from teleclaude.core.next_machine.phase_derivation import derive_prepare_phase, derive_work_phase
from teleclaude.core.next_machine.state_io import apply_prepared_state
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]


def _prepared_state() -> dict[str, StateValue]:
    return {
        "requirements_review": {"verdict": "approve"},
        "artifacts": {
            "requirements": {"produced_at": "2026-01-01T00:00:00+00:00"},
            "test_specs": {"produced_at": "2026-01-01T00:00:00+00:00"},
            "implementation_plan": {"produced_at": "2026-01-01T00:00:00+00:00"},
        },
        "test_spec_review": {"verdict": "approve"},
        "plan_review": {"verdict": "approve"},
        "dor": {"score": 8, "status": "pass"},
        "grounding": {"valid": True},
        "lifecycle_phase": PreparePhase.PREPARED.value,
    }


def test_todo_state_has_canonical_lifecycle_phase_default() -> None:
    state = TodoState.defaults()

    assert state.lifecycle_phase == PreparePhase.INPUT_ASSESSMENT.value
    assert state.prepare_phase == ""
    assert state.work_phase == ""


def test_item_phase_remains_independent_of_lifecycle_phase() -> None:
    state = TodoState.defaults()
    state.phase = ItemPhase.IN_PROGRESS.value
    state.lifecycle_phase = PreparePhase.PREPARED.value

    assert state.phase == ItemPhase.IN_PROGRESS.value
    assert state.lifecycle_phase == PreparePhase.PREPARED.value


def test_todo_state_strips_legacy_display_only_fields_on_validation() -> None:
    raw = TodoState.defaults().model_dump(exclude_none=True)
    raw["current"] = PreparePhase.PREPARED.value
    raw["integration_phase"] = "candidate_delivered"

    validated = TodoState.model_validate(raw)
    dumped = validated.model_dump(exclude_none=True)

    assert "current" not in dumped
    assert "integration_phase" not in dumped
    assert dumped["lifecycle_phase"] == PreparePhase.INPUT_ASSESSMENT.value


@pytest.mark.asyncio
async def test_derive_prepare_phase_reads_canonical_lifecycle_phase() -> None:
    result = await derive_prepare_phase({"lifecycle_phase": PreparePhase.PLAN_REVIEW.value}, MagicMock(), "slug")

    assert result == PreparePhase.PLAN_REVIEW


def test_derive_work_phase_reads_canonical_lifecycle_phase() -> None:
    result = derive_work_phase({"lifecycle_phase": WorkPhase.REVIEW_APPROVED.value}, "/tmp/worktree", "slug")

    assert result == WorkPhase.REVIEW_APPROVED


def test_apply_prepared_state_writes_lifecycle_phase_prepared() -> None:
    captured_state: dict[str, StateValue] = {}

    def _fake_write_state_sync(_slug: str, state: dict[str, StateValue]) -> None:
        captured_state.update(state)

    db_stub = MagicMock()
    db_stub.write_state_sync = _fake_write_state_sync
    conn_stub = MagicMock()
    conn_stub.execute.return_value.fetchone.return_value = None
    db_stub._sync_conn.return_value = conn_stub  # pyright: ignore[reportPrivateUsage]

    with (
        patch("teleclaude.core.next_machine.state_io._get_todos_db_sync", return_value=db_stub),
        patch("teleclaude.core.next_machine.state_io.read_phase_state", return_value={"kind": "bug"}),
        patch("teleclaude.core.next_machine.state_io._has_artifact_content", return_value=True),
        patch("teleclaude.core.next_machine.state_io.run_git_command", return_value=(0, "abc1234\n", "")),
    ):
        apply_prepared_state("/tmp/cwd", "slug")

    assert captured_state.get("lifecycle_phase") == PreparePhase.PREPARED.value
    assert captured_state.get("prepare_phase") == ""


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
    assert WorkPhase.BUILD_STARTED.value in combined
