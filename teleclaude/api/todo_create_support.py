"""Create-route helpers for the todo workflow endpoints.

Houses the cohesive sub-behaviors of ``todo_content_create`` that would
otherwise inflate the route module: currently the ``--plan`` seeding step that
turns a supplied implementation-plan into a plan-drafting seed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.core.next_machine.lifecycle import adopt_prepare_handoff_phase
from teleclaude.core.next_machine.state_mutation import StateWriter

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


async def seed_plan_drafting(todos_db: TodosDb, slug: str, *, repo_root: str) -> str:
    """Mark a supplied ``--plan`` implementation-plan as a plan-drafting seed.

    A supplied plan is an unverified draft basis, not an approved artifact: set
    the implementation-plan entry's ``seeded`` flag so phase derivation holds it
    in ``plan_drafting`` for a full plan-draft pass (grounding, blast radius, doc
    reflection) before plan-review, instead of bypassing prepare. Must run AFTER
    the seeding write's provenance sync, which runs ``_clear_rewrite_drift_state``
    and would otherwise wipe the flag. Returns the derived ``lifecycle_phase``.
    """
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        msg = f"Todo state missing after --plan creation for {slug!r}"
        raise RuntimeError(msg)
    writer = StateWriter(raw_state)
    writer.state.artifacts.implementation_plan.seeded = True
    phase = adopt_prepare_handoff_phase(writer.state, repo_root=repo_root)
    writer.state.lifecycle_phase = phase.value
    await writer.commit(todos_db, slug)
    return phase.value
