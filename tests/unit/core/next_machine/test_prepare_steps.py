"""Tests for v2 prepare phase dispatch behavior.

Output is a verbatim execution script. We snapshot the rendered output to lock
the wording at the boundary and rely on the snapshot diff to catch regressions.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.constants import SlashCommand
from teleclaude.core.next_machine._types import PreparePhase
from teleclaude.core.next_machine.output_formatting import (
    PENDING_DRIFT_CONTEXT_PREFIX,
    format_pending_classes_for_dispatch,
)
from teleclaude.core.next_machine.prepare_steps import DRIFT_ANALYZER_RECOMMENDED_MODE, _prepare_dispatch
from teleclaude.core.todos_db._upcycle import LATEST_TODO_STATE_SCHEMA_VERSION

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]

_STEPS = "teleclaude.core.next_machine.prepare_steps"
_DISPATCHED = "DISPATCHED"


def _parse_pending_context(context: str) -> dict[str, list[str]]:
    prefix, _separator, body = context.partition(": ")
    assert prefix == PENDING_DRIFT_CONTEXT_PREFIX
    parsed: dict[str, list[str]] = {}
    for part in body.split("; "):
        artifact, _equals, raw_classes = part.partition("=")
        parsed[artifact] = raw_classes.removeprefix("[").removesuffix("]").split(",")
    return parsed


async def _dispatch(phase: PreparePhase, *, live_worker_id: str | None = None) -> tuple[bool, str]:
    db = AsyncMock()
    todos_db = AsyncMock()
    with (
        patch(f"{_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
        patch(f"{_STEPS}.find_live_prepare_worker_for_slug", new=AsyncMock(return_value=live_worker_id)),
    ):
        return await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=phase,
            state={"schema_version": LATEST_TODO_STATE_SCHEMA_VERSION, "lifecycle_phase": phase.value},
        )


@pytest.mark.asyncio
async def test_prd_drafting_loads_intake_procedure(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.PRD_DRAFTING)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_architecture_drafting_loads_architecture_procedure(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.ARCHITECTURE_DRAFTING)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_architecture_review_dispatches_to_reviewer(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.ARCHITECTURE_REVIEW)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_plan_drafting_loads_plan_procedure(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.PLAN_DRAFTING)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_plan_review_dispatches_to_plan_review(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.PLAN_REVIEW)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_architecture_review_reuses_live_reviewer(snapshot: SnapshotAssertion) -> None:
    """A live reviewer for the slug+command emits sessions send, not sessions run."""
    keep_going, instruction = await _dispatch(PreparePhase.ARCHITECTURE_REVIEW, live_worker_id="reviewer-arch-1")
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_plan_review_reuses_live_reviewer(snapshot: SnapshotAssertion) -> None:
    """A live plan reviewer is reused via sessions send instead of spawning fresh."""
    keep_going, instruction = await _dispatch(PreparePhase.PLAN_REVIEW, live_worker_id="reviewer-plan-1")
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_prd_human_approval_emits_stamp_instruction(snapshot: SnapshotAssertion) -> None:
    keep_going, instruction = await _dispatch(PreparePhase.PRD_HUMAN_APPROVAL)
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_blocked_pending_drift_dispatches_drift_analyzer() -> None:
    db = AsyncMock()
    todos_db = AsyncMock()
    state = {
        "schema_version": LATEST_TODO_STATE_SCHEMA_VERSION,
        "lifecycle_phase": "blocked",
        "artifacts": {
            "prd": {
                "digest": "prd",
                "codebase_sha_at_write": "base",
                "referenced_paths": ["src/app.py"],
            }
        },
    }
    drift_result = {"prd": {"code": "pending"}}
    dispatch_worker = AsyncMock(return_value=(False, _DISPATCHED))
    with (
        patch(f"{_STEPS}.derive_lifecycle_drift", new=AsyncMock(return_value=drift_result)),
        patch(f"{_STEPS}._dispatch_worker", new=dispatch_worker),
        patch(f"{_STEPS}.prepare_blockers", return_value=["prd drift is pending; run drift analysis before prepared"]),
    ):
        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=PreparePhase.BLOCKED,
            state=state,
        )
    assert keep_going is False
    assert instruction == _DISPATCHED
    assert dispatch_worker.call_args.kwargs["command"] is SlashCommand.NEXT_DRIFT_ANALYZE
    assert dispatch_worker.call_args.kwargs["additional_context"] == format_pending_classes_for_dispatch(drift_result)
    assert dispatch_worker.call_args.kwargs["recommended_mode"] == DRIFT_ANALYZER_RECOMMENDED_MODE


@pytest.mark.asyncio
async def test_blocked_pending_drift_fresh_spawn_passes_pending_classes_as_context() -> None:
    db = AsyncMock()
    todos_db = AsyncMock()
    state = {
        "schema_version": LATEST_TODO_STATE_SCHEMA_VERSION,
        "lifecycle_phase": "blocked",
        "artifacts": {
            "prd": {
                "digest": "prd",
                "codebase_sha_at_write": "base",
                "referenced_paths": ["src/app.py"],
            }
        },
    }
    drift_result = {
        "prd": {"code": "pending", "age": "fresh"},
        "implementation-plan": {"dependency-graph": "pending", "upstream-snippet": "cosmetic"},
    }
    format_tool_call = Mock(return_value=_DISPATCHED)
    with (
        patch(f"{_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
        patch(f"{_STEPS}.find_live_prepare_worker_for_slug", new=AsyncMock(return_value=None)),
        patch(f"{_STEPS}.derive_lifecycle_drift", new=AsyncMock(return_value=drift_result)),
        patch(f"{_STEPS}.format_tool_call", new=format_tool_call),
        patch(f"{_STEPS}.prepare_blockers", return_value=["prd drift is pending; run drift analysis before prepared"]),
    ):
        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=PreparePhase.BLOCKED,
            state=state,
        )

    assert keep_going is False
    assert instruction == _DISPATCHED
    request = format_tool_call.call_args.args[0]
    assert request["additional_context"] == format_pending_classes_for_dispatch(drift_result)


@pytest.mark.asyncio
async def test_blocked_pending_drift_reuses_live_analyzer() -> None:
    """A live drift analyzer for the slug is reused instead of spawned fresh."""
    db = AsyncMock()
    todos_db = AsyncMock()
    state = {
        "schema_version": LATEST_TODO_STATE_SCHEMA_VERSION,
        "lifecycle_phase": "blocked",
        "artifacts": {
            "prd": {
                "digest": "prd",
                "codebase_sha_at_write": "base",
                "referenced_paths": ["src/app.py"],
            }
        },
    }
    drift_result = {"prd": {"code": "pending", "age": "fresh"}}
    with (
        patch(f"{_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
        patch(f"{_STEPS}.find_live_prepare_worker_for_slug", new=AsyncMock(return_value="analyzer-1")),
        patch(f"{_STEPS}.derive_lifecycle_drift", new=AsyncMock(return_value=drift_result)),
        patch(f"{_STEPS}.prepare_blockers", return_value=["prd drift is pending; run drift analysis before prepared"]),
    ):
        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=PreparePhase.BLOCKED,
            state=state,
        )
    assert keep_going is False
    expected_context = format_pending_classes_for_dispatch(drift_result)
    _prefix, _separator, payload = instruction.partition('"')
    message, _separator, _suffix = payload.partition('"')
    assert message[: len(expected_context)] == expected_context


@pytest.mark.asyncio
async def test_blocked_no_drift_emits_blocker_resolution(snapshot: SnapshotAssertion) -> None:
    db = AsyncMock()
    todos_db = AsyncMock()
    state = {"schema_version": LATEST_TODO_STATE_SCHEMA_VERSION, "lifecycle_phase": "blocked", "artifacts": {}}
    with (
        patch(f"{_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
        patch(f"{_STEPS}.derive_lifecycle_drift", new=AsyncMock(return_value={})),
        patch(
            f"{_STEPS}.prepare_blockers",
            return_value=["architecture artifact is present but required upstream prd is missing"],
        ),
    ):
        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=PreparePhase.BLOCKED,
            state=state,
        )
    assert keep_going is False
    assert instruction == snapshot


# Named-constant identity comparison for the prepared-terminal delegate test
# (string-assertion paradigm: identity vs named constant, not literal).
_PREPARED_TERMINAL_INSTRUCTION = "PREPARED: my-slug"


@pytest.mark.asyncio
async def test_prepared_delegates_to_terminal_formatter() -> None:
    with patch(
        f"{_STEPS}._prepare_step_prepared",
        new=AsyncMock(return_value=(False, _PREPARED_TERMINAL_INSTRUCTION)),
    ):
        keep_going, instruction = await _dispatch(PreparePhase.PREPARED)
    assert keep_going is False
    assert instruction == _PREPARED_TERMINAL_INSTRUCTION


@pytest.mark.asyncio
async def test_prepared_pending_drift_dispatches_analyzer_before_terminal_formatter() -> None:
    db = AsyncMock()
    todos_db = AsyncMock()
    state = {
        "schema_version": LATEST_TODO_STATE_SCHEMA_VERSION,
        "lifecycle_phase": PreparePhase.PREPARED.value,
        "artifacts": {"prd": {"digest": "prd"}},
    }
    dispatch_worker = AsyncMock(return_value=(False, _DISPATCHED))
    drift_result = {"prd": {"code": "pending", "age": "fresh"}}
    with (
        patch(f"{_STEPS}.derive_lifecycle_drift", new=AsyncMock(return_value=drift_result)),
        patch(f"{_STEPS}._dispatch_worker", new=dispatch_worker),
        patch(f"{_STEPS}._prepare_step_prepared", new=AsyncMock(return_value=(False, _PREPARED_TERMINAL_INSTRUCTION))),
    ):
        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=PreparePhase.PREPARED,
            state=state,
        )

    assert keep_going is False
    assert instruction == _DISPATCHED
    assert dispatch_worker.call_args.kwargs["command"] is SlashCommand.NEXT_DRIFT_ANALYZE
    assert dispatch_worker.call_args.kwargs["additional_context"] == format_pending_classes_for_dispatch(drift_result)
    assert dispatch_worker.call_args.kwargs["recommended_mode"] == DRIFT_ANALYZER_RECOMMENDED_MODE


def test_pending_classes_formatter_renders_pending_pairs_only() -> None:
    drift_result = {
        "implementation-plan": {"age": "pending", "code": "fresh"},
        "architecture": {
            "upstream-snippet": "pending",
            "code": "pending",
            "dependency-graph": "substantive",
        },
        "prd": {"owned-snippet": "cosmetic"},
    }
    context = format_pending_classes_for_dispatch(drift_result)
    assert _parse_pending_context(context) == {
        "architecture": ["code", "upstream-snippet"],
        "implementation-plan": ["age"],
    }


def test_pending_classes_formatter_returns_empty_without_pending_pairs() -> None:
    drift_result = {
        "architecture": {"code": "fresh", "dependency-graph": "substantive"},
        "prd": {"owned-snippet": "cosmetic"},
    }
    assert len(format_pending_classes_for_dispatch(drift_result)) == 0


@pytest.mark.asyncio
async def test_prepared_fresh_drift_delegates_to_terminal_formatter() -> None:
    db = AsyncMock()
    todos_db = AsyncMock()
    state = {
        "schema_version": LATEST_TODO_STATE_SCHEMA_VERSION,
        "lifecycle_phase": PreparePhase.PREPARED.value,
        "artifacts": {"prd": {"digest": "prd"}},
    }
    prepared = AsyncMock(return_value=(False, _PREPARED_TERMINAL_INSTRUCTION))
    with (
        patch(f"{_STEPS}.derive_lifecycle_drift", new=AsyncMock(return_value={"prd": {"code": "fresh"}})),
        patch(f"{_STEPS}._prepare_step_prepared", new=prepared),
    ):
        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=PreparePhase.PREPARED,
            state=state,
        )

    assert keep_going is False
    assert instruction == _PREPARED_TERMINAL_INSTRUCTION
    prepared.assert_awaited_once()


@pytest.mark.asyncio
async def test_reuse_does_not_collide_with_prefix_sharing_slug(snapshot: SnapshotAssertion) -> None:
    """End-to-end: a longer slug that starts with our slug as a prefix must NOT be reused.

    Exercises the real find_live_prepare_worker_for_slug lookup (no helper mock)
    so the slug-boundary guard is verified through the rendered dispatch script
    snapshot (which embeds the selected session_id verbatim).
    """
    # Two live prepare reviewers on repo root (subdir=None), same command prefix,
    # different slugs. The collider's slug starts with our target slug.
    fake_sessions = [
        SimpleNamespace(
            session_id="reviewer-collider",
            subdir=None,
            title="/next-review-architecture my-slug-extra",
        ),
        SimpleNamespace(
            session_id="reviewer-exact",
            subdir=None,
            title="/next-review-architecture my-slug",
        ),
    ]
    db = AsyncMock()
    db.list_sessions = AsyncMock(return_value=fake_sessions)
    todos_db = AsyncMock()
    with patch(f"{_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")):
        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=PreparePhase.ARCHITECTURE_REVIEW,
            state={"lifecycle_phase": PreparePhase.ARCHITECTURE_REVIEW.value},
        )
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_reuse_matches_title_with_trailing_context(snapshot: SnapshotAssertion) -> None:
    """A reviewer title with trailing whitespace+context after the slug still matches."""
    fake_sessions = [
        SimpleNamespace(
            session_id="reviewer-with-context",
            subdir=None,
            title="/next-review-architecture my-slug  ADDITIONAL CONTEXT: foo",
        ),
    ]
    db = AsyncMock()
    db.list_sessions = AsyncMock(return_value=fake_sessions)
    todos_db = AsyncMock()
    with patch(f"{_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")):
        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=PreparePhase.ARCHITECTURE_REVIEW,
            state={"lifecycle_phase": PreparePhase.ARCHITECTURE_REVIEW.value},
        )
    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_reuse_skips_session_with_non_root_subdir(snapshot: SnapshotAssertion) -> None:
    """A worktree-scoped session must NOT be reused for prepare (which runs on repo root).

    The snapshot captures the spawn-path dispatch script — its presence proves
    the worktree-scoped session was correctly skipped and fresh spawn ran.
    """
    fake_sessions = [
        SimpleNamespace(
            session_id="worktree-session",
            subdir="trees/my-slug",
            title="/next-review-architecture my-slug",
        ),
    ]
    db = AsyncMock()
    db.list_sessions = AsyncMock(return_value=fake_sessions)
    todos_db = AsyncMock()
    with patch(f"{_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")):
        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug="my-slug",
            cwd="/repo",
            phase=PreparePhase.ARCHITECTURE_REVIEW,
            state={"lifecycle_phase": PreparePhase.ARCHITECTURE_REVIEW.value},
        )
    assert keep_going is False
    assert instruction == snapshot
