"""Work state machine — phase step handlers and dispatcher.

Mirrors the prepare lifecycle loop pattern. Each handler is a pure
(state + side-effect) transition that returns ``(keep_going, instruction)``:

- ``keep_going=True``: the state mutated, the loop re-derives the work phase
  and re-dispatches without a worker round-trip.
- ``keep_going=False``: return ``instruction`` verbatim as the orchestrator
  script. The worker will idle, then the orchestrator re-enters the loop.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.integration_bridge import emit_review_approved
from teleclaude.core.next_machine._types import (
    DEFAULT_MAX_REVIEW_ROUNDS,
    REVIEW_DIFF_NOTE,
    StateValue,
    WorkPhase,
)
from teleclaude.core.next_machine.build_gates import format_build_gate_failure, run_build_gates
from teleclaude.core.next_machine.git_ops import (
    compose_agent_guidance,
    get_head_commit,
    has_build_commits_beyond_main,
    has_uncommitted_changes,
)
from teleclaude.core.next_machine.lifecycle import apply_authoritative_signal
from teleclaude.core.next_machine.output_formatting import (
    ToolCallRequest,
    format_error,
    format_finalize_handoff_complete,
    format_tool_call,
    format_uncommitted_changes,
)
from teleclaude.core.next_machine.prepare_steps import _commit_writer, _derive_project_root
from teleclaude.core.next_machine.runtime.sessions import find_live_session_for_slug
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.session_identity import get_session_id

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb
from teleclaude.core.next_machine.review_runtime import ReviewDispatchContext, resolve_pending_review_state

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Post-block helpers
# ---------------------------------------------------------------------------


def _builder_idle_post_block(slug: str) -> str:
    """Post-block after dispatching a builder — re-enter the work machine when idle."""
    return (
        f"WHEN WORKER IDLES:\n"
        f"Call telec todo work {slug}. The state machine emits the next action "
        f"(advance to review, relay build-gate failures, or terminal cleanup)."
    )


def _reviewer_idle_post_block(slug: str) -> str:
    """Post-block after dispatching a reviewer — re-enter the work machine when idle."""
    return (
        f"WHEN REVIEWER IDLES:\n"
        f"Call telec todo work {slug}. The state machine will read the verdict and "
        f"emit the next action (advance to finalize, relay findings to the builder, "
        f"or terminal cleanup)."
    )


async def _list_child_session_ids(db: Db, session_id: str) -> list[str]:
    """List child sessions spawned by the current orchestrator session."""
    if not session_id:
        return []
    try:
        child_sessions = await db.list_sessions(initiator_session_id=session_id)
        return [session.session_id for session in child_sessions]
    except Exception:
        logger.warning("Failed to query child sessions for cleanup", session_id=session_id)
        return []


# ---------------------------------------------------------------------------
# Phase handlers
# ---------------------------------------------------------------------------


async def _work_step_build_started(
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    worktree_cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """BUILD_STARTED: look up a live builder, otherwise dispatch a fresh one.

    DOR precondition: regular todos must have ``dor.status == "pass"``.
    Bugs skip DOR.
    """
    _ = todos_db

    kind_raw = state.get("kind")
    kind = kind_raw if isinstance(kind_raw, str) else "todo"

    if kind != "bug":
        dor_raw = state.get("dor")
        dor = dor_raw if isinstance(dor_raw, dict) else {}
        status = dor.get("status", "")
        if status != "pass":
            return False, format_error(
                "NOT_PREPARED",
                (f"{slug} has DOR status {status!r}, not 'pass'. Run telec todo prepare {slug} before entering work."),
                next_call=f"telec todo prepare {slug}",
            )

    command = SlashCommand.NEXT_BUGS_FIX if kind == "bug" else SlashCommand.NEXT_BUILD
    builder_id = await find_live_session_for_slug(db, slug, f"/{command.value}")
    if builder_id is not None:
        has_commits = await asyncio.to_thread(has_build_commits_beyond_main, worktree_cwd)
        if not has_commits:
            return False, (
                f"BUILDER ACTIVE: {slug}\n\n"
                f"Builder session {builder_id} has no commits beyond main yet. "
                f"Wait for it to commit the work, then call "
                f"telec todo work {slug}."
            )
        gates_passed, gate_output = await asyncio.to_thread(run_build_gates, worktree_cwd, slug)
        if not gates_passed:
            return False, format_build_gate_failure(slug, gate_output, f"telec todo work {slug}")
        writer = StateWriter(state)
        apply_authoritative_signal(writer.state, "build_complete", worktree_cwd=worktree_cwd)
        await _commit_writer(writer, todos_db, slug, state)
        return True, ""

    try:
        guidance = await compose_agent_guidance(db)
    except RuntimeError as exc:
        return False, format_error("NO_AGENTS", str(exc))

    return False, format_tool_call(
        ToolCallRequest(
            command=command,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=(
                f"Start implementation now. When the build is committed and ready for review, "
                f"call `telec todo work {slug}` so the machine can verify gates and continue."
            ),
            next_call=f"telec todo work {slug}",
            post_block=_builder_idle_post_block(slug),
        )
    )


async def _work_step_build_complete(
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    worktree_cwd: str,
    state: dict[str, StateValue],
    head_before_merge: str,
    head_after_merge: str,
) -> tuple[bool, str]:
    """BUILD_COMPLETE: dispatch a reviewer, or relay a re-review to the live one.

    Before dispatching, reconciles live-review progress via the review runtime:
    detects ground shifts from merge, tracks dispatch HEAD, and reuses active
    reviewer sessions across rounds.
    """
    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    round_raw = build_review.get("round", 0)
    round_num = round_raw if isinstance(round_raw, int) else 0

    if round_num > DEFAULT_MAX_REVIEW_ROUNDS:
        return False, format_error(
            "REVIEW_ROUND_LIMIT",
            (
                f"Review rounds exceeded for {slug}: current={round_num}, "
                f"max={DEFAULT_MAX_REVIEW_ROUNDS}. "
                f"Per lifecycle/work/review severity schema and general/procedure/orchestration "
                f"Review Round Limit Handling: approve is permitted only when the sole remaining "
                f"findings are Suggestion-severity. Any unresolved Requirement-Violation, Critical, "
                f"or Important finding keeps the review at changes_requested regardless of round "
                f"count. Read review-findings and verify before any closure action."
            ),
            next_call=f"telec todo artifacts read {slug} review-findings",
        )

    # Reconcile live-review state: detects ground shifts, reuses active reviewers.
    resolution = await resolve_pending_review_state(
        ReviewDispatchContext(db=db, todos_db=todos_db, worktree_cwd=worktree_cwd, slug=slug),
        state,
        head_before_merge=head_before_merge,
        head_after_merge=head_after_merge,
    )
    if resolution.instruction is not None:
        return False, resolution.instruction

    # Re-read after state mutation by resolve_pending_review_state
    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    round_raw = build_review.get("round", 0)
    round_num = round_raw if isinstance(round_raw, int) else 0

    # No live reviewer claimed the review — dispatch a fresh one.
    baseline_raw = build_review.get("baseline_commit", "")
    baseline = baseline_raw if isinstance(baseline_raw, str) else ""
    reviewer_id = await find_live_session_for_slug(db, slug, f"/{SlashCommand.NEXT_REVIEW_BUILD.value}")

    if round_num > 0 and reviewer_id is not None:
        head_sha = await asyncio.to_thread(get_head_commit, worktree_cwd)
        baseline_text = baseline or "unset"
        message = (
            f"Re-review round {round_num + 1}/{DEFAULT_MAX_REVIEW_ROUNDS} for {slug}. "
            f"Incremental scope: review only commits since baseline {baseline_text} "
            f"up to HEAD {head_sha or '<unknown>'}. "
            f"Read `telec todo artifacts read {slug} review-findings` first — your re-review "
            f"must verify the unresolved Requirement-Violation, Critical, and Important "
            f"findings from the prior round are now delivered by the new commits. "
            f"Per the severity schema in lifecycle/work/review, Requirement-Violation "
            f"findings cannot be deferred — the verdict is APPROVE only when all three "
            f"counts are zero. Stamp verdict with "
            f"`telec todo stamp {slug} --verdict approve|changes_requested --phase build_review`."
        )
        escaped = message.replace('"', '\\"')
        return False, (
            f"REVIEW RE-DISPATCH: {slug}\n\n"
            f"Execute in order:\n\n"
            f'telec sessions send {reviewer_id} "{escaped}"\n\n'
            f"Cancel the old heartbeat timer via KillShell(shell_id=<task_id>).\n"
            f"Start a new non-blocking heartbeat timer via "
            f'Bash(command="sleep 300", run_in_background=true) and save the new task_id.\n'
            f"When the reviewer reports idle, call telec todo work {slug}."
        )

    try:
        guidance = await compose_agent_guidance(db)
    except RuntimeError as exc:
        return False, format_error("NO_AGENTS", str(exc))

    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_REVIEW_BUILD,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            next_call=f"telec todo work {slug}",
            note=REVIEW_DIFF_NOTE,
            post_block=_reviewer_idle_post_block(slug),
        )
    )


async def _work_step_review_changes_requested(
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    worktree_cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """REVIEW_CHANGES_REQUESTED: relay findings to the live builder, or loop if fixed.

    The lifecycle remains on ``review_changes_requested`` until the builder
    commits fixes that pass the build gates.
    """
    _ = cwd
    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    baseline_raw = build_review.get("baseline_commit", "")
    baseline = baseline_raw if isinstance(baseline_raw, str) else ""
    head_sha = await asyncio.to_thread(get_head_commit, worktree_cwd)

    if baseline and head_sha and head_sha != baseline:
        gates_passed, gate_output = await asyncio.to_thread(run_build_gates, worktree_cwd, slug)
        if not gates_passed:
            return False, format_build_gate_failure(slug, gate_output, f"telec todo work {slug}")
        writer = StateWriter(state)
        apply_authoritative_signal(writer.state, "build_complete", worktree_cwd=worktree_cwd)
        await _commit_writer(writer, todos_db, slug, state)
        return True, ""

    # Fix not yet committed: relay findings to live builder.
    builder_id = await find_live_session_for_slug(db, slug, f"/{SlashCommand.NEXT_BUILD.value}")
    if builder_id is None:
        builder_id = await find_live_session_for_slug(db, slug, f"/{SlashCommand.NEXT_BUGS_FIX.value}")
    reviewer_id = await find_live_session_for_slug(db, slug, f"/{SlashCommand.NEXT_REVIEW_BUILD.value}")

    if builder_id is None:
        return False, format_error(
            "BUILDER_NOT_ALIVE",
            (
                f"Review requested changes for {slug}, but no live builder session exists "
                f"to relay findings to. The builder should remain alive across review rounds. "
                f"Manual intervention required."
            ),
            next_call=f"telec todo work {slug}",
        )

    message = (
        f"Review requested changes for {slug}. "
        f"Findings artifact: `review-findings`. Target: source code in the worktree. "
        f"Required read: software-development/procedure/lifecycle/fix-review-findings. "
        f"Address every Requirement-Violation, Critical, and Important finding — "
        f"anything less keeps the verdict at REQUEST CHANGES per the severity schema "
        f"in lifecycle/work/review. Requirement-Violation findings in particular "
        f"indicate a stated requirement's success criteria are not satisfied in the "
        f"delivery; fix the narrowing or the weak verification, do not argue severity. "
        f"When every non-Suggestion finding is resolved, commit the fixes and call "
        f"`telec todo work {slug}`. "
        f"Read findings via: telec todo artifacts read {slug} review-findings"
    )
    escaped = message.replace('"', '\\"')
    reviewer_wait = (
        f"Wait for reviewer session {reviewer_id} to report idle."
        if reviewer_id
        else "Wait for the builder to report FIX COMPLETE, then call the next step."
    )
    return False, (
        f"REVIEW CHANGES REQUESTED: {slug}\n\n"
        f"Execute in order:\n\n"
        f'telec sessions send {builder_id} "{escaped}"\n\n'
        f"Cancel the old heartbeat timer via KillShell(shell_id=<task_id>).\n"
        f"Start a new non-blocking heartbeat timer via "
        f'Bash(command="sleep 300", run_in_background=true) and save the new task_id.\n'
        f"{reviewer_wait}\n"
        f"When the signal arrives, call telec todo work {slug}."
    )


async def _work_step_review_approved(
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    worktree_cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """REVIEW_APPROVED: dispatch deferrals, finalize prepare, or relay.

    Preconditions: no uncommitted changes in the worktree.
    Branches:
    - Pending deferrals → dispatch ``/next-defer``.
    - No deferrals → dispatch ``/next-finalize`` (worker stamps finalize_ready).
    """
    _ = worktree_cwd, state
    if has_uncommitted_changes(cwd, slug):
        return False, format_uncommitted_changes(slug)

    if await todos_db.has_pending_deferrals(slug):
        try:
            guidance = await compose_agent_guidance(db)
        except RuntimeError as exc:
            return False, format_error("NO_AGENTS", str(exc))
        return False, format_tool_call(
            ToolCallRequest(
                command="next-defer",
                args=slug,
                project=_derive_project_root(cwd, slug),
                guidance=guidance,
                subfolder=f"{WORKTREE_DIR}/{slug}",
                next_call=f"telec todo work {slug}",
                post_block=(
                    f"WHEN WORKER IDLES:\nCall telec todo work {slug}. The state machine emits the next action."
                ),
            )
        )

    session_id = get_session_id() or ""
    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    round_raw = build_review.get("round", 0)
    review_round = round_raw if isinstance(round_raw, int) else 0
    try:
        await emit_review_approved(slug=slug, reviewer_session_id=session_id, review_round=max(review_round, 1))
    except Exception:
        logger.warning("Failed to emit review.approved event for %s", slug, exc_info=True)

    try:
        guidance = await compose_agent_guidance(db)
    except RuntimeError as exc:
        return False, format_error("NO_AGENTS", str(exc))

    is_bug = await todos_db.is_bug_todo(slug)
    note = "BUG FIX: Skip delivery bookkeeping. Delete todo directory after merge." if is_bug else ""
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_FINALIZE,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            next_call=f"telec todo work {slug}",
            note=note,
            post_block=(
                f"WHEN WORKER REPORTS FINALIZE_READY:\n"
                f"Call telec todo work {slug}. The state machine will drive the finalize handoff."
            ),
        )
    )


async def _work_step_finalize_ready(
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    worktree_cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """FINALIZE_READY: record the actual handoff under machine control."""
    _ = db, cwd, worktree_cwd
    writer = StateWriter(state)
    finalize = writer.state.finalize
    finalize.status = "handed_off"
    finalize.handed_off_at = datetime.now(UTC).isoformat()
    apply_authoritative_signal(writer.state, "finalize_handed_off")
    await _commit_writer(writer, todos_db, slug, state)
    return True, ""


async def _work_step_handed_off(
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    worktree_cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """HANDED_OFF: terminal cleanup. End worker child sessions and self-end."""
    _ = todos_db, cwd, worktree_cwd, state
    session_id = get_session_id() or ""
    child_session_ids = await _list_child_session_ids(db, session_id)
    return False, format_finalize_handoff_complete(slug, f"telec todo work {slug}", child_session_ids)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def _work_dispatch(
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    worktree_cwd: str,
    phase: WorkPhase,
    state: dict[str, StateValue],
    head_before_merge: str,
    head_after_merge: str,
) -> tuple[bool, str]:
    """Dispatch to the appropriate work phase handler.

    Returns ``(keep_going, instruction)``. When ``keep_going`` is True, the
    caller loops and re-derives the phase. When False, ``instruction`` is the
    orchestrator script to return verbatim.
    """
    if phase == WorkPhase.BUILD_COMPLETE:
        return await _work_step_build_complete(
            db=db,
            todos_db=todos_db,
            slug=slug,
            cwd=cwd,
            worktree_cwd=worktree_cwd,
            state=state,
            head_before_merge=head_before_merge,
            head_after_merge=head_after_merge,
        )

    handlers = {
        WorkPhase.BUILD_STARTED: _work_step_build_started,
        WorkPhase.REVIEW_CHANGES_REQUESTED: _work_step_review_changes_requested,
        WorkPhase.REVIEW_APPROVED: _work_step_review_approved,
        WorkPhase.FINALIZE_READY: _work_step_finalize_ready,
        WorkPhase.HANDED_OFF: _work_step_handed_off,
    }
    handler = handlers.get(phase)
    if handler is None:
        return False, format_error(
            "UNHANDLED_PHASE",
            f"No handler for work phase: {phase.value}",
            next_call=f"telec todo work {slug}",
        )
    return await handler(db=db, todos_db=todos_db, slug=slug, cwd=cwd, worktree_cwd=worktree_cwd, state=state)


__all__ = ["_work_dispatch"]
