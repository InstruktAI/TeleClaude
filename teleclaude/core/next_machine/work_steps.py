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
import shlex
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
from teleclaude.core.next_machine.build_gates import run_build_gates
from teleclaude.core.next_machine.git_ops import (
    compose_agent_guidance,
    get_head_commit,
    get_ref_commit,
    get_remote_branch_head,
    has_uncommitted_changes,
)
from teleclaude.core.next_machine.kinds import KIND_BUG, KIND_FEATURE, PLAN_ONLY_PREPARE_KINDS
from teleclaude.core.next_machine.lifecycle import LifecyclePhase, apply_authoritative_signal, is_ready_for_work
from teleclaude.core.next_machine.output_formatting import (
    ToolCallRequest,
    format_error,
    format_finalize_handoff_complete,
    format_tool_call,
    format_uncommitted_changes,
)
from teleclaude.core.next_machine.prepare_steps import _commit_writer, _derive_project_root
from teleclaude.core.next_machine.runtime.scripts import format_reviewer_direct_fix_message
from teleclaude.core.next_machine.runtime.sessions import find_live_session_for_slug
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.session_identity import get_session_id

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb
from teleclaude.core.next_machine.review_runtime import ReviewDispatchContext, resolve_pending_review_state

logger = get_logger(__name__)

PREPARED_ARTIFACT_CONTRACT = (
    "Prepared artifact contract for {slug}: PRD is the canonical intent and "
    "requirements source; implementation-plan is the execution spine; "
    "architecture (thin doc-edit log + the domain/design snippets it points "
    "to) is optional context when present. "
    "Legacy requirements is only a fallback when PRD is absent."
)
BUG_ARTIFACT_CONTRACT = (
    "Bug artifact contract for {slug}: the reviewed implementation-plan is the execution "
    "spine; the diagnosis is the verified root-cause context the plan grounds on; input is "
    "the reported symptom. Write the reproduction test the diagnosis prescribes and drive it "
    "red→green."
)
PLAN_ONLY_ARTIFACT_CONTRACT = (
    "Plan-only artifact contract for {slug}: implementation-plan is the intent and execution source "
    "for this {kind} work."
)
_PLAN_ONLY_WORK_KINDS = PLAN_ONLY_PREPARE_KINDS


# ---------------------------------------------------------------------------
# Post-block helpers
# ---------------------------------------------------------------------------


def _builder_idle_post_block(slug: str) -> str:
    """Post-block after dispatching a builder — re-enter the work machine when idle."""
    return (
        f"WHEN WORKER IDLES:\n"
        f"Call telec todo work {slug}. The state machine emits the next action "
        f"after the worker has stamped `telec todo stamp {slug} --build-complete`."
    )


def _reviewer_idle_post_block(slug: str) -> str:
    """Post-block after dispatching a reviewer — re-enter the work machine when idle."""
    return (
        f"WHEN REVIEWER IDLES:\n"
        f"Call telec todo work {slug}. The state machine will read the verdict and "
        f"emit the next action (advance to finalize, relay findings to the builder, "
        f"or terminal cleanup)."
    )


def _prepared_artifact_note(slug: str) -> str:
    """Return the current prepare artifact contract for worker dispatch notes."""
    return PREPARED_ARTIFACT_CONTRACT.format(slug=slug)


def _artifact_contract_note(slug: str, kind: str) -> str:
    """Return the work artifact contract for the current todo kind."""
    if kind == KIND_BUG:
        return BUG_ARTIFACT_CONTRACT.format(slug=slug)
    if kind in _PLAN_ONLY_WORK_KINDS:
        return PLAN_ONLY_ARTIFACT_CONTRACT.format(slug=slug, kind=kind)
    return _prepared_artifact_note(slug)


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


async def _handle_build_complete_claim(
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    worktree_cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str] | None:
    """Consume a build_complete claim by running gates and advancing the lifecycle.

    Returns ``None`` when no claim is outstanding so the caller falls through
    to its normal handler logic. Returns ``(keep_going, instruction)`` when the
    claim was consumed:

    - On pass: clears the claim, fires ``build_complete`` signal,
      ``keep_going=True`` so the dispatch loop advances to the next phase.
    - On fail: clears the claim, returns a fix-relay script that tells the
      orchestrator to send the gate output to the live builder session.
    """
    writer = StateWriter(state)
    if not writer.state.build_gate_claim_at:
        return None

    gates_passed, gate_output = await asyncio.to_thread(run_build_gates, worktree_cwd, slug)
    writer.state.build_gate_claim_at = ""

    if not gates_passed:
        await _commit_writer(writer, todos_db, slug, state)
        builder_id = await find_live_session_for_slug(db, slug, f"/{SlashCommand.NEXT_BUILD.value}")
        if builder_id is None:
            return False, format_error(
                "BUILD_GATE_FAILED",
                f"Build gates failed for {slug} and no live builder session exists to relay output. "
                f"Manual intervention required.\n\n{gate_output}",
                next_call=f"telec todo work {slug}",
            )
        message = (
            f"Build gates failed on your build_complete claim for {slug}. "
            f"Fix the failures and re-stamp build_complete.\n\n{gate_output}"
        )
        escaped = message.replace('"', '\\"')
        return False, (
            f"BUILD GATE FAILED: {slug}\n\n"
            f"Execute in order:\n\n"
            f'telec sessions send {builder_id} "{escaped}"\n\n'
            f"Cancel the old heartbeat timer via KillShell(shell_id=<task_id>).\n"
            f"Start a new non-blocking heartbeat timer via "
            f'Bash(command="sleep 300", run_in_background=true) and save the new task_id.\n'
            f"When the builder reports idle after re-stamping, call telec todo work {slug}."
        )

    apply_authoritative_signal(writer.state, "build_complete", worktree_cwd=worktree_cwd)
    await _commit_writer(writer, todos_db, slug, state)
    return True, ""


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

    Readiness gate is delegated to ``is_ready_for_work`` — the canonical
    helper checks ``lifecycle_phase`` (which already encodes PRD approval,
    plan approval, and grounding validity).
    """
    claim_result = await _handle_build_complete_claim(
        db=db, todos_db=todos_db, slug=slug, worktree_cwd=worktree_cwd, state=state
    )
    if claim_result is not None:
        return claim_result

    kind_raw = state.get("kind")
    kind = kind_raw if isinstance(kind_raw, str) else KIND_FEATURE
    lifecycle_phase_raw = state.get("lifecycle_phase")
    lifecycle_phase = lifecycle_phase_raw if isinstance(lifecycle_phase_raw, str) else None
    ready, reason = is_ready_for_work(kind=kind, lifecycle_phase=lifecycle_phase)
    if not ready:
        return False, format_error(
            "NOT_PREPARED",
            f"{slug} is not ready for work: {reason}. Run telec todo prepare {slug} before entering work.",
            next_call=f"telec todo prepare {slug}",
        )

    command = SlashCommand.NEXT_BUILD
    builder_id = await find_live_session_for_slug(db, slug, f"/{command.value}")
    if builder_id is not None:
        return False, (
            f"BUILDER ACTIVE: {slug}\n\n"
            f"Builder session {builder_id} has not stamped build completion yet. "
            f"Wait for it to run `telec todo stamp {slug} --build-complete`, "
            f"then call telec todo work {slug}."
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
            note=(
                f"{_artifact_contract_note(slug, kind)} Start implementation now. "
                f"When the build is committed and ready for review, "
                f"run `telec todo stamp {slug} --build-complete`."
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
    # Consume a stamped build_review verdict — stamps record facts, the
    # machine fires the lifecycle signal. Derive baseline_commit on first
    # consumption so re-review rounds can scope their diff.
    writer = StateWriter(state)
    br_writer = writer.state.build_review
    if br_writer.verdict in ("approve", "changes_requested"):
        if not br_writer.baseline_commit:
            head = await asyncio.to_thread(get_head_commit, worktree_cwd)
            if head:
                br_writer.baseline_commit = head
        before_phase = writer.state.lifecycle_phase
        apply_authoritative_signal(writer.state, "verdict", phase="build_review")
        if writer.state.lifecycle_phase != before_phase:
            await _commit_writer(writer, todos_db, slug, state)
            return True, ""

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
                f"Review Round Limit Handling: round limit is not an escape hatch. The schema has "
                f"three tiers (Requirement-Violation, Critical, Important) and every tier blocks the "
                f"verdict. Approve is permitted only when every finding is resolved. If any finding "
                f"remains, keep review=changes_requested; if the loop is genuinely stuck, escalate "
                f"to the human with the accumulated findings. Read review-findings and verify."
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
    kind_raw = state.get("kind")
    kind = kind_raw if isinstance(kind_raw, str) else KIND_FEATURE
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
            note=f"{_artifact_contract_note(slug, kind)} {REVIEW_DIFF_NOTE}",
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
    """REVIEW_CHANGES_REQUESTED: relay findings to the live builder, or wait for its stamp.

    The lifecycle remains on ``review_changes_requested`` until the builder
    stamps ``build_complete`` after committing fixes that pass the build gates.
    """
    _ = cwd
    claim_result = await _handle_build_complete_claim(
        db=db, todos_db=todos_db, slug=slug, worktree_cwd=worktree_cwd, state=state
    )
    if claim_result is not None:
        return claim_result

    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    baseline_raw = build_review.get("baseline_commit", "")
    baseline = baseline_raw if isinstance(baseline_raw, str) else ""
    dispatch_head_raw = build_review.get("dispatch_head", "")
    reviewed_head = dispatch_head_raw if isinstance(dispatch_head_raw, str) and dispatch_head_raw else baseline
    head_sha = await asyncio.to_thread(get_head_commit, worktree_cwd)

    # Fix not yet committed: relay findings to live builder.
    builder_id = await find_live_session_for_slug(db, slug, f"/{SlashCommand.NEXT_BUILD.value}")
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
    if reviewer_id is None:
        return False, format_error(
            "REVIEWER_NOT_ALIVE",
            (
                f"Review requested changes for {slug}, but no live reviewer session exists "
                f"to initiate the direct fix conversation. The reviewer should remain alive "
                f"across review rounds. Manual intervention required."
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
        f"When every finding is resolved, commit the fixes and run "
        f"`telec todo stamp {slug} --build-complete`. "
        f"Read findings via: telec todo artifacts read {slug} review-findings"
    )
    reviewer_message = format_reviewer_direct_fix_message(
        fixer_session_id=builder_id,
        task_context=message,
        completion_clause=(
            f"Collaborate until all findings are resolved, then persist the full review-findings artifact "
            f"with telec todo artifacts write {slug} review-findings <content> and set the verdict "
            f"by arithmetic: APPROVE only when unresolved Requirement-Violation, Critical, and Important "
            f"counts are all zero. "
            f"Report FIX COMPLETE."
        ),
    )
    quoted_reviewer_message = shlex.quote(reviewer_message)

    if reviewed_head and head_sha and head_sha != reviewed_head:
        return False, (
            f"FIX WORK NOT STAMPED: {slug}\n\n"
            f"Builder session {builder_id} has commits after reviewed head {reviewed_head} "
            f"at HEAD {head_sha}, but has not stamped build completion.\n\n"
            f"Tell the reviewer to start a direct conversation with the fixer:\n"
            f"telec sessions send {reviewer_id} {quoted_reviewer_message} (you will use regular send, NOT --direct)\n\n"
            f"Wait for it to run `telec todo stamp {slug} --build-complete`, "
            f"then call telec todo work {slug}."
        )

    return False, (
        f"REVIEW CHANGES REQUESTED: {slug}\n\n"
        f"Execute in order:\n\n"
        f"Tell the reviewer to start a direct conversation with the fixer:\n"
        f"telec sessions send {reviewer_id} {quoted_reviewer_message} (you will use regular send, NOT --direct)\n\n"
        f"Cancel the old heartbeat timer via KillShell(shell_id=<task_id>).\n"
        f"Start a new non-blocking heartbeat timer via "
        f'Bash(command="sleep 300", run_in_background=true) and save the new task_id.\n'
        f"Wait for fixer to complete (monitor via heartbeat; do not poll continuously).\n"
        f"Wait for reviewer session {reviewer_id} to report idle.\n"
        f"When the signal arrives, call telec todo work {slug}."
    )


async def _handle_finalize_ready_claim(
    *,
    slug: str,
    cwd: str,
    worktree_cwd: str,
    todos_db: TodosDb,
    state: dict[str, StateValue],
) -> tuple[bool, str] | None:
    """Consume a finalize-ready claim by validating triple-ref consistency.

    Returns ``None`` when no claim is outstanding so the caller falls through
    to its normal dispatch logic. Returns ``(keep_going, instruction)`` when
    the claim was consumed:

    - On valid triple-ref: fires ``finalize_ready`` signal and commits the
      lifecycle change through the state writer, returns ``keep_going=True``.
      The TodosDb phase-transition chokepoint owns integration event emission.
    - On invalid: returns a fix-relay script instructing the orchestrator to
      surface the mismatch (e.g., remote ref drift) and re-stamp.
    """
    writer = StateWriter(state)
    if writer.state.finalize.status != "ready":
        return None
    if writer.state.lifecycle_phase != LifecyclePhase.REVIEW_APPROVED.value:
        return None

    if has_uncommitted_changes(cwd, slug):
        return False, format_error(
            "FINALIZE_UNCOMMITTED",
            f"finalize_ready: worktree {WORKTREE_DIR}/{slug} has uncommitted changes — commit before finalizing",
            next_call=f"telec todo work {slug}",
        )

    worktree_head = await asyncio.to_thread(get_head_commit, worktree_cwd)
    branch_head = await asyncio.to_thread(get_ref_commit, cwd, slug)
    remote_head = await asyncio.to_thread(get_remote_branch_head, cwd, slug)
    claimed_sha = writer.state.finalize.sha

    # Stale-claim guard: every observed ref AND the stamped SHA must agree.
    # If the worker stamped against an older HEAD and someone has since pushed,
    # the refs may match each other but disagree with finalize.sha — never enqueue
    # the wrong commit for integration.
    if not worktree_head or not branch_head or worktree_head != branch_head:
        return False, format_error(
            "FINALIZE_BRANCH_MISMATCH",
            (f"finalize_ready: worktree HEAD ({worktree_head!r}) does not match branch ref {slug!r} ({branch_head!r})"),
            next_call=f"telec todo work {slug}",
        )

    if not remote_head or remote_head != branch_head:
        return False, format_error(
            "FINALIZE_REMOTE_MISMATCH",
            (
                f"finalize_ready: remote branch {slug!r} ({remote_head!r}) does not match "
                f"local branch ({branch_head!r}) — push first, then re-stamp finalize_ready"
            ),
            next_call=f"telec todo work {slug}",
        )

    if not claimed_sha or claimed_sha != worktree_head:
        return False, format_error(
            "FINALIZE_STALE_CLAIM",
            (
                f"finalize_ready: stamped SHA ({claimed_sha!r}) does not match current worktree HEAD "
                f"({worktree_head!r}) — the branch advanced after the claim was stamped. Re-stamp finalize_ready."
            ),
            next_call=f"telec todo work {slug}",
        )

    apply_authoritative_signal(writer.state, "finalize_ready")
    await _commit_writer(writer, todos_db, slug, state)
    return True, ""


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
    - Finalize-ready claim present → triple-ref check, advance lifecycle, emit event.
    - Pending deferrals → dispatch ``/next-defer``.
    - No deferrals → dispatch ``/next-finalize`` (worker stamps finalize_ready).
    """
    finalize_result = await _handle_finalize_ready_claim(
        slug=slug, cwd=cwd, worktree_cwd=worktree_cwd, todos_db=todos_db, state=state
    )
    if finalize_result is not None:
        return finalize_result

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
    """FINALIZE_READY: terminal cleanup. End child sessions and self."""
    _ = todos_db, cwd, worktree_cwd, state
    session_id = get_session_id() or ""
    child_session_ids = await _list_child_session_ids(db, session_id)
    return False, format_finalize_handoff_complete(slug, child_session_ids)


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
