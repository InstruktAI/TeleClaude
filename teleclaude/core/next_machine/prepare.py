"""Prepare stage — Phase A state machine for collaborative architect work.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio

from instrukt_ai_logging import get_logger

from teleclaude.constants import SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import _PREPARE_LOOP_LIMIT, PreparePhase, StateValue
from teleclaude.core.next_machine.git_ops import compose_agent_guidance
from teleclaude.core.next_machine.output_formatting import ToolCallRequest, format_tool_call
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.prepare_helpers import _ARTIFACT_CASCADE, check_artifact_staleness
from teleclaude.core.next_machine.prepare_steps import _prepare_dispatch, _restamp_artifact_digest
from teleclaude.core.next_machine.roadmap import add_to_roadmap, slug_in_roadmap
from teleclaude.core.next_machine.slug_resolution import (
    _find_next_prepare_slug,
    resolve_canonical_project_root,
    resolve_holder_children,
)
from teleclaude.core.next_machine.state_io import _resolve_state_cwd, read_phase_state, write_phase_state

logger = get_logger(__name__)


async def _apply_stale_artifact_reroute(
    cwd: str,
    slug: str,
    state: dict[str, StateValue],
    stale_artifacts: list[str],
) -> None:
    """Reset prepare routing when tracked artifacts have gone stale.

    Restamps all stale artifact digests to match current file content before
    writing state. Without this, the staleness check fires again on the next
    loop iteration and the machine never escapes the reroute.
    """
    earliest = stale_artifacts[0] if stale_artifacts else ""
    phase_map = {
        "input": PreparePhase.INPUT_ASSESSMENT,
        "requirements": PreparePhase.PLAN_DRAFTING,
        "implementation_plan": PreparePhase.PLAN_REVIEW,
    }
    stale_phase = phase_map.get(earliest, PreparePhase.INPUT_ASSESSMENT)
    state["current"] = stale_phase.value
    for key, filename in _ARTIFACT_CASCADE:
        if key in stale_artifacts:
            _restamp_artifact_digest(state, cwd, slug, key, filename)
    await asyncio.to_thread(write_phase_state, cwd, slug, state)
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


async def next_prepare(db: Db, slug: str | None, cwd: str) -> str:
    """Phase A state machine for collaborative architect work.

    Reads durable state from state.yaml, determines the current prepare phase,
    executes the next step, and returns structured tool-call instructions for
    the orchestrator.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from roadmap if not provided)
        cwd: Current working directory (project root)

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    # Canonicalize cwd so worktree paths resolve to the project root.
    # Without this, an orchestrator that cd's into a worktree would cause
    # all file lookups (roadmap, state, artifacts) to hit the wrong directory.
    cwd = await asyncio.to_thread(resolve_canonical_project_root, cwd)

    # Pre-dispatch preconditions: slug resolution, roadmap validation, container detection
    resolved_slug = slug
    if not resolved_slug:
        resolved_slug = await asyncio.to_thread(_find_next_prepare_slug, cwd)

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

    holder_children = await asyncio.to_thread(resolve_holder_children, cwd, resolved_slug)
    if holder_children:
        # Container items (split holders) do not have worktrees, so mark_phase("finalize_ready")
        # cannot run here — its on_enter handler requires a worktree. The work machine handles
        # finalization routing for container items.
        return (
            f"SPLIT FINALIZE: {resolved_slug} was split into: {', '.join(holder_children)}. "
            f"Run telec todo work {resolved_slug} to trigger finalize and integration."
        )

    if not await asyncio.to_thread(slug_in_roadmap, cwd, resolved_slug):
        await asyncio.to_thread(add_to_roadmap, cwd, resolved_slug)
        logger.info("AUTO_ROADMAP_ADD slug=%s machine=prepare", resolved_slug)

    # Dispatch loop
    for _iter in range(_PREPARE_LOOP_LIMIT):
        # Resolve effective cwd: worktree if it exists, project root otherwise.
        # Computed per iteration because the first step may create the worktree.
        effective_cwd = _resolve_state_cwd(cwd, resolved_slug)

        state = await asyncio.to_thread(read_phase_state, effective_cwd, resolved_slug)

        # Artifact staleness check (R6): run before routing
        stale_artifacts = await asyncio.to_thread(check_artifact_staleness, effective_cwd, resolved_slug)
        if stale_artifacts:
            await _apply_stale_artifact_reroute(effective_cwd, resolved_slug, state, stale_artifacts)

        # Resolve current phase from authoritative state value
        raw_current = str(state.get("current", "")).strip()
        try:
            phase = PreparePhase(raw_current)
        except ValueError:
            # current is a work-phase state (build_started, etc.) — prepare is done
            return f"PREPARED: {resolved_slug} is past the prepare lifecycle (current={raw_current})."

        logger.info(
            "NEXT_PREPARE_PHASE slug=%s phase=%s iter=%d",
            resolved_slug,
            phase.value,
            _iter,
        )

        keep_going, instruction = await _prepare_dispatch(
            db=db, slug=resolved_slug, cwd=effective_cwd, phase=phase, state=state
        )
        if not keep_going:
            return instruction

    return (
        f"LOOP_LIMIT: prepare state machine for {resolved_slug} exceeded "
        f"{_PREPARE_LOOP_LIMIT} internal transitions. "
        f"Inspect todos/{resolved_slug}/state.yaml current for stuck state."
    )


__all__ = ["next_prepare"]
