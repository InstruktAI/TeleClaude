"""Prepare stage — Phase A state machine for collaborative architect work.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import _PREPARE_LOOP_LIMIT, PreparePhase, StateValue
from teleclaude.core.next_machine.git_ops import compose_agent_guidance
from teleclaude.core.next_machine.output_formatting import ToolCallRequest, format_tool_call
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.prepare_helpers import (
    _ARTIFACT_CASCADE,
    check_artifact_staleness_db,
)
from teleclaude.core.next_machine.prepare_steps import _prepare_dispatch
from teleclaude.core.next_machine.slug_resolution import (
    resolve_canonical_project_root,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.types.todos import ArtifactEntry

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)


async def _find_next_prepare_slug_db(todos_db: TodosDb) -> str | None:
    """Find next slug needing preparation from DB roadmap and artifact state."""
    entries = await todos_db.list_roadmap()
    for entry in entries:
        slug = entry["slug"]
        state = await todos_db.read_state(slug)
        if state is None:
            continue
        phase = state.get("phase")
        if phase == "done":
            continue
        has_requirements = await todos_db.artifact_exists(slug, "requirements")
        has_impl_plan = await todos_db.artifact_exists(slug, "implementation-plan")
        if not has_requirements or not has_impl_plan:
            return slug
        if phase == "pending":
            return slug
    return None


async def _apply_stale_artifact_reroute(
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
    stale_artifacts: list[str],
) -> dict[str, StateValue]:
    """Reset prepare routing when tracked artifacts have gone stale.

    Restamps all stale artifact digests to match current DB content through the
    typed :class:`ArtifactsState` model before persisting the full validated
    state. Without the restamp, the staleness check fires again on the next
    loop iteration and the machine never escapes the reroute. Returns the
    persisted state dict so the caller can continue the current loop iteration
    against the updated baseline without a redundant DB round-trip.
    """
    earliest = stale_artifacts[0] if stale_artifacts else ""
    phase_map = {
        "input": PreparePhase.INPUT_ASSESSMENT,
        "requirements": PreparePhase.PLAN_DRAFTING,
        "implementation_plan": PreparePhase.PLAN_REVIEW,
    }
    stale_phase = phase_map.get(earliest, PreparePhase.INPUT_ASSESSMENT)

    writer = StateWriter(state)
    writer.state.current = stale_phase.value
    for key, filename in _ARTIFACT_CASCADE:
        if key not in stale_artifacts:
            continue
        db_name = filename.removesuffix(".md") if filename.endswith(".md") else key
        current_digest = await todos_db.artifact_digest(slug, db_name)
        entry = getattr(writer.state.artifacts, key, None)
        if isinstance(entry, ArtifactEntry) and current_digest and current_digest != entry.digest:
            entry.digest = current_digest
    payload = await writer.commit(todos_db, slug)

    _emit_prepare_event(
        "domain.software-development.prepare.artifact_invalidated",
        {"slug": slug, "stale_artifacts": stale_artifacts, "reason": "digest_mismatch"},
    )
    logger.info(
        "ARTIFACT_STALENESS slug=%s stale=%s routing_to=%s",
        slug,
        stale_artifacts,
        stale_phase.value,
    )
    return payload


async def next_prepare(db: Db, slug: str | None, cwd: str) -> str:  # pylint: disable=too-many-locals
    """Phase A state machine for collaborative architect work.

    Reads durable state from todos.db, determines the current prepare phase,
    executes the next step, and returns structured tool-call instructions for
    the orchestrator.
    """
    from teleclaude.core.next_machine.slug_resolution import (  # pylint: disable=import-outside-toplevel
        resolve_holder_children_db,
    )
    from teleclaude.core.todos_db import get_todos_db  # pylint: disable=import-outside-toplevel

    cwd = resolve_canonical_project_root(cwd)
    todos_db = await get_todos_db(cwd)

    resolved_slug = slug
    if not resolved_slug:
        resolved_slug = await _find_next_prepare_slug_db(todos_db)

    if not resolved_slug:
        guidance = await compose_agent_guidance(db)
        return format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_PREPARE_DRAFT,
                args="",
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="No active preparation work found.",
                next_call="telec todo prepare",
            )
        )

    holder_children = await resolve_holder_children_db(todos_db, resolved_slug)
    if holder_children:
        return (
            f"SPLIT FINALIZE: {resolved_slug} was split into: {', '.join(holder_children)}. "
            f"Run telec todo work {resolved_slug} to trigger finalize and integration."
        )

    if not await todos_db.slug_in_roadmap(resolved_slug):
        await todos_db.add_to_roadmap(resolved_slug)
        logger.info("AUTO_ROADMAP_ADD slug=%s machine=prepare", resolved_slug)

    # Dispatch loop
    for _iter in range(_PREPARE_LOOP_LIMIT):
        state = await todos_db.read_state(resolved_slug)
        if state is None:
            msg = f"Contract violation: no state record for slug {resolved_slug!r}"
            raise RuntimeError(msg)

        # Artifact staleness check (R6): run before routing
        stale_artifacts = await check_artifact_staleness_db(todos_db, resolved_slug)
        if stale_artifacts:
            state = await _apply_stale_artifact_reroute(todos_db, resolved_slug, state, stale_artifacts)

        # Resolve current phase from authoritative state value
        raw_current = str(state.get("current", "")).strip()
        try:
            phase = PreparePhase(raw_current)
        except ValueError:
            # Unknown phase — verify prepare is actually complete before
            # declaring PREPARED.  If plan_review lacks an approve verdict,
            # the lifecycle was skipped (e.g. a phantom value landed in
            # current).  Route back to the first incomplete gate.
            plan_review = state.get("plan_review", {})
            plan_approved = isinstance(plan_review, dict) and plan_review.get("verdict") == "approve"
            if plan_approved:
                return f"PREPARED: {resolved_slug} is past the prepare lifecycle (current={raw_current})."

            has_plan = await todos_db.artifact_exists(resolved_slug, "implementation-plan")
            if has_plan:
                recovery_writer = StateWriter(state)
                recovery_writer.state.current = PreparePhase.PLAN_REVIEW.value
                await recovery_writer.commit(todos_db, resolved_slug)
                logger.warning(
                    "PREPARE_RECOVERY: slug=%s invalid current=%s, unapproved plan_review, rerouting",
                    resolved_slug,
                    raw_current,
                )
                continue  # re-enter loop with corrected phase

            req_review = state.get("requirements_review", {})
            req_approved = isinstance(req_review, dict) and req_review.get("verdict") == "approve"
            if req_approved:
                recovery_writer = StateWriter(state)
                recovery_writer.state.current = PreparePhase.PLAN_DRAFTING.value
                await recovery_writer.commit(todos_db, resolved_slug)
                logger.warning(
                    "PREPARE_RECOVERY: slug=%s had invalid current=%s with no plan, rerouting to plan_drafting",
                    resolved_slug,
                    raw_current,
                )
                continue

            return f"PREPARED: {resolved_slug} is past the prepare lifecycle (current={raw_current})."

        logger.info(
            "NEXT_PREPARE_PHASE slug=%s phase=%s iter=%d",
            resolved_slug,
            phase.value,
            _iter,
        )

        keep_going, instruction = await _prepare_dispatch(
            db=db, todos_db=todos_db, slug=resolved_slug, cwd=cwd, phase=phase, state=state
        )
        if not keep_going:
            return instruction

    return (
        f"LOOP_LIMIT: prepare state machine for {resolved_slug} exceeded "
        f"{_PREPARE_LOOP_LIMIT} internal transitions. "
        f"Inspect state for {resolved_slug} for stuck state."
    )


__all__ = ["next_prepare"]
