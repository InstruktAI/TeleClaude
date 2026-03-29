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
from teleclaude.core.next_machine.prepare_helpers import _ARTIFACT_CASCADE, check_artifact_staleness_db
from teleclaude.core.next_machine.prepare_steps import _prepare_dispatch, _restamp_artifact_digest_db
from teleclaude.core.next_machine.slug_resolution import (
    resolve_canonical_project_root,
)

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)


async def _apply_stale_artifact_reroute(
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
    stale_artifacts: list[str],
) -> None:
    """Reset prepare routing when tracked artifacts have gone stale.

    Restamps all stale artifact digests to match current DB content before
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
    for key, _filename in _ARTIFACT_CASCADE:
        if key in stale_artifacts:
            await _restamp_artifact_digest_db(todos_db, state, slug, key)
    await todos_db.write_state(slug, state)
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


async def next_prepare(db: Db, slug: str | None, cwd: str) -> str:  # pylint: disable=too-many-locals
    """Phase A state machine for collaborative architect work.

    Reads durable state from todos.db, determines the current prepare phase,
    executes the next step, and returns structured tool-call instructions for
    the orchestrator.
    """
    from teleclaude.core.next_machine.slug_resolution import (  # pylint: disable=import-outside-toplevel
        _find_next_prepare_slug,
        resolve_holder_children,
    )
    from teleclaude.core.todos_db import get_todos_db  # pylint: disable=import-outside-toplevel

    cwd = resolve_canonical_project_root(cwd)
    todos_db = await get_todos_db(cwd)

    resolved_slug = slug
    if not resolved_slug:
        resolved_slug = _find_next_prepare_slug(cwd)

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

    holder_children = resolve_holder_children(cwd, resolved_slug)
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
            state = {}

        # Artifact staleness check (R6): run before routing
        stale_artifacts = await check_artifact_staleness_db(todos_db, resolved_slug)
        if stale_artifacts:
            await _apply_stale_artifact_reroute(todos_db, resolved_slug, state, stale_artifacts)

        # Resolve current phase from authoritative state value
        raw_current = str(state.get("current", "")).strip()
        try:
            phase = PreparePhase(raw_current)
        except ValueError:
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
