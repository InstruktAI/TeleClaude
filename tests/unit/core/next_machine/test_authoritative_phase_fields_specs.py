"""Spec contract for the authoritative-phase-fields todo.

# guard: no-companion

Assertions pin the behavioral contract for authoritative sub-phase fields on
TodoState; they must not be weakened.

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


# ── R1: state model ──────────────────────────────────────────────────────────


def test_todo_state_has_authoritative_subphase_fields_with_empty_default() -> None:
    """TodoState must carry prepare_phase and work_phase as strings defaulting to ''."""
    from teleclaude.types.todos import TodoState

    state = TodoState.defaults()

    assert hasattr(state, "prepare_phase")
    assert hasattr(state, "work_phase")
    assert state.prepare_phase == ""
    assert state.work_phase == ""
    assert isinstance(state.prepare_phase, str)
    assert isinstance(state.work_phase, str)


def test_item_phase_remains_independent_of_subphase_fields() -> None:
    """Item-level phase keeps holding ItemPhase values; sub-phase fields are independent."""
    from teleclaude.types.todos import TodoState

    state = TodoState.defaults()
    state.phase = ItemPhase.IN_PROGRESS.value
    state.prepare_phase = PreparePhase.PREPARED.value
    state.work_phase = WorkPhase.BUILD_STARTED.value

    assert state.phase == ItemPhase.IN_PROGRESS.value
    assert state.prepare_phase == PreparePhase.PREPARED.value
    assert state.work_phase == WorkPhase.BUILD_STARTED.value


# ── R2: derivation precedence ────────────────────────────────────────────────


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


@pytest.mark.asyncio
async def test_prepare_step_transitions_write_authoritative_phase() -> None:
    """The real dispatched prepare step writes prepare_phase on its transition.

    Drives ``_prepare_step_input_assessment`` on the happy path (requirements
    artifact present) and asserts that the state persisted via the typed writer
    carries ``prepare_phase == REQUIREMENTS_REVIEW`` — the destination of the
    INPUT_ASSESSMENT → REQUIREMENTS_REVIEW transition.
    """
    from teleclaude.core.next_machine import prepare_steps

    captured: dict[str, StateValue] = {}

    async def _fake_commit(writer, _todos_db, _slug, state: dict[str, StateValue]) -> None:
        payload = writer.to_dict()
        state.clear()
        state.update(payload)
        captured["state"] = payload

    todos_db = AsyncMock()
    todos_db.artifact_exists = AsyncMock(return_value=True)
    todos_db.artifact_digest = AsyncMock(return_value="digest-abc")

    with (
        patch.object(prepare_steps, "_commit_writer", _fake_commit),
        patch.object(prepare_steps, "ensure_worktree_with_policy_async", AsyncMock()),
        patch.object(prepare_steps, "_emit_prepare_event", lambda *_a, **_kw: None),
    ):
        looped, _message = await prepare_steps._prepare_step_input_assessment(
            MagicMock(),
            todos_db,
            "slug",
            "/tmp/cwd",
            {},
        )

    assert looped is True
    written = captured.get("state", {})
    assert isinstance(written, dict)
    assert written.get("prepare_phase") == PreparePhase.REQUIREMENTS_REVIEW.value


@pytest.mark.asyncio
async def test_work_step_transitions_write_authoritative_phase() -> None:
    """The real dispatched work step writes work_phase on its entry.

    Drives ``_work_step_build_started`` with an unset ``work_phase`` and asserts
    the handler records the BUILD_STARTED entry via ``write_phase_state`` before
    doing any dispatch work.
    """
    from teleclaude.core.next_machine import work_steps

    captured: dict[str, StateValue] = {}

    async def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
        captured["state"] = dict(state)

    state: dict[str, StateValue] = {"kind": "bug"}

    with (
        patch.object(work_steps, "write_phase_state", _fake_write),
        patch.object(work_steps, "find_live_session_for_slug", AsyncMock(return_value=None)),
        patch.object(work_steps, "compose_agent_guidance", AsyncMock(return_value="g")),
    ):
        await work_steps._work_step_build_started(
            db=MagicMock(),
            todos_db=AsyncMock(),
            slug="slug",
            cwd="/tmp/cwd",
            worktree_cwd="/tmp/worktree",
            state=state,
        )

    written = captured.get("state", {})
    assert isinstance(written, dict)
    assert written.get("work_phase") == WorkPhase.BUILD_STARTED.value


def test_apply_prepared_state_writes_prepare_phase_prepared() -> None:
    """apply_prepared_state must stamp prepare_phase='prepared' on the successful path.

    Validation passes only when the required artifacts and git HEAD are present;
    any failure there must raise before a write, so this test drives the happy
    path by stubbing the artifact/git checks and captures the final state that
    StateWriter.commit_sync persists via todos_db.write_state_sync.
    """
    from teleclaude.core.next_machine.state_io import apply_prepared_state

    captured: dict[str, StateValue] = {}

    def _fake_write_state_sync(_slug: str, state: dict[str, StateValue]) -> None:
        captured["state"] = state

    db_stub = MagicMock()
    db_stub.write_state_sync = _fake_write_state_sync
    conn_stub = MagicMock()
    conn_stub.execute.return_value.fetchone.return_value = None
    db_stub._sync_conn.return_value = conn_stub  # pyright: ignore[reportPrivateUsage]

    with (
        patch("teleclaude.core.next_machine.state_io._get_todos_db_sync", return_value=db_stub),
        patch("teleclaude.core.next_machine.state_io.read_phase_state", return_value={"kind": "bug"}),
        patch("teleclaude.core.next_machine.state_io._has_artifact_content", return_value=True),
        patch(
            "teleclaude.core.next_machine.git_ops.run_git_command",
            return_value=(0, "abc1234\n", ""),
        ),
    ):
        apply_prepared_state("/tmp/cwd", "slug")

    written = captured.get("state", {})
    assert isinstance(written, dict)
    assert written.get("prepare_phase") == PreparePhase.PREPARED.value


def test_apply_prepared_state_raises_and_does_not_persist_when_artifacts_missing() -> None:
    """Missing required artifacts must raise and leave state unwritten.

    Pins the C1 fix: validation runs before any persistence. If the
    implementation-plan artifact is missing, the function must raise
    ``ValueError`` and no write must reach write_phase_state or
    write_state_sync — the todo stays in its prior phase.
    """
    from teleclaude.core.next_machine.state_io import apply_prepared_state

    write_phase_state_calls: list[tuple[str, str, dict[str, StateValue]]] = []
    write_state_sync_calls: list[tuple[str, dict[str, StateValue]]] = []

    def _recording_write_phase_state(cwd: str, slug: str, state: dict[str, StateValue]) -> None:
        write_phase_state_calls.append((cwd, slug, dict(state)))

    def _recording_write_state_sync(slug: str, state: dict[str, StateValue]) -> None:
        write_state_sync_calls.append((slug, dict(state)))

    db_stub = MagicMock()
    db_stub.write_state_sync = _recording_write_state_sync

    # kind='todo' requires BOTH requirements and implementation-plan. Stub
    # requirements as present but implementation-plan as absent so validation
    # fails on the second check — the exact partial-precondition shape that
    # round 3 allowed to silently persist a prepare_phase claim.
    def _has_artifact(_cwd: str, _slug: str, name: str) -> bool:
        return name == "requirements"

    with (
        patch("teleclaude.core.next_machine.state_io.write_phase_state", _recording_write_phase_state),
        patch("teleclaude.core.next_machine.state_io._get_todos_db_sync", return_value=db_stub),
        patch("teleclaude.core.next_machine.state_io.read_phase_state", return_value={"kind": "todo"}),
        patch("teleclaude.core.next_machine.state_io._has_artifact_content", _has_artifact),
        pytest.raises(ValueError, match="implementation-plan"),
    ):
        apply_prepared_state("/tmp/cwd", "slug")

    assert write_phase_state_calls == []
    assert write_state_sync_calls == []


def test_apply_prepared_state_raises_and_does_not_persist_when_git_head_unreachable() -> None:
    """Unreachable git HEAD must raise and leave state unwritten.

    Pins the grounding branch of the C1 fix: artifacts are present but
    ``git rev-parse HEAD`` fails (rc=128) so the grounding baseline cannot
    be established. The function must raise and no write must reach
    write_phase_state or write_state_sync.
    """
    from teleclaude.core.next_machine.state_io import apply_prepared_state

    write_phase_state_calls: list[tuple[str, str, dict[str, StateValue]]] = []
    write_state_sync_calls: list[tuple[str, dict[str, StateValue]]] = []

    def _recording_write_phase_state(cwd: str, slug: str, state: dict[str, StateValue]) -> None:
        write_phase_state_calls.append((cwd, slug, dict(state)))

    def _recording_write_state_sync(slug: str, state: dict[str, StateValue]) -> None:
        write_state_sync_calls.append((slug, dict(state)))

    db_stub = MagicMock()
    db_stub.write_state_sync = _recording_write_state_sync

    with (
        patch("teleclaude.core.next_machine.state_io.write_phase_state", _recording_write_phase_state),
        patch("teleclaude.core.next_machine.state_io._get_todos_db_sync", return_value=db_stub),
        patch("teleclaude.core.next_machine.state_io.read_phase_state", return_value={"kind": "bug"}),
        patch("teleclaude.core.next_machine.state_io._has_artifact_content", return_value=True),
        patch(
            "teleclaude.core.next_machine.git_ops.run_git_command",
            return_value=(128, "", "fatal: not a git repository"),
        ),
        pytest.raises(ValueError, match="git rev-parse HEAD failed"),
    ):
        apply_prepared_state("/tmp/cwd", "slug")

    assert write_phase_state_calls == []
    assert write_state_sync_calls == []


# ── R5: mark-phase CLI ───────────────────────────────────────────────────────


def test_mark_phase_cli_writes_prepare_phase_when_value_matches_prepare_enum() -> None:
    """mark-phase with a PreparePhase value writes state['prepare_phase']."""
    from teleclaude.cli.telec.handlers import todo as todo_handler

    captured: dict[str, StateValue] = {}

    def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
        captured["state"] = state

    with (
        patch("teleclaude.cli.telec.handlers.todo.write_phase_state", _fake_write),
        patch("teleclaude.cli.telec.handlers.todo.read_phase_state", return_value={}),
    ):
        exit_code = todo_handler.handle_mark_phase(slug="slug", phase=PreparePhase.PREPARED.value, cwd="/tmp/cwd")

    assert exit_code == 0
    written = captured.get("state", {})
    assert isinstance(written, dict)
    assert written.get("prepare_phase") == PreparePhase.PREPARED.value


def test_mark_phase_cli_writes_work_phase_when_value_matches_work_enum() -> None:
    """mark-phase with a WorkPhase value writes state['work_phase']."""
    from teleclaude.cli.telec.handlers import todo as todo_handler

    captured: dict[str, StateValue] = {}

    def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
        captured["state"] = state

    with (
        patch("teleclaude.cli.telec.handlers.todo.write_phase_state", _fake_write),
        patch("teleclaude.cli.telec.handlers.todo.read_phase_state", return_value={}),
    ):
        exit_code = todo_handler.handle_mark_phase(slug="slug", phase=WorkPhase.BUILD_STARTED.value, cwd="/tmp/cwd")

    assert exit_code == 0
    written = captured.get("state", {})
    assert isinstance(written, dict)
    assert written.get("work_phase") == WorkPhase.BUILD_STARTED.value


def test_mark_phase_cli_rejects_invalid_phase_value_with_listing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unknown phase value exits non-zero and lists valid values for both enums."""
    from teleclaude.cli.telec.handlers import todo as todo_handler

    exit_code = todo_handler.handle_mark_phase(slug="slug", phase="not_a_real_phase", cwd="/tmp/cwd")

    assert exit_code != 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert PreparePhase.PREPARED.value in combined
    assert WorkPhase.BUILD_STARTED.value in combined
