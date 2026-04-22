"""Prepare stage — Phase A dispatcher.

Reads the canonical ``lifecycle_phase`` from persisted state and dispatches the
current prepare step. It never derives or advances lifecycle state on its own.
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
    is_work_lifecycle_phase,
    require_lifecycle_phase,
)
from teleclaude.core.next_machine.output_formatting import ToolCallRequest, format_tool_call
from teleclaude.core.next_machine.prepare_steps import _commit_writer, _prepare_dispatch
from teleclaude.core.next_machine.slug_resolution import resolve_canonical_project_root
from teleclaude.core.next_machine.state_mutation import StateWriter

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb
from teleclaude.core.next_machine._types import PreparePhase as _PP
from teleclaude.core.next_machine.slug_resolution import resolve_holder_children_db
from teleclaude.core.todos_db import get_todos_db

logger = get_logger(__name__)


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

    cwd = resolve_canonical_project_root(cwd)
    todos_db = await get_todos_db(cwd)

    resolved_slug = slug
    if not resolved_slug:
        resolved_slug = await _find_next_prepare_slug_db(todos_db)

    # Draft todos bypass the lifecycle entirely — reject even explicit prepare calls.
    if resolved_slug:
        _draft_state = await todos_db.read_state(resolved_slug)
        _draft_lifecycle = (
            require_lifecycle_phase(_draft_state.get("lifecycle_phase"), context=f"next_prepare({resolved_slug})")
            if isinstance(_draft_state, dict)
            else None
        )
        if _draft_lifecycle == LifecyclePhase.DRAFT:
            resolved_slug = None

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
