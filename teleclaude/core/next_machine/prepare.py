"""Prepare stage — Phase A dispatcher.

Reads the canonical ``lifecycle_phase`` from persisted state and dispatches the
current prepare step. It never derives or advances lifecycle state on its own.

Review fix loops preserve the peer-conversation contract: "send fixer and
reviewer session IDs to each other with --direct to let them iterate without
context-destroying churn."
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import _PREPARE_LOOP_LIMIT
from teleclaude.core.next_machine.git_ops import _merge_origin_main_into_worktree, compose_agent_guidance
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    adopt_prepare_handoff_phase,
    is_work_lifecycle_phase,
    require_lifecycle_phase,
)
from teleclaude.core.next_machine.output_formatting import ToolCallRequest, format_tool_call
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
    ("input", "input"),
    ("requirements", "requirements"),
    ("test_specs", "test-specs"),
    ("implementation_plan", "implementation-plan"),
)


# Phase satisfaction walk — ordered list of (phase, gate-check) pairs. Each gate
# answers "is this phase still satisfied given current artifact digests?" Returns
# False when a rewind is needed. The walk dispatches the earliest unsatisfied
# phase, so a downstream rewind only fires once the upstream is back to satisfied.
_SATISFACTION_ORDER: tuple[str, ...] = (
    "requirements_review",
    "test_spec_build",
    "test_spec_review",
    "plan_drafting",
    "plan_review",
)


def _as_dict(value: object) -> dict[str, StateValue]:
    """Return value if it is a dict, otherwise an empty dict."""
    return value if isinstance(value, dict) else {}


def _review_approved_against(state: dict[str, StateValue], review_key: str, expected_digest: str) -> bool:
    """True when a review verdict is approve AND its approved_digest matches the expected digest."""
    review = _as_dict(state.get(review_key))
    if review.get("verdict") != "approve":
        return True  # not yet reviewed — not a rewind condition
    return review.get("approved_digest", "") == expected_digest


def _build_phase_fresh(
    state: dict[str, StateValue], artifact_key: str, upstream_key: str, current_digests: dict[str, str]
) -> bool:
    """True when a built artifact's recorded upstream digest matches the current upstream digest."""
    artifacts = _as_dict(state.get("artifacts"))
    entry = _as_dict(artifacts.get(artifact_key))
    if not entry.get("produced_at"):
        return True
    upstream = _as_dict(entry.get("upstream_digests"))
    return upstream.get(upstream_key, "") == current_digests.get(upstream_key, "")


def _plan_drafting_fresh(state: dict[str, StateValue], current_digests: dict[str, str]) -> bool:
    """True when the plan's recorded upstream digests match current requirements and test_specs."""
    artifacts = _as_dict(state.get("artifacts"))
    plan = _as_dict(artifacts.get("implementation_plan"))
    if not plan.get("produced_at"):
        return True
    upstream = _as_dict(plan.get("upstream_digests"))
    if upstream.get("requirements", "") != current_digests.get("requirements", ""):
        return False
    current_specs_digest = current_digests.get("test_specs", "")
    if current_specs_digest and upstream.get("test_specs", "") != current_specs_digest:
        return False
    return True


def _phase_satisfied(phase: str, state: dict[str, StateValue], current_digests: dict[str, str]) -> bool:
    """Return True when the given phase's stamped state matches current artifact digests."""
    if phase == "requirements_review":
        return _review_approved_against(state, "requirements_review", current_digests.get("requirements", ""))
    if phase == "test_spec_build":
        return _build_phase_fresh(state, "test_specs", "requirements", current_digests)
    if phase == "test_spec_review":
        return _review_approved_against(state, "test_spec_review", current_digests.get("test_specs", ""))
    if phase == "plan_drafting":
        return _plan_drafting_fresh(state, current_digests)
    if phase == "plan_review":
        return _review_approved_against(state, "plan_review", current_digests.get("implementation_plan", ""))
    return True


async def detect_unsatisfied_phase(todos_db: TodosDb, slug: str, state: dict[str, StateValue]) -> LifecyclePhase | None:
    """Walk the prepare phases and return the earliest unsatisfied phase, or None.

    A phase is unsatisfied when its stamped digest binding does not match the
    current artifact content digest. The earliest unsatisfied phase is where the
    machine should rewind to; everything downstream re-validates from there.
    """
    current_digests = {
        "requirements": await todos_db.artifact_digest(slug, "requirements"),
        "test_specs": await todos_db.artifact_digest(slug, "test-specs"),
        "implementation_plan": await todos_db.artifact_digest(slug, "implementation-plan"),
    }
    for phase in _SATISFACTION_ORDER:
        if not _phase_satisfied(phase, state, current_digests):
            return LifecyclePhase(phase)
    return None


async def _hydrate_artifact_presence_for_adoption(
    todos_db: TodosDb,
    slug: str,
    writer: StateWriter,
) -> None:
    """Load current artifact presence into state before draft handoff adoption."""
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
        if state is None:
            continue
        item_phase = state.get("phase")
        if item_phase == "done":
            continue
        lifecycle = require_lifecycle_phase(state.get("lifecycle_phase"), context=f"_find_next_prepare_slug_db({slug})")
        if lifecycle == LifecyclePhase.DRAFT:
            continue
        if lifecycle != LifecyclePhase.PREPARED and not is_work_lifecycle_phase(lifecycle):
            return slug
    return None


async def next_prepare(db: Db, slug: str | None, cwd: str) -> str:
    """Dispatch the current prepare lifecycle step from authoritative state."""
    # Silence unused-import warnings for the helpers re-exported here.
    _ = _commit_writer

    cwd = str(resolve_state_root(cwd))
    todos_db = await get_todos_db(cwd)

    resolved_slug = slug
    if not resolved_slug:
        resolved_slug = await _find_next_prepare_slug_db(todos_db)

    if resolved_slug:
        _draft_state = await todos_db.read_state(resolved_slug)
        _draft_lifecycle = (
            require_lifecycle_phase(_draft_state.get("lifecycle_phase"), context=f"next_prepare({resolved_slug})")
            if isinstance(_draft_state, dict)
            else None
        )
        if _draft_lifecycle == LifecyclePhase.DRAFT:
            draft_writer = StateWriter(_draft_state)
            await _hydrate_artifact_presence_for_adoption(todos_db, resolved_slug, draft_writer)
            adopted = adopt_prepare_handoff_phase(draft_writer.state)
            draft_writer.state.lifecycle_phase = adopted.value
            await draft_writer.commit(todos_db, resolved_slug)

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

    # Merge origin/main into the worktree (if it exists) so the grounding
    # check sees files that landed from other deliveries. Mirrors the same
    # pattern used by the work machine (work.py).
    worktree_path = Path(cwd) / WORKTREE_DIR / resolved_slug
    if worktree_path.is_dir():
        merge_err = await asyncio.to_thread(_merge_origin_main_into_worktree, str(worktree_path), resolved_slug)
        if merge_err:
            logger.warning("PREPARE_MERGE_MAIN slug=%s error=%s", resolved_slug, merge_err)

    for _iter in range(_PREPARE_LOOP_LIMIT):
        state = await todos_db.read_state(resolved_slug)
        if state is None:
            msg = f"Contract violation: no state record for slug {resolved_slug!r}"
            raise RuntimeError(msg)

        writer = StateWriter(state)
        # Digest-driven rewind: if any phase's stamped digest no longer matches
        # the current artifact content, walk back to the earliest unsatisfied
        # phase. This makes the machine self-healing when the human edits an
        # artifact after approval.
        rewind_to = await detect_unsatisfied_phase(todos_db, resolved_slug, state)
        if rewind_to is not None and rewind_to.value != writer.state.lifecycle_phase:
            logger.info(
                "NEXT_PREPARE_REWIND slug=%s from=%s to=%s",
                resolved_slug,
                writer.state.lifecycle_phase,
                rewind_to.value,
            )
            writer.state.lifecycle_phase = rewind_to.value
            await writer.commit(todos_db, resolved_slug)
            state = await todos_db.read_state(resolved_slug)
            if state is None:
                msg = f"Contract violation: state disappeared after rewind for slug {resolved_slug!r}"
                raise RuntimeError(msg)
            writer = StateWriter(state)

        lifecycle = require_lifecycle_phase(writer.state.lifecycle_phase, context=f"next_prepare({resolved_slug})")
        if lifecycle == LifecyclePhase.PREPARED or is_work_lifecycle_phase(lifecycle):
            phase = _PP.PREPARED
        else:
            phase = _PP(lifecycle.value)
        logger.info(
            "NEXT_PREPARE_PHASE slug=%s phase=%s iter=%d",
            resolved_slug,
            phase.value,
            _iter,
        )

        keep_going, instruction = await _prepare_dispatch(
            db=db,
            todos_db=todos_db,
            slug=resolved_slug,
            cwd=cwd,
            phase=_PP(phase.value),
            state=state,
        )
        if not keep_going:
            return instruction

    return (
        f"LOOP_LIMIT: prepare state machine for {resolved_slug} exceeded "
        f"{_PREPARE_LOOP_LIMIT} internal transitions. "
        f"Inspect state for {resolved_slug} for stuck state."
    )


__all__ = ["next_prepare"]
