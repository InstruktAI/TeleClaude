"""xfail spec contract for the authoritative-phase-fields todo.

# guard: no-companion


Every test in this module is marked xfail until the implementation lands. The
builder removes the xfail marker per task as the corresponding requirement is
satisfied. Assertions pin the behavioral contract; they must not be weakened
when the markers are removed.

Spec inventory (mirrors test-specs.md):
- R1: TodoState fields and item-level independence.
- R2: Authoritative field beats primitives, with primitive fallback.
- R3: Disagreement warning.
- R4: Step handlers and apply_prepared_state write the authoritative field.
- R5: mark-phase CLI dispatches by enum membership and rejects invalid input.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.next_machine._types import ItemPhase, PreparePhase, StateValue, WorkPhase

if TYPE_CHECKING:
    pass

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]

# Tests that pin the NEW behavior carry strict-xfail individually. Fallback /
# regression-guard tests remain regular pytest because they assert behavior
# that already exists and must not regress.
_pins_new_behavior = pytest.mark.xfail(strict=True, reason="awaits authoritative-phase-fields impl")


# ── R1: state model ──────────────────────────────────────────────────────────


@_pins_new_behavior
def test_todo_state_has_authoritative_subphase_fields_with_empty_default() -> None:
    """TodoState must carry prepare_phase and work_phase as strings defaulting to ''."""
    from teleclaude.types.todos import TodoState  # type: ignore[import-not-found]

    state = TodoState.defaults()

    assert hasattr(state, "prepare_phase")
    assert hasattr(state, "work_phase")
    assert state.prepare_phase == ""
    assert state.work_phase == ""
    assert isinstance(state.prepare_phase, str)
    assert isinstance(state.work_phase, str)


@_pins_new_behavior
def test_item_phase_remains_independent_of_subphase_fields() -> None:
    """Item-level phase keeps holding ItemPhase values; sub-phase fields are independent."""
    from teleclaude.types.todos import TodoState  # type: ignore[import-not-found]

    state = TodoState.defaults()
    state.phase = ItemPhase.IN_PROGRESS.value
    state.prepare_phase = PreparePhase.PREPARED.value
    state.work_phase = WorkPhase.BUILD_STARTED.value

    assert state.phase == ItemPhase.IN_PROGRESS.value
    assert state.prepare_phase == PreparePhase.PREPARED.value
    assert state.work_phase == WorkPhase.BUILD_STARTED.value


# ── R2: derivation precedence ────────────────────────────────────────────────


@_pins_new_behavior
@pytest.mark.asyncio
async def test_derive_prepare_phase_returns_authoritative_field_when_set() -> None:
    """Authoritative prepare_phase value beats primitive derivation."""
    from teleclaude.core.next_machine.phase_derivation import derive_prepare_phase

    todos_db = AsyncMock()
    # primitives would derive to INPUT_ASSESSMENT (no requirements artifact)
    todos_db.artifact_exists = AsyncMock(return_value=False)

    state = {"prepare_phase": PreparePhase.PREPARED.value}

    result = await derive_prepare_phase(state, todos_db, "slug")

    assert result == PreparePhase.PREPARED


@_pins_new_behavior
def test_derive_work_phase_returns_authoritative_field_when_set() -> None:
    """Authoritative work_phase value beats primitive derivation.

    Primitive logic on this state would return BUILD_STARTED (no worktree, no
    finalize, no verdict). Authoritative says REVIEW_APPROVED. The new
    contract requires the authoritative value to win.
    """
    from teleclaude.core.next_machine.phase_derivation import derive_work_phase

    state = {"work_phase": WorkPhase.REVIEW_APPROVED.value}

    result = derive_work_phase(state, "/tmp/worktree", "slug", gates_checker=lambda _c, _s: (True, ""))

    assert result == WorkPhase.REVIEW_APPROVED


@pytest.mark.asyncio
async def test_derive_prepare_phase_falls_back_to_primitives_when_unset() -> None:
    """Empty prepare_phase falls through to primitive derivation."""
    from teleclaude.core.next_machine.phase_derivation import derive_prepare_phase

    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=False)

    state = {"prepare_phase": ""}

    result = await derive_prepare_phase(state, todos_db, "slug")

    assert result == PreparePhase.INPUT_ASSESSMENT


def test_derive_work_phase_falls_back_to_primitives_when_unset() -> None:
    """Empty work_phase falls through to primitive derivation."""
    from teleclaude.core.next_machine.phase_derivation import derive_work_phase

    state = {
        "work_phase": "",
        "build_review": {"verdict": "approve"},
    }

    result = derive_work_phase(state, "/tmp/worktree", "slug", gates_checker=lambda _c, _s: (True, ""))

    assert result == WorkPhase.REVIEW_APPROVED


# ── R3: consistency-check warning ────────────────────────────────────────────


@_pins_new_behavior
@pytest.mark.asyncio
async def test_derivation_logs_warning_on_authoritative_field_disagreement(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Disagreement between authoritative field and primitives logs a warning."""
    from teleclaude.core.next_machine.phase_derivation import derive_prepare_phase

    todos_db = AsyncMock()
    # primitives would say INPUT_ASSESSMENT; authoritative claims PREPARED
    todos_db.artifact_exists = AsyncMock(return_value=False)

    state = {"prepare_phase": PreparePhase.PREPARED.value}

    with caplog.at_level(logging.WARNING):
        result = await derive_prepare_phase(state, todos_db, "slug-x")

    # authoritative is preserved despite the warning
    assert result == PreparePhase.PREPARED
    # warning surfaces both values and the slug
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "slug-x" in m and PreparePhase.PREPARED.value in m and PreparePhase.INPUT_ASSESSMENT.value in m
        for m in warnings
    )


# ── R4: state-machine writes ─────────────────────────────────────────────────


@_pins_new_behavior
@pytest.mark.asyncio
async def test_prepare_step_transitions_write_authoritative_phase() -> None:
    """A representative prepare step writes prepare_phase to the destination value."""
    from teleclaude.core.next_machine import prepare_steps  # type: ignore[import-not-found]

    captured: dict[str, StateValue] = {}

    async def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
        captured["state"] = state

    with patch.object(prepare_steps, "write_phase_state", _fake_write):
        # Invoke a prepare step entrypoint that completes a transition. The
        # builder picks the canonical entrypoint; this assertion only needs
        # the state-write to carry prepare_phase.
        await prepare_steps.handle_input_assessment_complete(  # type: ignore[attr-defined]
            db=MagicMock(),
            todos_db=AsyncMock(),
            slug="slug",
            cwd="/tmp/cwd",
            state={},
        )

    written = captured.get("state", {})
    assert isinstance(written, dict)
    assert written.get("prepare_phase") in {p.value for p in PreparePhase}


@_pins_new_behavior
@pytest.mark.asyncio
async def test_work_step_transitions_write_authoritative_phase() -> None:
    """A representative work step writes work_phase to the destination value."""
    from teleclaude.core.next_machine import work_steps  # type: ignore[import-not-found]

    captured: dict[str, StateValue] = {}

    async def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
        captured["state"] = state

    with patch.object(work_steps, "write_phase_state", _fake_write):
        await work_steps.handle_build_started(  # type: ignore[attr-defined]
            db=MagicMock(),
            todos_db=AsyncMock(),
            slug="slug",
            cwd="/tmp/cwd",
            state={},
        )

    written = captured.get("state", {})
    assert isinstance(written, dict)
    assert written.get("work_phase") in {p.value for p in WorkPhase}


@_pins_new_behavior
def test_apply_prepared_state_writes_prepare_phase_prepared() -> None:
    """apply_prepared_state must set prepare_phase = 'prepared'."""
    from teleclaude.core.next_machine.state_io import apply_prepared_state

    captured: dict[str, StateValue] = {}

    def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
        captured["state"] = state

    with patch("teleclaude.core.next_machine.state_io.write_phase_state", _fake_write):
        apply_prepared_state("/tmp/cwd", "slug")

    written = captured.get("state", {})
    assert isinstance(written, dict)
    assert written.get("prepare_phase") == PreparePhase.PREPARED.value


# ── R5: mark-phase CLI ───────────────────────────────────────────────────────


@_pins_new_behavior
def test_mark_phase_cli_writes_prepare_phase_when_value_matches_prepare_enum() -> None:
    """mark-phase with a PreparePhase value writes state['prepare_phase']."""
    from teleclaude.cli.telec.handlers import todo as todo_handler  # type: ignore[import-not-found]

    captured: dict[str, StateValue] = {}

    def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
        captured["state"] = state

    with (
        patch("teleclaude.cli.telec.handlers.todo.write_phase_state", _fake_write),
        patch("teleclaude.cli.telec.handlers.todo.read_phase_state", return_value={}),
    ):
        exit_code = todo_handler.handle_mark_phase(  # type: ignore[attr-defined]
            slug="slug", phase=PreparePhase.PREPARED.value, cwd="/tmp/cwd"
        )

    assert exit_code == 0
    written = captured.get("state", {})
    assert isinstance(written, dict)
    assert written.get("prepare_phase") == PreparePhase.PREPARED.value


@_pins_new_behavior
def test_mark_phase_cli_writes_work_phase_when_value_matches_work_enum() -> None:
    """mark-phase with a WorkPhase value writes state['work_phase']."""
    from teleclaude.cli.telec.handlers import todo as todo_handler  # type: ignore[import-not-found]

    captured: dict[str, StateValue] = {}

    def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
        captured["state"] = state

    with (
        patch("teleclaude.cli.telec.handlers.todo.write_phase_state", _fake_write),
        patch("teleclaude.cli.telec.handlers.todo.read_phase_state", return_value={}),
    ):
        exit_code = todo_handler.handle_mark_phase(  # type: ignore[attr-defined]
            slug="slug", phase=WorkPhase.BUILD_STARTED.value, cwd="/tmp/cwd"
        )

    assert exit_code == 0
    written = captured.get("state", {})
    assert isinstance(written, dict)
    assert written.get("work_phase") == WorkPhase.BUILD_STARTED.value


@_pins_new_behavior
def test_mark_phase_cli_rejects_invalid_phase_value_with_listing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unknown phase value exits non-zero and lists valid values for both enums."""
    from teleclaude.cli.telec.handlers import todo as todo_handler  # type: ignore[import-not-found]

    exit_code = todo_handler.handle_mark_phase(  # type: ignore[attr-defined]
        slug="slug", phase="not_a_real_phase", cwd="/tmp/cwd"
    )

    assert exit_code != 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert PreparePhase.PREPARED.value in combined
    assert WorkPhase.BUILD_STARTED.value in combined
