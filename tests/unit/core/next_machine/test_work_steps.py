"""Unit tests for work state machine step handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.constants import SlashCommand
from teleclaude.core.next_machine._types import PhaseStatus
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.output_formatting import ToolCallRequest
from teleclaude.core.next_machine.review_runtime import ReviewResolution
from teleclaude.core.next_machine.work_steps import (
    _handle_build_complete_claim,
    _handle_finalize_ready_claim,
    _work_step_build_complete,
    _work_step_build_started,
    _work_step_finalize_ready,
    _work_step_review_changes_requested,
)

pytestmark = [pytest.mark.unit, pytest.mark.timeout(10)]

_WORK_STEPS = "teleclaude.core.next_machine.work_steps"


def _mock_db() -> AsyncMock:
    return AsyncMock()


def _mock_todos_db() -> AsyncMock:
    db = AsyncMock()
    db.is_bug_todo = AsyncMock(return_value=False)
    return db


def _base_state(*, kind: str = "todo", lifecycle_phase: str = "build_started") -> dict:
    return {
        "kind": kind,
        "lifecycle_phase": lifecycle_phase,
    }


# ── _work_step_build_started: waiting/dispatch ──────────────────────────────


@pytest.mark.asyncio
async def test_build_started_waits_for_builder_completion_stamp(snapshot: SnapshotAssertion) -> None:
    """A live builder owns the explicit build_complete stamp."""
    state = _base_state()

    with patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="sess-123")):
        keep_going, instruction = await _work_step_build_started(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_build_started_dispatches_when_no_builder_exists(snapshot: SnapshotAssertion) -> None:
    """When no builder session exists, dispatch a fresh one."""
    state = _base_state()

    with (
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value=None)),
        patch(f"{_WORK_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
    ):
        keep_going, instruction = await _work_step_build_started(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction == snapshot


async def _capture_build_dispatch_request(
    kind: str,
) -> ToolCallRequest:
    state = _base_state(kind=kind)
    dispatch = object()

    with (
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value=None)),
        patch(f"{_WORK_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
        patch(f"{_WORK_STEPS}.format_tool_call", return_value=dispatch) as format_tool_call_mock,
    ):
        keep_going, instruction = await _work_step_build_started(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug=f"{kind}-slug",
            cwd="/project",
            worktree_cwd=f"/project/trees/{kind}-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction is dispatch
    request = format_tool_call_mock.call_args.args[0]
    assert isinstance(request, ToolCallRequest)
    return request


@pytest.mark.asyncio
async def test_build_started_dispatch_note_matches_standard_prepared_todo(snapshot: SnapshotAssertion) -> None:
    request = await _capture_build_dispatch_request("todo")

    assert request["command"] == SlashCommand.NEXT_BUILD
    assert request["note"] == snapshot


@pytest.mark.asyncio
async def test_build_started_dispatch_note_matches_prepped_todo(snapshot: SnapshotAssertion) -> None:
    request = await _capture_build_dispatch_request("prepped")

    assert request["command"] == SlashCommand.NEXT_BUILD
    assert request["note"] == snapshot


@pytest.mark.asyncio
async def test_build_started_dispatch_note_matches_bug_todo(snapshot: SnapshotAssertion) -> None:
    request = await _capture_build_dispatch_request("bug")

    assert request["command"] == SlashCommand.NEXT_BUGS_FIX
    assert request["note"] == snapshot


@pytest.mark.asyncio
async def test_build_started_dispatch_note_matches_plan_only_todo(snapshot: SnapshotAssertion) -> None:
    request = await _capture_build_dispatch_request("refactor")

    assert request["command"] == SlashCommand.NEXT_BUILD
    assert request["note"] == snapshot


async def _capture_review_dispatch_request(
    kind: str,
) -> ToolCallRequest:
    dispatch = object()
    state = {
        "kind": kind,
        "lifecycle_phase": "build_complete",
        "build_review": {"round": 0, "baseline_commit": "aaa111", "dispatch_head": "aaa111"},
    }

    with (
        patch(
            f"{_WORK_STEPS}.resolve_pending_review_state",
            new=AsyncMock(
                return_value=ReviewResolution(
                    state=state,
                    status=PhaseStatus.PENDING.value,
                    instruction=None,
                )
            ),
        ),
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value=None)),
        patch(f"{_WORK_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
        patch(f"{_WORK_STEPS}.format_tool_call", return_value=dispatch) as format_tool_call_mock,
    ):
        keep_going, instruction = await _work_step_build_complete(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug=f"{kind}-slug",
            cwd="/project",
            worktree_cwd=f"/project/trees/{kind}-slug",
            state=state,
            head_before_merge="aaa111",
            head_after_merge="aaa111",
        )

    assert keep_going is False
    assert instruction is dispatch
    request = format_tool_call_mock.call_args.args[0]
    assert isinstance(request, ToolCallRequest)
    return request


@pytest.mark.asyncio
async def test_build_complete_review_dispatch_note_matches_standard_prepared_todo(
    snapshot: SnapshotAssertion,
) -> None:
    request = await _capture_review_dispatch_request("todo")

    assert request["command"] == SlashCommand.NEXT_REVIEW_BUILD
    assert request["note"] == snapshot


@pytest.mark.asyncio
async def test_build_complete_review_dispatch_note_matches_bug_todo(snapshot: SnapshotAssertion) -> None:
    request = await _capture_review_dispatch_request("bug")

    assert request["command"] == SlashCommand.NEXT_REVIEW_BUILD
    assert request["note"] == snapshot


@pytest.mark.asyncio
async def test_build_started_bug_skips_readiness_gate_and_dispatches() -> None:
    """Bug lanes dispatch build work without going through is_ready_for_work."""
    state = {
        "kind": "bug",
        "lifecycle_phase": "build_started",
    }
    dispatched = object()
    blocked = object()

    with (
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value=None)),
        patch(f"{_WORK_STEPS}.compose_agent_guidance", new=AsyncMock(return_value="guidance")),
        patch(f"{_WORK_STEPS}.format_tool_call", return_value=dispatched),
        patch(f"{_WORK_STEPS}.format_error", return_value=blocked),
    ):
        keep_going, instruction = await _work_step_build_started(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="bug-slug",
            cwd="/project",
            worktree_cwd="/project/trees/bug-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction is dispatched


@pytest.mark.asyncio
async def test_build_started_rejects_pre_prepared_lifecycle_phase(snapshot: SnapshotAssertion) -> None:
    """Pre-prepared lifecycle_phase produces NOT_PREPARED at the work-step entry.

    Integration coverage for the readiness gate wiring in _work_step_build_started:
    the unit-tested is_ready_for_work helper is correct on its own, but this
    test pins the call-site so a refactor that bypasses the helper would fail.
    """
    state = {
        "kind": "todo",
        "lifecycle_phase": "plan_review",
    }
    blocked = object()

    with patch(f"{_WORK_STEPS}.format_error", return_value=blocked) as format_error_mock:
        keep_going, instruction = await _work_step_build_started(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction is blocked
    format_error_mock.assert_called_once()
    args = format_error_mock.call_args
    assert args.args == snapshot


# ── _work_step_review_changes_requested: waiting ─────────────────────────────


@pytest.mark.asyncio
async def test_review_changes_requested_waits_for_fix_completion_stamp_after_commits(
    snapshot: SnapshotAssertion,
) -> None:
    """Committed fixes are evidence only until the builder stamps completion."""
    state: dict = {
        "lifecycle_phase": "review_changes_requested",
        "build_review": {
            "verdict": "changes_requested",
            "baseline_commit": "aaa111",
            "dispatch_head": "aaa111",
            "round": 0,
        },
    }

    with (
        patch(f"{_WORK_STEPS}.get_head_commit", return_value="bbb222"),
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="builder-1")),
    ):
        keep_going, instruction = await _work_step_review_changes_requested(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_review_changes_requested_relay_message_addresses_every_finding(
    snapshot: SnapshotAssertion,
) -> None:
    """Relay to a live builder names every finding tier and forbids the Suggestion bucket.

    Pins the Severity tier overhaul: the message must instruct the builder to address
    every finding (no "non-Suggestion" qualifier), reference the three-tier schema,
    and direct the builder to the build-complete stamp on completion.
    """
    state: dict = {
        "lifecycle_phase": "review_changes_requested",
        "build_review": {
            "verdict": "changes_requested",
            "baseline_commit": "aaa111",
            "dispatch_head": "aaa111",
            "round": 0,
        },
    }

    with (
        patch(f"{_WORK_STEPS}.get_head_commit", return_value="aaa111"),
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="builder-1")),
    ):
        keep_going, instruction = await _work_step_review_changes_requested(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_review_changes_requested_tells_reviewer_to_open_direct_builder_link(
    snapshot: SnapshotAssertion,
) -> None:
    """The reviewer, not the orchestrator, initiates the direct fix conversation."""
    state: dict = {
        "lifecycle_phase": "review_changes_requested",
        "build_review": {
            "verdict": "changes_requested",
            "baseline_commit": "aaa111",
            "dispatch_head": "aaa111",
            "round": 0,
        },
    }

    with (
        patch(f"{_WORK_STEPS}.get_head_commit", return_value="aaa111"),
        patch(
            f"{_WORK_STEPS}.find_live_session_for_slug",
            new=AsyncMock(side_effect=["builder-1", "reviewer-1"]),
        ),
    ):
        keep_going, instruction = await _work_step_review_changes_requested(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_build_complete_round_limit_message_has_no_suggestion_floor(snapshot: SnapshotAssertion) -> None:
    """Round-limit message must not promise approval for Suggestion-only findings.

    Pins the orchestration round-limit overhaul: the message must state that round
    limit is not an escape hatch, reference the three-tier schema, and direct the
    orchestrator to escalate to the human if the loop is stuck — never to approve
    on a Suggestion floor.
    """
    state: dict = {
        "lifecycle_phase": "build_complete",
        "build_review": {"round": 99},  # exceeds DEFAULT_MAX_REVIEW_ROUNDS
    }

    keep_going, instruction = await _work_step_build_complete(
        db=_mock_db(),
        todos_db=_mock_todos_db(),
        slug="test-slug",
        cwd="/project",
        worktree_cwd="/project/trees/test-slug",
        state=state,
        head_before_merge="aaa111",
        head_after_merge="aaa111",
    )

    assert keep_going is False
    assert instruction == snapshot


# ── _handle_build_complete_claim ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_complete_claim_no_claim_returns_none() -> None:
    """When the claim is empty, the helper falls through (returns None)."""
    state = {"build_gate_claim_at": "", "lifecycle_phase": "build_started"}

    result = await _handle_build_complete_claim(
        db=_mock_db(),
        todos_db=_mock_todos_db(),
        slug="test-slug",
        worktree_cwd="/project/trees/test-slug",
        state=state,
    )

    assert result is None


@pytest.mark.asyncio
async def test_build_complete_claim_pass_advances_lifecycle() -> None:
    """A claim with passing gates fires the build_complete signal and clears the claim."""
    state = {
        "build_gate_claim_at": "2026-01-01T00:00:00+00:00",
        "lifecycle_phase": "build_started",
        "build_start_base_sha": "deadbeef",
    }
    todos_db = _mock_todos_db()
    todos_db.write_state = AsyncMock()

    with (
        patch(f"{_WORK_STEPS}.run_build_gates", return_value=(True, "passed")),
        patch(f"{_WORK_STEPS}.get_head_commit", return_value="cafebabe"),
        patch(f"{_WORK_STEPS}._commit_writer", new=AsyncMock()),
    ):
        result = await _handle_build_complete_claim(
            db=_mock_db(),
            todos_db=todos_db,
            slug="test-slug",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert result == (True, "")


@pytest.mark.asyncio
async def test_build_complete_claim_fail_returns_fix_relay_script(snapshot: SnapshotAssertion) -> None:
    """A claim with failing gates clears the claim and emits a fix-relay script to the live builder."""
    state = {
        "build_gate_claim_at": "2026-01-01T00:00:00+00:00",
        "lifecycle_phase": "build_started",
    }

    with (
        patch(f"{_WORK_STEPS}.run_build_gates", return_value=(False, "FAILED tests/foo.py")),
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value="builder-123")),
        patch(f"{_WORK_STEPS}._commit_writer", new=AsyncMock()),
    ):
        keep_going, instruction = await _handle_build_complete_claim(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_build_complete_claim_fail_no_builder_surfaces_error(snapshot: SnapshotAssertion) -> None:
    """A failed claim with no live builder surfaces a manual-intervention error."""
    state = {
        "build_gate_claim_at": "2026-01-01T00:00:00+00:00",
        "lifecycle_phase": "build_started",
    }

    with (
        patch(f"{_WORK_STEPS}.run_build_gates", return_value=(False, "gate failed")),
        patch(f"{_WORK_STEPS}.find_live_session_for_slug", new=AsyncMock(return_value=None)),
        patch(f"{_WORK_STEPS}._commit_writer", new=AsyncMock()),
    ):
        keep_going, instruction = await _handle_build_complete_claim(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction == snapshot


# ── _handle_finalize_ready_claim ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_ready_claim_no_claim_returns_none() -> None:
    """When finalize is not 'ready', the helper falls through."""
    state = {
        "finalize": {"status": "pending"},
        "lifecycle_phase": "review_approved",
    }

    result = await _handle_finalize_ready_claim(
        slug="test-slug",
        cwd="/project",
        worktree_cwd="/project/trees/test-slug",
        todos_db=_mock_todos_db(),
        state=state,
    )

    assert result is None


@pytest.mark.asyncio
async def test_finalize_ready_claim_wrong_phase_returns_none() -> None:
    """A finalize-ready claim is only consumed from REVIEW_APPROVED."""
    state = {
        "finalize": {"status": "ready", "sha": "cafebabe", "worker_session_id": "w-1"},
        "lifecycle_phase": "build_started",
    }

    result = await _handle_finalize_ready_claim(
        slug="test-slug",
        cwd="/project",
        worktree_cwd="/project/trees/test-slug",
        todos_db=_mock_todos_db(),
        state=state,
    )

    assert result is None


@pytest.mark.asyncio
async def test_finalize_ready_claim_uncommitted_changes_blocks(snapshot: SnapshotAssertion) -> None:
    state = {
        "finalize": {"status": "ready", "sha": "cafebabe", "worker_session_id": "w-1"},
        "lifecycle_phase": "review_approved",
    }

    with patch(f"{_WORK_STEPS}.has_uncommitted_changes", return_value=True):
        keep_going, instruction = await _handle_finalize_ready_claim(
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            todos_db=_mock_todos_db(),
            state=state,
        )

    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_finalize_ready_claim_remote_mismatch_blocks(snapshot: SnapshotAssertion) -> None:
    state = {
        "finalize": {"status": "ready", "sha": "cafebabe", "worker_session_id": "w-1"},
        "lifecycle_phase": "review_approved",
    }

    with (
        patch(f"{_WORK_STEPS}.has_uncommitted_changes", return_value=False),
        patch(f"{_WORK_STEPS}.get_head_commit", return_value="cafebabe"),
        patch(f"{_WORK_STEPS}.get_ref_commit", return_value="cafebabe"),
        patch(f"{_WORK_STEPS}.get_remote_branch_head", return_value="deadbeef"),
    ):
        keep_going, instruction = await _handle_finalize_ready_claim(
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            todos_db=_mock_todos_db(),
            state=state,
        )

    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_finalize_ready_claim_stale_sha_blocks(snapshot: SnapshotAssertion) -> None:
    """A claim whose stamped SHA differs from current worktree HEAD is rejected
    even when the three live refs agree among themselves — the branch advanced
    after the claim was stamped, and integrating the wrong commit would be a bug."""
    state = {
        "finalize": {"status": "ready", "sha": "oldsha", "worker_session_id": "w-1"},
        "lifecycle_phase": "review_approved",
    }

    with (
        patch(f"{_WORK_STEPS}.has_uncommitted_changes", return_value=False),
        patch(f"{_WORK_STEPS}.get_head_commit", return_value="newsha"),
        patch(f"{_WORK_STEPS}.get_ref_commit", return_value="newsha"),
        patch(f"{_WORK_STEPS}.get_remote_branch_head", return_value="newsha"),
    ):
        keep_going, instruction = await _handle_finalize_ready_claim(
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            todos_db=_mock_todos_db(),
            state=state,
        )

    assert keep_going is False
    assert instruction == snapshot


@pytest.mark.asyncio
async def test_finalize_ready_claim_commits_valid_triple_ref_without_manual_event_emit() -> None:
    """Valid claims keep the triple-ref gate and leave event emission to TodosDb."""
    state = {
        "finalize": {
            "status": "ready",
            "branch": "test-slug",
            "sha": "cafebabe",
            "ready_at": "2026-05-09T12:00:00+00:00",
            "worker_session_id": "w-1",
        },
        "lifecycle_phase": "review_approved",
    }
    commit = AsyncMock()

    with (
        patch(f"{_WORK_STEPS}.has_uncommitted_changes", return_value=False),
        patch(f"{_WORK_STEPS}.get_head_commit", return_value="cafebabe"),
        patch(f"{_WORK_STEPS}.get_ref_commit", return_value="cafebabe"),
        patch(f"{_WORK_STEPS}.get_remote_branch_head", return_value="cafebabe"),
        patch(f"{_WORK_STEPS}._commit_writer", new=commit),
    ):
        result = await _handle_finalize_ready_claim(
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            todos_db=_mock_todos_db(),
            state=state,
        )

    assert result == (True, "")
    commit.assert_awaited_once()
    committed_writer = commit.await_args.args[0]
    assert committed_writer.state.lifecycle_phase == LifecyclePhase.FINALIZE_READY.value


@pytest.mark.asyncio
async def test_finalize_ready_step_returns_worker_cleanup_script(snapshot: SnapshotAssertion) -> None:
    """FINALIZE_READY owns the terminal worker-session cleanup directly."""
    state = {
        "finalize": {"status": "ready", "sha": "cafebabe", "worker_session_id": "w-1"},
        "lifecycle_phase": LifecyclePhase.FINALIZE_READY.value,
    }

    with (
        patch(f"{_WORK_STEPS}.get_session_id", return_value="orchestrator-1"),
        patch(f"{_WORK_STEPS}._list_child_session_ids", new=AsyncMock(return_value=["child-1", "child-2"])),
    ):
        keep_going, instruction = await _work_step_finalize_ready(
            db=_mock_db(),
            todos_db=_mock_todos_db(),
            slug="test-slug",
            cwd="/project",
            worktree_cwd="/project/trees/test-slug",
            state=state,
        )

    assert keep_going is False
    assert instruction == snapshot
