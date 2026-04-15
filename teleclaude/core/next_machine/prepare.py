"""Prepare stage — Phase A state machine for collaborative architect work.

Each loop iteration re-derives :class:`PreparePhase` from the state primitives
(stamped verdicts, DOR score, artifact presence, grounding validity) via
:func:`derive_prepare_phase`, then routes through :func:`_prepare_dispatch`.
No persistent ``current`` value, no mark-phase calls.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import _PREPARE_LOOP_LIMIT, StateValue
from teleclaude.core.next_machine.git_ops import compose_agent_guidance
from teleclaude.core.next_machine.output_formatting import ToolCallRequest, format_tool_call
from teleclaude.core.next_machine.phase_derivation import derive_prepare_phase
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.prepare_helpers import (
    _ARTIFACT_CASCADE,
    check_artifact_staleness_db,
)
from teleclaude.core.next_machine.prepare_steps import _commit_writer, _prepare_dispatch
from teleclaude.core.next_machine.slug_resolution import (
    resolve_canonical_project_root,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.types.todos import ArtifactEntry

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)


async def _find_next_prepare_slug_db(todos_db: TodosDb) -> str | None:
    """Find next slug needing preparation by deriving phase from primitives.

    Returns the first roadmap entry whose derived prepare phase is not PREPARED
    (i.e., still has prepare work remaining). Skips items already marked done.
    """
    from teleclaude.core.next_machine._types import PreparePhase as _PP  # pylint: disable=import-outside-toplevel

    entries = await todos_db.list_roadmap()
    for entry in entries:
        slug = entry["slug"]
        state = await todos_db.read_state(slug)
        if state is None:
            continue
        item_phase = state.get("phase")
        if item_phase == "done":
            continue
        derived = await derive_prepare_phase(state, todos_db, slug)
        if derived != _PP.PREPARED:
            return slug
    return None


async def _apply_stale_artifact_reroute(
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
    stale_artifacts: list[str],
) -> dict[str, StateValue]:
    """Refresh digests for stale artifacts and invalidate downstream review verdicts.

    A stale artifact means the DB-stored content diverged from the stamped
    digest. After restamping the current digest the loop re-derives the
    phase, but derivation still has to see a reason to re-route — otherwise
    we'd advance through an already-approved downstream review against
    potentially outdated content. We clear the downstream review verdicts
    (requirements → test specs → plan) so derivation lands back on the first
    stale review phase.
    """
    downstream_map = {
        "input": ("requirements_review", "test_spec_review", "plan_review"),
        "requirements": ("test_spec_review", "plan_review"),
        "implementation_plan": ("plan_review",),
    }

    writer = StateWriter(state)
    for key, artifact_name in _ARTIFACT_CASCADE:
        if key not in stale_artifacts:
            continue
        current_digest = await todos_db.artifact_digest(slug, artifact_name)
        entry = getattr(writer.state.artifacts, key, None)
        if isinstance(entry, ArtifactEntry) and current_digest and current_digest != entry.digest:
            entry.digest = current_digest
        for review_key in downstream_map.get(key, ()):
            review = getattr(writer.state, review_key, None)
            if review is not None and getattr(review, "verdict", "") == "approve":
                review.verdict = ""

    payload = await writer.commit(todos_db, slug)
    state.clear()
    state.update(payload)

    _emit_prepare_event(
        "domain.software-development.prepare.artifact_invalidated",
        {"slug": slug, "stale_artifacts": stale_artifacts, "reason": "digest_mismatch"},
    )
    logger.info(
        "ARTIFACT_STALENESS slug=%s stale=%s routing_to=derive",
        slug,
        stale_artifacts,
    )
    return state


async def next_prepare(db: Db, slug: str | None, cwd: str) -> str:  # pylint: disable=too-many-locals
    """Phase A state machine for collaborative architect work.

    Reads durable state from todos.db, derives the current prepare phase via
    :func:`derive_prepare_phase` on every iteration, executes the next step,
    and returns structured tool-call instructions for the orchestrator.
    """
    from teleclaude.core.next_machine.slug_resolution import (  # pylint: disable=import-outside-toplevel
        resolve_holder_children_db,
    )
    from teleclaude.core.todos_db import get_todos_db  # pylint: disable=import-outside-toplevel

    # Silence unused-import warnings for the helpers re-exported here.
    _ = _commit_writer

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

    for _iter in range(_PREPARE_LOOP_LIMIT):
        state = await todos_db.read_state(resolved_slug)
        if state is None:
            msg = f"Contract violation: no state record for slug {resolved_slug!r}"
            raise RuntimeError(msg)

        stale_artifacts = await check_artifact_staleness_db(todos_db, resolved_slug)
        if stale_artifacts:
            state = await _apply_stale_artifact_reroute(todos_db, resolved_slug, state, stale_artifacts)

        phase = await derive_prepare_phase(state, todos_db, resolved_slug)
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
