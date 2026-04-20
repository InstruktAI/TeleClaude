"""Review runtime helpers for the work state machine.

Extracted from work.py to keep the orchestration module focused on top-level
routing while this module owns live-review reuse and verdict reconciliation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import PhaseStatus, StateValue
from teleclaude.core.next_machine.git_ops import get_head_commit, review_surface_overlap_files
from teleclaude.core.next_machine.output_formatting import format_error
from teleclaude.core.next_machine.runtime.scripts import (
    format_review_ground_shift_script,
    format_review_in_progress_script,
)
from teleclaude.core.next_machine.runtime.sessions import find_live_session_with_status_for_slug

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb
from teleclaude.core.next_machine.state_mutation import StateWriter


def _read_build_review(state: dict[str, StateValue]) -> dict[str, StateValue]:
    """Extract build_review sub-dict from state, defaulting to empty."""
    raw = state.get("build_review")
    return raw if isinstance(raw, dict) else {}


@dataclass(frozen=True)
class ReviewDispatchContext:
    """Stable inputs for one review-resolution decision."""

    db: Db
    todos_db: TodosDb
    worktree_cwd: str
    slug: str


@dataclass(frozen=True)
class ReviewResolution:
    """Result of reconciling pending review state."""

    state: dict[str, StateValue]
    status: str
    instruction: str | None


async def _persist_review_dispatch_metadata(
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
    *,
    baseline_commit: str | None = None,
    dispatch_head: str | None = None,
) -> dict[str, StateValue]:
    """Persist review-dispatch bookkeeping via the validated state boundary."""
    writer = StateWriter(state)
    if baseline_commit is not None:
        writer.state.build_review.baseline_commit = baseline_commit
    if dispatch_head is not None:
        writer.state.build_review.dispatch_head = dispatch_head
    payload = await writer.commit(todos_db, slug)
    state.clear()
    state.update(payload)
    return state


async def _resolve_live_review(
    context: ReviewDispatchContext,
    state: dict[str, StateValue],
    *,
    review_round: int,
    baseline_commit: str,
    dispatch_head: str,
    reviewer_id: str,
    current_head: str,
    head_before_merge: str,
) -> ReviewResolution:
    """Handle review that is still owned by an active reviewer session."""
    needs_initial_baseline = review_round == 0 and not baseline_commit and bool(current_head)
    needs_head_refresh = bool(current_head and dispatch_head != current_head)
    if needs_initial_baseline or needs_head_refresh:
        await _persist_review_dispatch_metadata(
            context.todos_db,
            context.slug,
            state,
            baseline_commit=current_head if needs_initial_baseline else None,
            dispatch_head=current_head if current_head else None,
        )

    if head_before_merge and current_head and head_before_merge != current_head:
        overlapping_files = await asyncio.to_thread(
            review_surface_overlap_files,
            context.worktree_cwd,
            head_before_merge,
            current_head,
        )
        if overlapping_files:
            return ReviewResolution(
                state=state,
                status=PhaseStatus.PENDING.value,
                instruction=format_review_ground_shift_script(
                    context.slug,
                    reviewer_id,
                    head_before_merge,
                    current_head,
                    overlapping_files,
                    next_step=f"telec todo work {context.slug}",
                ),
            )
    return ReviewResolution(
        state=state,
        status=PhaseStatus.PENDING.value,
        instruction=format_review_in_progress_script(
            context.slug,
            reviewer_id,
            next_step=f"telec todo work {context.slug}",
        ),
    )


async def _reconcile_finished_review(
    context: ReviewDispatchContext,
    state: dict[str, StateValue],
    *,
    reviewer_id: str | None,
    reviewer_status: str,
    dispatch_head: str,
) -> ReviewResolution | None:
    """Handle a dispatched review that no longer has an active owner.

    In the derivation-based architecture, if the reviewer stamped a verdict
    (via ``telec todo stamp``), ``build_review.verdict`` is already set and
    phase derivation returns the correct WorkPhase on the next loop iteration.
    This function only detects the edge case where the reviewer idled without
    stamping a verdict.
    """
    if not dispatch_head:
        return None

    # If a verdict is already stamped, phase derivation handles it — nothing to reconcile.
    build_review = _read_build_review(state)
    verdict = build_review.get("verdict", "")
    if verdict:
        return None

    if reviewer_id is not None and reviewer_status == "idle":
        return ReviewResolution(
            state=state,
            status=PhaseStatus.PENDING.value,
            instruction=format_error(
                "REVIEWER_IDLE_WITHOUT_VERDICT",
                f"Reviewer session {reviewer_id} idled for {context.slug}, but review-findings has no verdict.",
                next_call=f"telec sessions tail {reviewer_id}",
            ),
        )
    return None


async def resolve_pending_review_state(
    context: ReviewDispatchContext,
    state: dict[str, StateValue],
    *,
    head_before_merge: str,
    head_after_merge: str,
) -> ReviewResolution:
    """Reconcile live-review progress before deciding whether to dispatch a reviewer."""
    build_review = _read_build_review(state)
    round_raw = build_review.get("round", 0)
    review_round = round_raw if isinstance(round_raw, int) else 0
    baseline_raw = build_review.get("baseline_commit", "")
    baseline_commit = baseline_raw if isinstance(baseline_raw, str) else ""
    dispatch_raw = build_review.get("dispatch_head", "")
    dispatch_head = dispatch_raw if isinstance(dispatch_raw, str) else ""
    current_head = head_after_merge or await asyncio.to_thread(get_head_commit, context.worktree_cwd)
    reviewer_id, reviewer_status = await find_live_session_with_status_for_slug(
        context.db,
        context.slug,
        "/next-review-",
    )

    if reviewer_id is not None and reviewer_status in ("active", "unknown"):
        return await _resolve_live_review(
            context,
            state,
            review_round=review_round,
            baseline_commit=baseline_commit,
            dispatch_head=dispatch_head,
            reviewer_id=reviewer_id,
            current_head=current_head,
            head_before_merge=head_before_merge,
        )

    finished = await _reconcile_finished_review(
        context,
        state,
        reviewer_id=reviewer_id,
        reviewer_status=reviewer_status,
        dispatch_head=dispatch_head,
    )
    if finished is not None:
        return finished

    needs_initial_baseline = review_round == 0 and not baseline_commit and bool(current_head)
    needs_head_refresh = bool(current_head and dispatch_head != current_head)
    if needs_initial_baseline or needs_head_refresh:
        await _persist_review_dispatch_metadata(
            context.todos_db,
            context.slug,
            state,
            baseline_commit=current_head if needs_initial_baseline else None,
            dispatch_head=current_head if current_head else None,
        )
    return ReviewResolution(state=state, status=PhaseStatus.PENDING.value, instruction=None)
