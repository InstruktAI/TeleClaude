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
    ARTIFACT_TEST_SPECS,
    SlashCommand,
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
from teleclaude.core.next_machine.output_formatting import PrepareRecommendation, format_prepare_recommendation
from teleclaude.core.next_machine.prepare_steps import _commit_writer, _prepare_dispatch
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.project_root import resolve_state_root
from teleclaude.types.state_value import StateValue

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

from teleclaude.core.next_machine._types import PreparePhase as _PP
from teleclaude.core.next_machine.slug_resolution import resolve_holder_children_db
from teleclaude.core.todos_db import get_todos_db

logger = get_logger(__name__)

_ADOPTION_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("input", ARTIFACT_INPUT),
    ("prd", ARTIFACT_PRD),
    ("requirements", ARTIFACT_REQUIREMENTS),
    ("architecture", ARTIFACT_ARCHITECTURE),
    ("test_specs", ARTIFACT_TEST_SPECS),
    ("implementation_plan", ARTIFACT_IMPLEMENTATION_PLAN),
)


async def _hydrate_artifact_presence_for_adoption(
    todos_db: TodosDb,
    slug: str,
    writer: StateWriter,
) -> None:
    """Load current artifact presence into state before handoff adoption."""
    for state_key, artifact_name in _ADOPTION_ARTIFACTS:
        entry = getattr(writer.state.artifacts, state_key)
        if entry.digest:
            continue
        if not await todos_db.artifact_exists(slug, artifact_name):
            continue
        entry.digest = await todos_db.artifact_digest(slug, artifact_name)


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
    await _hydrate_artifact_presence_for_adoption(todos_db, slug, writer)
    derived = reconcile_lifecycle_phase(writer.state, stage=LifecycleStage.PREPARE, worktree_cwd=repo_root)
    if derived is None:
        derived = adopt_prepare_handoff_phase(writer.state, repo_root=repo_root)
    if writer.state.lifecycle_phase != derived.value:
        writer.state.lifecycle_phase = derived.value
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
        payload: PrepareRecommendation = {
            "slug": "",
            "lifecycle_phase": LifecyclePhase.DRAFT.value,
            "stage": "prepare",
            "kind": "feature",
            "recommended_command": f"/{SlashCommand.NEXT_PREPARE_INTAKE.value}",
            "recommended_args": "",
            "required_reads": [],
            "drift": {},
            "blockers": ["no active preparation work found"],
            "advisory": [guidance, "Create or select a todo, then run `telec todo prepare` again."],
        }
        return format_prepare_recommendation(payload)

    holder_children = await resolve_holder_children_db(todos_db, resolved_slug)
    if holder_children:
        payload: PrepareRecommendation = {
            "slug": resolved_slug,
            "lifecycle_phase": LifecyclePhase.BLOCKED.value,
            "stage": "prepare",
            "kind": "split-holder",
            "recommended_command": "telec todo work",
            "recommended_args": resolved_slug,
            "required_reads": [],
            "drift": {},
            "blockers": [f"split holder has children: {', '.join(holder_children)}"],
            "advisory": ["Run work on the holder to trigger finalize and integration."],
        }
        return format_prepare_recommendation(payload)

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

    payload: PrepareRecommendation = {
        "slug": resolved_slug,
        "lifecycle_phase": LifecyclePhase.BLOCKED.value,
        "stage": "prepare",
        "kind": "unknown",
        "recommended_command": "",
        "recommended_args": "",
        "required_reads": [],
        "drift": {},
        "blockers": [f"prepare loop exceeded {_PREPARE_LOOP_LIMIT} internal transitions"],
        "advisory": ["Inspect state before continuing."],
    }
    return format_prepare_recommendation(payload)


__all__ = ["next_prepare"]
