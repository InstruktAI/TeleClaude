"""Work state machine — phase step handlers and dispatcher.

Mirrors the prepare lifecycle loop pattern. Each handler is a pure
(state + side-effect) transition that returns ``(keep_going, instruction)``:

- ``keep_going=True``: the state mutated, the loop re-derives the work phase
  and re-dispatches without a worker round-trip.
- ``keep_going=False``: return ``instruction`` verbatim as the orchestrator
  script. The worker will idle, then the orchestrator re-enters the loop.

No imports from core.py (circular-import guard).
"""

# pylint: disable=cyclic-import  # Work state machine bridges next_machine sub-modules.

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.integration_bridge import (
    emit_branch_pushed,
    emit_deployment_started,
    emit_review_approved,
)
from teleclaude.core.next_machine._types import (
    DEFAULT_MAX_REVIEW_ROUNDS,
    DOR_READY_THRESHOLD,
    REVIEW_DIFF_NOTE,
    StateValue,
    WorkPhase,
)
from teleclaude.core.next_machine.git_ops import (
    compose_agent_guidance,
    get_head_commit,
    has_uncommitted_changes,
)
from teleclaude.core.next_machine.output_formatting import (
    ToolCallRequest,
    format_error,
    format_finalize_handoff_complete,
    format_tool_call,
    format_uncommitted_changes,
)
from teleclaude.core.next_machine.prepare_steps import (
    _commit_writer,
    _derive_project_root,
)
from teleclaude.core.next_machine.runtime.sessions import find_live_session_for_slug
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.session_identity import get_session_id

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

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


def _append_event(
    state: dict[str, StateValue],
    *,
    actor: str,
    kind: str,
    details: dict[str, StateValue] | None = None,
) -> None:
    """Append a typed event to the state's audit log (best-effort)."""
    events = state.get("events")
    if not isinstance(events, list):
        events = []
        state["events"] = events
    events.append(
        {
            "at": datetime.now(UTC).isoformat(),
            "actor": actor,
            "kind": kind,
            "details": details or {},
        }
    )


async def _list_child_session_ids(db: Db, session_id: str) -> list[str]:
    """List child sessions spawned by the current orchestrator session."""
    if not session_id:
        return []
    try:
        child_sessions = await db.list_sessions(initiator_session_id=session_id)
        return [session.session_id for session in child_sessions]
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to query child sessions for cleanup", session_id=session_id)
        return []


# ---------------------------------------------------------------------------
# Phase handlers
# ---------------------------------------------------------------------------


async def _work_step_build_started(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    worktree_cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """BUILD_STARTED: look up a live builder, otherwise dispatch a fresh one.

    DOR precondition: regular todos must have ``dor.score >= DOR_READY_THRESHOLD``.
    Bugs skip DOR. Prepped todos are expected to have their DOR stamped by the
    prepare machine; if it is missing we treat that as a contract violation.
    """
    _ = todos_db, worktree_cwd  # dispatch is stateless from todos_db view

    kind_raw = state.get("kind")
    kind = kind_raw if isinstance(kind_raw, str) else "todo"

    if kind != "bug":
        dor_raw = state.get("dor")
        dor = dor_raw if isinstance(dor_raw, dict) else {}
        score_raw = dor.get("score", 0)
        score = score_raw if isinstance(score_raw, int) else 0
        if score < DOR_READY_THRESHOLD:
            return False, format_error(
                "NOT_PREPARED",
                (
                    f"{slug} has DOR score {score} < {DOR_READY_THRESHOLD}. "
                    f"Run telec todo prepare {slug} before entering work."
                ),
                next_call=f"telec todo prepare {slug}",
            )

    command = SlashCommand.NEXT_BUGS_FIX if kind == "bug" else SlashCommand.NEXT_BUILD
    builder_id = await find_live_session_for_slug(db, slug, f"/{command.value}")
    if builder_id is not None:
        return False, (
            f"BUILDER ACTIVE: {slug}\n\n"
            f"Builder session {builder_id} is still running. "
            f"Wait for its next idle event, then call telec todo work {slug}."
        )

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
            next_call=f"telec todo work {slug}",
            post_block=_builder_idle_post_block(slug),
        )
    )


async def _work_step_build_complete(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
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
    from teleclaude.core.next_machine.review_runtime import (  # pylint: disable=import-outside-toplevel
        ReviewDispatchContext,
        resolve_pending_review_state,
    )

    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    round_raw = build_review.get("round", 0)
    round_num = round_raw if isinstance(round_raw, int) else 0

    if round_num > DEFAULT_MAX_REVIEW_ROUNDS:
        return False, format_error(
            "REVIEW_ROUND_LIMIT",
            (
                f"Review rounds exceeded for {slug}: current={round_num}, "
                f"max={DEFAULT_MAX_REVIEW_ROUNDS}. Manual resolution required."
            ),
            next_call=f"telec todo work {slug}",
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
            f"up to HEAD {head_sha or '<unknown>'}. Stamp verdict with "
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


async def _work_step_review_changes_requested(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    worktree_cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """REVIEW_CHANGES_REQUESTED: relay findings to the live builder, or loop if fixed.

    If the builder has committed fixes (HEAD advanced beyond the review baseline),
    clear the verdict so the next iteration re-derives to BUILD_COMPLETE and
    dispatches a re-review. Otherwise relay the findings to the existing builder
    session and wait for FIX COMPLETE.
    """
    _ = cwd
    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    baseline_raw = build_review.get("baseline_commit", "")
    baseline = baseline_raw if isinstance(baseline_raw, str) else ""
    head_sha = await asyncio.to_thread(get_head_commit, worktree_cwd)

    if baseline and head_sha and head_sha != baseline:
        # Builder has committed fixes — clear the verdict and bump the round.
        # Keep baseline_commit pointing at the commit the reviewer last reviewed
        # so the re-review dispatch can scope diff to baseline..HEAD.
        writer = StateWriter(state)
        review = writer.state.build_review
        review.verdict = ""
        review.dispatch_head = ""
        review.round = review.round + 1
        _append_event(
            state,
            actor="work_state_machine",
            kind="review_round_advanced",
            details={"slug": slug, "round": review.round, "baseline": baseline},
        )
        await _commit_writer(writer, todos_db, slug, state)
        return True, ""  # loop — re-derive phase

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
        f"Address the findings and report FIX COMPLETE. "
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


async def _work_step_review_approved(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
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
    except Exception:  # pylint: disable=broad-exception-caught
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


async def _work_step_finalize_ready(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    worktree_cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """FINALIZE_READY: emit integration events and advance finalize to handed_off.

    Validates worktree branch/sha are populated, emits branch_pushed and
    deployment_started events, then stamps ``finalize.status = "handed_off"``
    so the next loop iteration derives HANDED_OFF.
    """
    _ = db, cwd, worktree_cwd
    finalize_raw = state.get("finalize")
    finalize = finalize_raw if isinstance(finalize_raw, dict) else {}
    branch_raw = finalize.get("branch", "")
    branch = branch_raw.strip() if isinstance(branch_raw, str) else ""
    sha_raw = finalize.get("sha", "")
    sha = sha_raw.strip() if isinstance(sha_raw, str) else ""
    worker_session_raw = finalize.get("worker_session_id", "")
    worker_session_id = worker_session_raw.strip() if isinstance(worker_session_raw, str) else ""
    ready_at_raw = finalize.get("ready_at", "")
    ready_at = ready_at_raw if isinstance(ready_at_raw, str) else ""

    if not branch or not sha:
        return False, format_error(
            "FINALIZE_STATE_INVALID",
            f"{slug} finalize state is missing branch or sha; re-run finalize prepare.",
            next_call=f"telec todo work {slug}",
        )

    try:
        await emit_branch_pushed(
            branch=branch,
            sha=sha,
            remote="origin",
            pusher=f"finalizer/{worker_session_id}" if worker_session_id else "",
        )
        await emit_deployment_started(
            slug=slug,
            branch=branch,
            sha=sha,
            worker_session_id=worker_session_id,
            ready_at=ready_at or None,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("finalize handoff failed for %s", slug, exc_info=True)
        return False, format_error(
            "FINALIZE_HANDOFF_FAILED",
            f"Failed to emit finalize handoff for {slug}: {type(exc).__name__}: {exc}",
            next_call=f"telec todo work {slug}",
        )

    writer = StateWriter(state)
    writer.state.finalize.status = "handed_off"
    writer.state.finalize.handed_off_at = datetime.now(UTC).isoformat()
    writer.state.finalize.handoff_session_id = get_session_id() or ""
    _append_event(
        state,
        actor="work_state_machine",
        kind="finalize_handed_off",
        details={"slug": slug, "branch": branch, "sha": sha},
    )
    await _commit_writer(writer, todos_db, slug, state)
    return True, ""  # loop — next iter derives HANDED_OFF


async def _work_step_handed_off(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
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


async def _work_dispatch(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
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
