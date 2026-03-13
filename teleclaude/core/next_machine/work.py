"""Work stage — Phase B state machine for deterministic builder work.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from time import perf_counter

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.integration_bridge import emit_branch_pushed, emit_deployment_started, emit_review_approved
from teleclaude.core.next_machine._types import (
    NEXT_WORK_PHASE_LOG,
    REVIEW_DIFF_NOTE,
    ItemPhase,
    PhaseName,
    PhaseStatus,
    PreparePhase,
    _SINGLE_FLIGHT_GUARD,
)
from teleclaude.core.next_machine.build_gates import (
    check_file_has_content,
    format_build_gate_failure,
    run_build_gates,
    verify_artifacts,
)
from teleclaude.core.next_machine.delivery import sweep_completed_groups
from teleclaude.core.next_machine.git_ops import (
    compose_agent_guidance,
    has_uncommitted_changes,
    get_stash_entries,
    _has_meaningful_diff,
    _merge_origin_main_into_worktree,
)
from teleclaude.core.next_machine.output_formatting import (
    format_error,
    format_finalize_handoff_complete,
    format_stash_debt,
    format_tool_call,
    format_uncommitted_changes,
)
from teleclaude.core.next_machine.roadmap import (
    add_to_roadmap,
    check_dependencies_satisfied,
    load_roadmap_deps,
    slug_in_roadmap,
)
from teleclaude.core.next_machine.slug_resolution import (
    get_item_phase,
    is_ready_for_work,
    resolve_canonical_project_root,
    resolve_first_runnable_holder_child,
    resolve_slug_async,
    set_item_phase,
)
from teleclaude.core.next_machine.state_io import (
    _get_finalize_state,
    _get_head_commit,
    _is_review_round_limit_reached,
    _mark_finalize_handed_off,
    _review_scope_note,
    has_pending_deferrals,
    is_bug_todo,
    mark_phase,
    read_phase_state,
)
from teleclaude.core.next_machine.worktrees import (
    _ensure_todo_on_remote_main,
    ensure_worktree_with_policy_async,
)

logger = get_logger(__name__)

# Single-flight lock registry — one per (canonical_cwd, slug) pair.
# _SINGLE_FLIGHT_GUARD is the threading.Lock protecting mutations; defined in _types.
_SINGLE_FLIGHT_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


async def _get_slug_single_flight_lock(cwd: str, slug: str) -> asyncio.Lock:
    """Return repo+slug lock keyed by canonical project root for strict isolation."""
    canonical_cwd = await asyncio.to_thread(resolve_canonical_project_root, cwd)
    key = (canonical_cwd, slug)
    with _SINGLE_FLIGHT_GUARD:
        lock = _SINGLE_FLIGHT_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _SINGLE_FLIGHT_LOCKS[key] = lock
    return lock


def _log_next_work_phase(slug: str, phase: str, started_at: float, decision: str, reason: str) -> None:
    """Emit grep-friendly phase timing logs for /todos/work."""
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    phase_slug = slug or "<auto>"
    logger.info(
        "%s slug=%s phase=%s decision=%s reason=%s duration_ms=%d",
        NEXT_WORK_PHASE_LOG,
        phase_slug,
        phase,
        decision,
        reason,
        elapsed_ms,
    )
    try:
        from teleclaude.core.operations import emit_operation_progress

        emit_operation_progress(phase, decision, reason)
    except Exception:
        logger.debug("Operation progress emission skipped", exc_info=True)


async def next_work(db: Db, slug: str | None, cwd: str) -> str:
    """Phase B state machine for deterministic builder work.

    Executes the build/review/fix/finalize cycle on prepared work items.
    Only considers items with phase "ready" and satisfied dependencies.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from roadmap if not provided)
        cwd: Current working directory (project root)

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    canonical_cwd = await asyncio.to_thread(resolve_canonical_project_root, cwd)
    if canonical_cwd != cwd:
        logger.debug(
            "next_work normalized cwd to canonical project root", requested_cwd=cwd, canonical_cwd=canonical_cwd
        )
        cwd = canonical_cwd

    # Sweep completed group parents before resolving next slug
    await asyncio.to_thread(sweep_completed_groups, cwd)

    phase_slug = slug or "<auto>"
    slug_resolution_started = perf_counter()

    # 1. Resolve slug - only ready items when no explicit slug
    deps = await asyncio.to_thread(load_roadmap_deps, cwd)

    resolved_slug: str
    if slug:
        # Explicit slug provided - verify it's in roadmap, ready, and dependencies satisfied
        # Bugs bypass the roadmap check (they're not in the roadmap)
        is_bug = await asyncio.to_thread(is_bug_todo, cwd, slug)
        if not is_bug and not await asyncio.to_thread(slug_in_roadmap, cwd, slug):
            # Auto-add to roadmap — user intent is clear
            await asyncio.to_thread(add_to_roadmap, cwd, slug)
            logger.info("AUTO_ROADMAP_ADD slug=%s machine=work", slug)
            # Reload deps after roadmap change
            deps = await asyncio.to_thread(load_roadmap_deps, cwd)

        # Holder resolution: if slug is a container with children, route to first runnable child
        if not is_bug:
            holder_child, holder_reason = await asyncio.to_thread(resolve_first_runnable_holder_child, cwd, slug, deps)
            if holder_child:
                slug = holder_child
            elif holder_reason == "complete":
                _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "holder_complete")
                return f"COMPLETE: Holder '{slug}' has no remaining child work."
            elif holder_reason == "deps_unsatisfied":
                _log_next_work_phase(
                    phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_deps_unsatisfied"
                )
                return format_error(
                    "DEPS_UNSATISFIED",
                    f"Holder '{slug}' has children, but none are currently runnable due to unsatisfied dependencies.",
                    next_call="Complete dependency items first.",
                )
            elif holder_reason == "item_not_ready":
                _log_next_work_phase(
                    phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_not_ready"
                )
                return format_error(
                    "ITEM_NOT_READY",
                    f"Holder '{slug}' has children, but none are ready to start work.",
                    next_call=f"Call telec todo prepare on the child items for '{slug}' first.",
                )
            elif holder_reason == "children_not_in_roadmap":
                _log_next_work_phase(
                    phase_slug, "slug_resolution", slug_resolution_started, "error", "holder_children_missing"
                )
                return format_error(
                    "NOT_PREPARED",
                    f"Holder '{slug}' has child todos, but none are in roadmap.",
                    next_call="Add child items to roadmap or call telec todo prepare.",
                )

        phase = await asyncio.to_thread(get_item_phase, cwd, slug)
        if (
            not is_bug
            and phase == ItemPhase.PENDING.value
            and not await asyncio.to_thread(is_ready_for_work, cwd, slug)
        ):
            _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "item_not_ready")
            return format_error(
                "ITEM_NOT_READY",
                f"Item '{slug}' is pending and DOR score is below threshold. Must be ready to start work.",
                next_call=f"Call telec todo prepare {slug} to prepare it first.",
            )
        if phase == ItemPhase.DONE.value:
            _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "item_done")
            return f"COMPLETE: Item '{slug}' is already done."

        # Item is ready or in_progress - check dependencies
        if not await asyncio.to_thread(check_dependencies_satisfied, cwd, slug, deps):
            _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "error", "deps_unsatisfied")
            return format_error(
                "DEPS_UNSATISFIED",
                f"Item '{slug}' has unsatisfied dependencies.",
                next_call="Complete dependency items first, or check todos/roadmap.yaml.",
            )
        resolved_slug = slug  # type: ignore[assignment]  # narrowed by `if slug:` above
    else:
        # R6: Use resolve_slug with dependency gating
        found_slug, _, _ = await resolve_slug_async(cwd, None, True, deps)

        if not found_slug:
            # Check if there are ready items (without dependency gating) to provide better error
            has_ready_items, _, _ = await resolve_slug_async(cwd, None, True)

            if has_ready_items:
                _log_next_work_phase(
                    phase_slug, "slug_resolution", slug_resolution_started, "error", "ready_but_deps_unsatisfied"
                )
                return format_error(
                    "DEPS_UNSATISFIED",
                    "Ready items exist but all have unsatisfied dependencies.",
                    next_call="Complete dependency items first, or check todos/roadmap.yaml.",
                )
            _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "skip", "no_ready_items")
            return format_error(
                "NO_READY_ITEMS",
                "No ready items found in roadmap.",
                next_call="Call telec todo prepare to prepare items first.",
            )
        resolved_slug = found_slug  # type: ignore[assignment]  # narrowed by early return above

    phase_slug = resolved_slug
    _log_next_work_phase(phase_slug, "slug_resolution", slug_resolution_started, "run", "resolved")

    preconditions_started = perf_counter()

    # 2. Guardrail: stash debt is forbidden for AI orchestration
    stash_entries = await asyncio.to_thread(get_stash_entries, cwd)
    if stash_entries:
        _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "error", "stash_debt")
        return format_stash_debt(resolved_slug, len(stash_entries))

    # 3. Validate preconditions
    # Bugs use bug.md; regular todos use requirements.md + implementation-plan.md
    precondition_root = cwd
    worktree_path = Path(cwd) / WORKTREE_DIR / resolved_slug
    is_bug = await asyncio.to_thread(is_bug_todo, cwd, resolved_slug)
    if worktree_path.exists():
        if is_bug:
            if check_file_has_content(str(worktree_path), f"todos/{resolved_slug}/bug.md"):
                precondition_root = str(worktree_path)
        elif (
            check_file_has_content(str(worktree_path), f"todos/{resolved_slug}/requirements.md")
            and check_file_has_content(str(worktree_path), f"todos/{resolved_slug}/implementation-plan.md")
        ):
            precondition_root = str(worktree_path)

    if not is_bug:
        has_requirements = check_file_has_content(precondition_root, f"todos/{resolved_slug}/requirements.md")
        has_impl_plan = check_file_has_content(precondition_root, f"todos/{resolved_slug}/implementation-plan.md")
        if not (has_requirements and has_impl_plan):
            _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "error", "not_prepared")
            return format_error(
                "NOT_PREPARED",
                f"todos/{resolved_slug} is missing requirements or implementation plan.",
                next_call=f"Call telec todo prepare {resolved_slug} to complete preparation.",
            )
    else:
        has_bug_md = check_file_has_content(precondition_root, f"todos/{resolved_slug}/bug.md")
        if not has_bug_md:
            _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "error", "invalid_bug")
            return format_error(
                "INVALID_BUG",
                f"todos/{resolved_slug} has kind='bug' but bug.md is missing or empty.",
                next_call=f"Recreate with: telec bugs create {resolved_slug}",
            )
    _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "run", "validated")

    # 3b. Pre-build freshness gate: verify preparation is still valid
    if not is_bug:
        prep_state = await asyncio.to_thread(read_phase_state, cwd, resolved_slug)
        prepare_phase_val = str(prep_state.get("prepare_phase", "")).strip()
        grounding = prep_state.get("grounding", {})
        grounding_valid = isinstance(grounding, dict) and grounding.get("valid") is True
        # Only block if prepare_phase is explicitly set and not "prepared",
        # or grounding is explicitly invalidated. Legacy todos (no prepare_phase) pass through.
        if prepare_phase_val and prepare_phase_val != PreparePhase.PREPARED.value:
            _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "error", "stale_preparation")
            return format_error(
                "STALE",
                f"{resolved_slug} preparation is not complete (phase: {prepare_phase_val}).",
                next_call=f"Run telec todo prepare {resolved_slug} to re-ground.",
            )
        if prepare_phase_val == PreparePhase.PREPARED.value and not grounding_valid:
            _log_next_work_phase(phase_slug, "preconditions", preconditions_started, "error", "stale_grounding")
            return format_error(
                "STALE",
                f"{resolved_slug} preparation is invalidated (grounding.valid=false).",
                next_call=f"Run telec todo prepare {resolved_slug} to re-ground.",
            )

    # 3c. Ensure todo artifacts exist on origin/main before worktree creation.
    # Worktrees branch from origin/main — locally scaffolded artifacts (bugs, todos)
    # must be committed and pushed so the worktree includes them.
    # This is a hard prerequisite: if artifacts can't reach origin/main, the
    # worktree won't have them and the worker will fail.
    remote_sync_started = perf_counter()
    sync_ok, sync_reason = await asyncio.to_thread(_ensure_todo_on_remote_main, cwd, resolved_slug)
    sync_decision = "run" if sync_ok else "skip"
    _log_next_work_phase(phase_slug, "ensure_remote_artifacts", remote_sync_started, sync_decision, sync_reason)
    if not sync_ok and sync_reason == "push_deferred":
        return format_error(
            "REMOTE_SYNC_FAILED",
            f"Todo artifacts for {resolved_slug} could not be pushed to origin/main. "
            "Worktrees branch from origin/main — workers won't find the artifacts.",
            next_call="Resolve git conflicts on main, push manually, then retry.",
        )

    worktree_cwd = str(Path(cwd) / WORKTREE_DIR / resolved_slug)
    ensure_started = perf_counter()
    slug_lock = await _get_slug_single_flight_lock(cwd, resolved_slug)
    if slug_lock.locked():
        logger.info(
            "%s slug=%s phase=ensure_prepare decision=wait reason=single_flight_in_progress duration_ms=0",
            NEXT_WORK_PHASE_LOG,
            phase_slug,
        )

    # 4. Ensure worktree exists + conditional prep in single-flight window.
    try:
        async with slug_lock:
            logger.info(
                "next_work entering ensure boundary slug=%s cwd=%s worktree_path=%s",
                resolved_slug,
                cwd,
                worktree_cwd,
            )
            ensure_result = await ensure_worktree_with_policy_async(cwd, resolved_slug)
            if ensure_result.created:
                logger.info("Created new worktree for %s", resolved_slug)
            ensure_decision = "run" if ensure_result.prepared else "skip"
            _log_next_work_phase(
                phase_slug, "ensure_prepare", ensure_started, ensure_decision, ensure_result.prep_reason
            )
    except RuntimeError as exc:
        logger.error(
            "next_work worktree preparation failed for slug=%s cwd=%s worktree_path=%s: %s",
            resolved_slug,
            cwd,
            worktree_cwd,
            exc,
            exc_info=True,
        )
        _log_next_work_phase(phase_slug, "ensure_prepare", ensure_started, "error", "prep_failed")
        return format_error(
            "WORKTREE_PREP_FAILED",
            str(exc),
            next_call="Add tools/worktree-prepare.sh or fix its execution, then retry.",
        )
    except Exception as exc:
        logger.error(
            "next_work worktree setup failed for slug=%s cwd=%s worktree_path=%s: %s",
            resolved_slug,
            cwd,
            worktree_cwd,
            exc,
            exc_info=True,
        )
        _log_next_work_phase(phase_slug, "ensure_prepare", ensure_started, "error", f"unexpected_{type(exc).__name__}")
        return format_error(
            "WORKTREE_SETUP_FAILED",
            f"Unexpected error while ensuring worktree for {resolved_slug}: {type(exc).__name__}: {exc}",
            next_call="Inspect daemon logs for worktree setup failure, fix the repository or branch state, then retry.",
        )

    dispatch_started = perf_counter()

    # 5. Check uncommitted changes
    if has_uncommitted_changes(cwd, resolved_slug):
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "uncommitted_changes")
        return format_uncommitted_changes(resolved_slug)

    # 6. Claim the item (pending → in_progress) — safe to do here since it's
    # just a "someone is looking at this" marker. Even if the orchestrator doesn't
    # dispatch, the next next_work() call picks it up again.
    current_phase = await asyncio.to_thread(get_item_phase, worktree_cwd, resolved_slug)
    if current_phase == ItemPhase.PENDING.value:
        await asyncio.to_thread(set_item_phase, worktree_cwd, resolved_slug, ItemPhase.IN_PROGRESS.value)

    # 7. Route from worktree-owned build/review state.
    # Review is authoritative: once approved, never regress back to build because
    # of clerical build-state drift.
    state = await asyncio.to_thread(read_phase_state, worktree_cwd, resolved_slug)
    build_value = state.get(PhaseName.BUILD.value)
    build_status = build_value if isinstance(build_value, str) else PhaseStatus.PENDING.value
    review_value = state.get(PhaseName.REVIEW.value)
    review_status = review_value if isinstance(review_value, str) else PhaseStatus.PENDING.value

    # Repair contradictory state: review approved implies build complete.
    if review_status == PhaseStatus.APPROVED.value and build_status != PhaseStatus.COMPLETE.value:
        repair_started = perf_counter()
        await asyncio.to_thread(
            mark_phase, worktree_cwd, resolved_slug, PhaseName.BUILD.value, PhaseStatus.COMPLETE.value
        )
        build_status = PhaseStatus.COMPLETE.value
        _log_next_work_phase(
            phase_slug,
            "state_repair",
            repair_started,
            "run",
            "approved_review_implies_build_complete",
        )

    # Guard stale review approvals: if new commits landed after approval baseline,
    # route back through review instead of proceeding to finalize.
    if review_status == PhaseStatus.APPROVED.value:
        baseline_raw = state.get("review_baseline_commit")
        baseline = baseline_raw if isinstance(baseline_raw, str) else ""
        head_sha = await asyncio.to_thread(_get_head_commit, worktree_cwd)
        if (
            baseline
            and head_sha
            and baseline != head_sha
            and await asyncio.to_thread(_has_meaningful_diff, worktree_cwd, baseline, head_sha)
        ):
            repair_started = perf_counter()
            await asyncio.to_thread(
                mark_phase, worktree_cwd, resolved_slug, PhaseName.REVIEW.value, PhaseStatus.PENDING.value
            )
            review_status = PhaseStatus.PENDING.value
            _log_next_work_phase(
                phase_slug,
                "state_repair",
                repair_started,
                "run",
                "review_approval_stale_baseline",
            )

    finalize_state = _get_finalize_state(state)

    # Finalize handoff is a slug-scoped follow-up step after FINALIZE_READY.
    # Once ready is recorded, the next `telec todo work {slug}` must consume
    # that durable state and emit integration events exactly once before the
    # queue is allowed to advance.
    if review_status == PhaseStatus.APPROVED.value and finalize_state.get("status") == "handed_off":
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "skip", "finalize_already_handed_off")
        return format_error(
            "FINALIZE_ALREADY_HANDED_OFF",
            f"{resolved_slug} has already been handed off to integration. Continue the queue without a slug.",
            next_call="telec todo work",
        )

    if review_status == PhaseStatus.APPROVED.value and finalize_state.get("status") == "ready":
        branch = finalize_state.get("branch", "").strip()
        sha = finalize_state.get("sha", "").strip()
        worker_session_id = finalize_state.get("worker_session_id", "").strip()
        if not branch or not sha:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "finalize_state_invalid")
            return format_error(
                "FINALIZE_STATE_INVALID",
                f"{resolved_slug} finalize state is missing branch or sha; re-run finalize prepare.",
                next_call=f"telec todo work {resolved_slug}",
            )

        session_id = os.environ.get("TELECLAUDE_SESSION_ID", "unknown")
        handoff_started = perf_counter()
        try:
            await emit_branch_pushed(
                branch=branch,
                sha=sha,
                remote="origin",
                pusher=f"finalizer/{worker_session_id}" if worker_session_id else "",
            )
            await emit_deployment_started(
                slug=resolved_slug,
                branch=branch,
                sha=sha,
                worker_session_id=worker_session_id,
                orchestrator_session_id=session_id,
                ready_at=finalize_state.get("ready_at"),
            )
            await asyncio.to_thread(
                _mark_finalize_handed_off,
                worktree_cwd,
                resolved_slug,
                handoff_session_id=session_id,
            )
        except Exception as exc:
            _log_next_work_phase(phase_slug, "dispatch_decision", handoff_started, "error", "finalize_handoff_failed")
            return format_error(
                "FINALIZE_HANDOFF_FAILED",
                f"Failed to emit finalize handoff for {resolved_slug}: {type(exc).__name__}: {exc}",
                next_call=f"telec todo work {resolved_slug}",
            )
        _log_next_work_phase(phase_slug, "dispatch_decision", handoff_started, "run", "finalize_handoff_emitted")

        # Collect active child sessions spawned by this orchestrator for cleanup
        child_session_ids: list[str] = []
        if session_id != "unknown":
            try:
                child_sessions = await db.list_sessions(initiator_session_id=session_id)
                child_session_ids = [s.session_id for s in child_sessions]
            except Exception:
                logger.warning("Failed to query child sessions for cleanup", session_id=session_id)

        return format_finalize_handoff_complete(resolved_slug, "telec todo work", child_session_ids)

    # If review requested changes, continue fix loop regardless of build-state drift.
    if review_status == PhaseStatus.CHANGES_REQUESTED.value:
        try:
            guidance = await compose_agent_guidance(db)
        except RuntimeError as exc:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
            return format_error("NO_AGENTS", str(exc))
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_fix_review")
        return format_tool_call(
            command=SlashCommand.NEXT_FIX_REVIEW,
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
            note=(
                "PEER CONVERSATION NOTE: If you still have the reviewer session alive from the "
                "previous review dispatch, prefer the direct conversation pattern from "
                "POST_COMPLETION[next-review-build] instead of a fresh fix-review dispatch: "
                "send fixer and reviewer session IDs to each other with --direct to let them "
                "iterate without context-destroying churn. This fallback path is for when the "
                "reviewer session has already ended."
            ),
        )

    # Pending review still requires build completion + gates before dispatching review.
    if review_status != PhaseStatus.APPROVED.value:
        # mark_phase(build, started) is deferred to the orchestrator via pre_dispatch
        # to avoid orphaned "build: started" when the orchestrator decides not to dispatch.
        if build_status != PhaseStatus.COMPLETE.value:
            # Merge origin/main into the worktree before build dispatch so the
            # builder starts on a current branch and inherits any test fixes from main.
            merge_main_result = await asyncio.to_thread(_merge_origin_main_into_worktree, worktree_cwd, resolved_slug)
            if merge_main_result:
                _log_next_work_phase(phase_slug, "merge_main", dispatch_started, "error", "merge_main_failed")
                return format_error("MERGE_MAIN_FAILED", merge_main_result)

            try:
                guidance = await compose_agent_guidance(db)
            except RuntimeError as exc:
                _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
                return format_error("NO_AGENTS", str(exc))

            # Build pre-dispatch marking instructions
            pre_dispatch = f"telec todo mark-phase {resolved_slug} --phase build --status started"

            # Bugs use next-bugs-fix instead of next-build
            # Check main repo's todos/ (bug.md lives there, not synced to worktree)
            is_bug = await asyncio.to_thread(is_bug_todo, cwd, resolved_slug)
            if is_bug:
                _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_bugs_fix")
                return format_tool_call(
                    command=SlashCommand.NEXT_BUGS_FIX,
                    args=resolved_slug,
                    project=cwd,
                    guidance=guidance,
                    subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
                    next_call=f"telec todo work {resolved_slug}",
                    pre_dispatch=pre_dispatch,
                )
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_build")
            return format_tool_call(
                command=SlashCommand.NEXT_BUILD,
                args=resolved_slug,
                project=cwd,
                guidance=guidance,
                subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
                next_call=f"telec todo work {resolved_slug}",
                pre_dispatch=pre_dispatch,
            )

        # Build gates: verify tests and demo structure before allowing review.
        review_round_raw = state.get("review_round")
        review_round = review_round_raw if isinstance(review_round_raw, int) else 0
        gate_started = perf_counter()
        gates_passed, gate_output = await asyncio.to_thread(run_build_gates, worktree_cwd, resolved_slug)
        if not gates_passed:
            gate_log_detail = "build_gates_failed_post_review" if review_round > 0 else "build_gates_failed"
            _log_next_work_phase(phase_slug, "gate_execution", gate_started, "error", gate_log_detail)
            if review_round == 0:
                # First build: reset to started so the builder retries from scratch
                await asyncio.to_thread(
                    mark_phase, worktree_cwd, resolved_slug, PhaseName.BUILD.value, PhaseStatus.STARTED.value
                )
            # review_round > 0: keep build=complete; builder gets a focused fix instruction
            next_call = f"telec todo work {resolved_slug}"
            return format_build_gate_failure(resolved_slug, gate_output, next_call)
        _log_next_work_phase(phase_slug, "gate_execution", gate_started, "run", "build_gates_passed")

        # Artifact verification: check implementation plan checkboxes, commits, quality checklist.
        verify_started = perf_counter()
        is_bug = await asyncio.to_thread(is_bug_todo, cwd, resolved_slug)
        artifacts_passed, artifacts_output = await asyncio.to_thread(
            verify_artifacts, worktree_cwd, resolved_slug, PhaseName.BUILD.value, is_bug=is_bug
        )
        if not artifacts_passed:
            artifact_log_detail = (
                "artifact_verification_failed_post_review" if review_round > 0 else "artifact_verification_failed"
            )
            _log_next_work_phase(phase_slug, "gate_execution", verify_started, "error", artifact_log_detail)
            if review_round == 0:
                await asyncio.to_thread(
                    mark_phase, worktree_cwd, resolved_slug, PhaseName.BUILD.value, PhaseStatus.STARTED.value
                )
            # review_round > 0: keep build=complete; builder gets a focused fix instruction
            next_call = f"telec todo work {resolved_slug}"
            return format_build_gate_failure(resolved_slug, artifacts_output, next_call)
        _log_next_work_phase(phase_slug, "gate_execution", verify_started, "run", "artifact_verification_passed")

        # Review not started or still pending.
        limit_reached, current_round, max_rounds = _is_review_round_limit_reached(worktree_cwd, resolved_slug)
        if limit_reached:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "review_round_limit")
            return format_error(
                "REVIEW_ROUND_LIMIT",
                (
                    f"Review rounds exceeded for {resolved_slug}: "
                    f"current={current_round}, max={max_rounds}. "
                    f"Manual resolution required.\n\n"
                    f"Before acting, load the relevant worker role:\n"
                    f"  telec docs index\n"
                    f"Then use telec docs get to load the procedure for the role you are assuming."
                ),
                next_call=f"telec todo work {resolved_slug}",
            )
        try:
            guidance = await compose_agent_guidance(db)
        except RuntimeError as exc:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
            return format_error("NO_AGENTS", str(exc))
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_review")
        return format_tool_call(
            command=SlashCommand.NEXT_REVIEW_BUILD,
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
            note=f"{REVIEW_DIFF_NOTE}\n\n{_review_scope_note(worktree_cwd, resolved_slug)}",
        )

    # 8.5 Check pending deferrals (R7)
    if await asyncio.to_thread(has_pending_deferrals, worktree_cwd, resolved_slug):
        try:
            guidance = await compose_agent_guidance(db)
        except RuntimeError as exc:
            _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
            return format_error("NO_AGENTS", str(exc))
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_defer")
        return format_tool_call(
            command="next-defer",  # not a SlashCommand; deferred to runtime resolution
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
            next_call=f"telec todo work {resolved_slug}",
        )

    # 9. Review approved - dispatch finalize prepare
    if has_uncommitted_changes(cwd, resolved_slug):
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "uncommitted_changes")
        return format_uncommitted_changes(resolved_slug)
    try:
        guidance = await compose_agent_guidance(db)
    except RuntimeError as exc:
        _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "error", "no_agents")
        return format_error("NO_AGENTS", str(exc))

    # Emit review.approved event once finalize dispatch begins. The later
    # slug-specific handoff step emits branch/deployment events after the
    # finalizer has actually reported FINALIZE_READY.
    review_round_val = state.get("review_round")
    review_round = review_round_val if isinstance(review_round_val, int) else 1
    session_id = os.environ.get("TELECLAUDE_SESSION_ID", "unknown")
    try:
        await emit_review_approved(
            slug=resolved_slug,
            reviewer_session_id=session_id,
            review_round=review_round,
        )
    except Exception:
        logger.warning("Failed to emit review.approved event for %s", resolved_slug, exc_info=True)

    # Bugs skip delivered.yaml bookkeeping and are removed from todos entirely
    # Check main repo's todos/ (bug.md lives there, not synced to worktree)
    is_bug = await asyncio.to_thread(is_bug_todo, cwd, resolved_slug)
    note = "BUG FIX: Skip delivered.yaml bookkeeping. Delete todo directory after merge." if is_bug else ""
    _log_next_work_phase(phase_slug, "dispatch_decision", dispatch_started, "run", "dispatch_finalize")
    return format_tool_call(
        command=SlashCommand.NEXT_FINALIZE,
        args=resolved_slug,
        project=cwd,
        guidance=guidance,
        subfolder=f"{WORKTREE_DIR}/{resolved_slug}",
        next_call=f"telec todo work {resolved_slug}",
        note=note,
    )


__all__ = ["next_work"]
