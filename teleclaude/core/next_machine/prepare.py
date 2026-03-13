"""Prepare stage — Phase A state machine for collaborative architect work.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio

from instrukt_ai_logging import get_logger

from teleclaude.constants import SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import _PREPARE_LOOP_LIMIT, PreparePhase
from teleclaude.core.next_machine.git_ops import compose_agent_guidance
from teleclaude.core.next_machine.output_formatting import format_tool_call
from teleclaude.core.next_machine.prepare_events import _derive_prepare_phase, _emit_prepare_event
from teleclaude.core.next_machine.prepare_steps import _prepare_dispatch
from teleclaude.core.next_machine.roadmap import add_to_roadmap, slug_in_roadmap
from teleclaude.core.next_machine.slug_resolution import (
    _find_next_prepare_slug,
    resolve_holder_children,
)
from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state

logger = get_logger(__name__)


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
    try:
        # Pre-dispatch preconditions: slug resolution, roadmap validation, container detection
        resolved_slug = slug
        if not resolved_slug:
            resolved_slug = await asyncio.to_thread(_find_next_prepare_slug, cwd)

        if not resolved_slug:
            guidance = await compose_agent_guidance(db)
            return format_tool_call(
                command=SlashCommand.NEXT_PREPARE_DRAFT,
                args="",
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="No active preparation work found.",
                next_call="telec todo prepare",
            )

        holder_children = await asyncio.to_thread(resolve_holder_children, cwd, resolved_slug)
        if holder_children:
            return f"CONTAINER: {resolved_slug} was split into: {', '.join(holder_children)}. Work on those first."

        if not await asyncio.to_thread(slug_in_roadmap, cwd, resolved_slug):
            await asyncio.to_thread(add_to_roadmap, cwd, resolved_slug)
            logger.info("AUTO_ROADMAP_ADD slug=%s machine=prepare", resolved_slug)

        # Dispatch loop
        for _iter in range(_PREPARE_LOOP_LIMIT):
            state = await asyncio.to_thread(read_phase_state, cwd, resolved_slug)

            # Artifact staleness check (R6): run before routing
            from teleclaude.core.next_machine.prepare_helpers import (
                check_artifact_staleness,
            )

            stale_artifacts = await asyncio.to_thread(check_artifact_staleness, cwd, resolved_slug)
            if stale_artifacts:
                earliest = stale_artifacts[0] if stale_artifacts else ""
                # Map earliest stale artifact to phase to re-run
                _phase_map = {
                    "input": PreparePhase.INPUT_ASSESSMENT,
                    "requirements": PreparePhase.PLAN_DRAFTING,
                    "implementation_plan": PreparePhase.PLAN_REVIEW,
                }
                stale_phase = _phase_map.get(earliest, PreparePhase.INPUT_ASSESSMENT)
                state["prepare_phase"] = stale_phase.value
                await asyncio.to_thread(write_phase_state, cwd, resolved_slug, state)
                _emit_prepare_event(
                    "domain.software-development.prepare.artifact_invalidated",
                    {"slug": resolved_slug, "stale_artifacts": stale_artifacts, "reason": "digest_mismatch"},
                )
                logger.info(
                    "ARTIFACT_STALENESS slug=%s stale=%s routing_to=%s",
                    resolved_slug,
                    stale_artifacts,
                    stale_phase.value,
                )

            # Resolve current phase
            raw_phase = str(state.get("prepare_phase", "")).strip()
            try:
                phase = PreparePhase(raw_phase)
            except ValueError:
                # Derive phase from artifact existence for legacy todos
                phase = await asyncio.to_thread(_derive_prepare_phase, resolved_slug, cwd, state)

            logger.info(
                "NEXT_PREPARE_PHASE slug=%s phase=%s iter=%d",
                resolved_slug,
                phase.value,
                _iter,
            )

            keep_going, instruction = await _prepare_dispatch(
                db=db, slug=resolved_slug, cwd=cwd, phase=phase, state=state
            )
            if not keep_going:
                return instruction

        return (
            f"LOOP_LIMIT: prepare state machine for {resolved_slug} exceeded "
            f"{_PREPARE_LOOP_LIMIT} internal transitions. "
            f"Inspect todos/{resolved_slug}/state.yaml prepare_phase for stuck state."
        )
    except RuntimeError:
        raise


__all__ = ["next_prepare"]
