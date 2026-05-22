"""Prepare stage — Phase A dispatcher."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS,
)
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import _PREPARE_LOOP_LIMIT
from teleclaude.core.next_machine.git_ops import compose_agent_guidance
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    LifecycleStage,
    adopt_prepare_handoff_phase,
    is_work_lifecycle_phase,
    reconcile_lifecycle_phase,
    require_lifecycle_phase,
)
from teleclaude.core.next_machine.output_formatting import format_blocker_resolution
from teleclaude.core.next_machine.prepare_steps import _commit_writer, _prepare_dispatch
from teleclaude.core.next_machine.provenance import sync_artifact_provenance
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.project_root import resolve_state_root
from teleclaude.snippet_validation import snippet_body_digest
from teleclaude.types.state_value import StateValue

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

from teleclaude.core.next_machine._types import PreparePhase as _PP
from teleclaude.core.next_machine.slug_resolution import (
    HolderResolutionMode,
    HolderResolutionReason,
    resolve_runnable_holder_children_db,
)
from teleclaude.core.todos_db import get_todos_db

logger = get_logger(__name__)

_ADOPTION_ARTIFACTS: tuple[tuple[str, str], ...] = (
    (STATE_KEY_INPUT, ARTIFACT_INPUT),
    (STATE_KEY_PRD, ARTIFACT_PRD),
    (STATE_KEY_REQUIREMENTS, ARTIFACT_REQUIREMENTS),
    (STATE_KEY_ARCHITECTURE, ARTIFACT_ARCHITECTURE),
    (STATE_KEY_IMPLEMENTATION_PLAN, ARTIFACT_IMPLEMENTATION_PLAN),
)


def _format_holder_prepare_instruction(
    holder_slug: str,
    children: tuple[str, ...],
    runnable: tuple[str, ...],
    reason: HolderResolutionReason,
) -> str:
    """Return the next prepare action for a holder entrypoint."""
    if runnable:
        commands = "\n".join(f"telec todo prepare {child}" for child in runnable)
        return (
            "This slug is a split holder. The holder is not a prepare/work target.\n"
            "Run prepare on these direct child todos:\n"
            f"{commands}"
        )
    if reason is HolderResolutionReason.COMPLETE:
        return f"All direct children for '{holder_slug}' are delivered. No prepare work remains."
    if reason is HolderResolutionReason.ALL_PREPARED:
        return (
            f"All direct children for '{holder_slug}' are already prepared or in work. "
            f"Run `telec todo work {holder_slug}` to resolve child work."
        )
    if reason is HolderResolutionReason.DEPS_UNSATISFIED:
        return (
            f"Holder '{holder_slug}' has direct children, but none are prepare-runnable because "
            "their dependencies are not delivered yet."
        )
    if reason is HolderResolutionReason.CHILDREN_NOT_IN_ROADMAP:
        return f"Holder '{holder_slug}' has child todos, but none are active roadmap entries."
    return (
        f"Holder '{holder_slug}' has direct children, but none are currently prepare-runnable. "
        f"Children: {', '.join(children)}"
    )


async def _hydrate_artifact_presence_for_adoption(
    todos_db: TodosDb,
    slug: str,
    writer: StateWriter,
    *,
    repo_root: str,
) -> None:
    """Load current artifact presence into state before handoff adoption."""
    for state_key, artifact_name in _ADOPTION_ARTIFACTS:
        entry = getattr(writer.state.artifacts, state_key)
        if entry.digest and entry.async_provenance_complete:
            continue
        if not await todos_db.artifact_exists(slug, artifact_name):
            continue
        artifact_body = await todos_db.read_artifact(slug, artifact_name)
        await sync_artifact_provenance(
            todos_db,
            writer,
            slug,
            artifact_name,
            repo_root=repo_root,
            artifact_body=artifact_body,
            snippet_digest_fn=snippet_body_digest,
        )


async def _find_next_prepare_slug_db(todos_db: TodosDb) -> str | None:
    """Find the first roadmap entry still in the prepare lane."""
    entries = await todos_db.list_roadmap()
    for entry in entries:
        slug = entry["slug"]
        state = await todos_db.read_state(slug)
        if state is None or state.get("phase") == "done":
            continue
        lifecycle = require_lifecycle_phase(state.get("lifecycle_phase"), context=f"_find_next_prepare_slug_db({slug})")
        if lifecycle != LifecyclePhase.PREPARED and not is_work_lifecycle_phase(lifecycle):
            return slug
    return None


async def _adopt_prepare_phase(
    todos_db: TodosDb,
    slug: str,
    raw_state: dict[str, StateValue],
    *,
    repo_root: str,
) -> dict[str, StateValue]:
    writer = StateWriter(raw_state)
    await _hydrate_artifact_presence_for_adoption(todos_db, slug, writer, repo_root=repo_root)
    derived = reconcile_lifecycle_phase(writer.state, stage=LifecycleStage.PREPARE, worktree_cwd=repo_root)
    if derived is None:
        derived = adopt_prepare_handoff_phase(writer.state, repo_root=repo_root)
    writer.state.lifecycle_phase = derived.value
    payload = writer.to_dict()
    if payload != raw_state:
        payload = await writer.commit(todos_db, slug)
        return payload
    return raw_state


async def next_prepare(db: Db, slug: str | None, cwd: str) -> str:
    """Dispatch the current prepare lifecycle step from authoritative state."""
    _ = _commit_writer

    cwd = str(resolve_state_root(cwd))
    todos_db = await get_todos_db(cwd)

    resolved_slug = slug or await _find_next_prepare_slug_db(todos_db)
    if not resolved_slug:
        guidance = await compose_agent_guidance(db)
        instruction = (
            f"1. Create a new todo: `telec todo create <slug>` (use --kind feature|bug|refactor|migration|prepped).\n"
            f"2. Or pick an existing slug from `telec roadmap list`.\n"
            f"3. Then call `telec todo prepare <slug>` to drive the lifecycle.\n\n"
            f"{guidance}"
        )
        return format_blocker_resolution(
            "",
            instruction,
            blockers=["no active preparation work found"],
        )

    holder_resolution = await resolve_runnable_holder_children_db(
        todos_db,
        resolved_slug,
        await todos_db.load_deps(),
        mode=HolderResolutionMode.PREPARE,
    )
    if holder_resolution.children:
        instruction = _format_holder_prepare_instruction(
            resolved_slug,
            holder_resolution.children,
            holder_resolution.runnable,
            holder_resolution.reason,
        )
        return format_blocker_resolution(
            resolved_slug,
            instruction,
            blockers=[f"split holder has children: {', '.join(holder_resolution.children)}"],
        )

    if not await todos_db.slug_in_roadmap(resolved_slug):
        await todos_db.add_to_roadmap(resolved_slug)
        logger.info("AUTO_ROADMAP_ADD slug=%s machine=prepare", resolved_slug)

    for iteration in range(_PREPARE_LOOP_LIMIT):
        state = await todos_db.read_state(resolved_slug)
        if state is None:
            raise RuntimeError(f"Contract violation: no state record for slug {resolved_slug!r}")

        state = await _adopt_prepare_phase(todos_db, resolved_slug, state, repo_root=cwd)
        writer = StateWriter(state)
        lifecycle = require_lifecycle_phase(writer.state.lifecycle_phase, context=f"next_prepare({resolved_slug})")
        phase = (
            _PP.PREPARED
            if lifecycle == LifecyclePhase.PREPARED or is_work_lifecycle_phase(lifecycle)
            else _PP(lifecycle.value)
        )
        logger.info("NEXT_PREPARE_PHASE slug=%s phase=%s iter=%d", resolved_slug, phase.value, iteration)

        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug=resolved_slug,
            cwd=cwd,
            phase=phase,
            state=state,
        )
        if not keep_going:
            return instruction

    instruction = (
        "The prepare state machine could not converge. Inspect the todo state "
        f"via `telec todo show {resolved_slug}` and surface to the user — the lifecycle "
        "cannot self-resolve."
    )
    return format_blocker_resolution(
        resolved_slug,
        instruction,
        blockers=[f"prepare loop exceeded {_PREPARE_LOOP_LIMIT} internal transitions"],
    )


__all__ = ["next_prepare"]
