"""Seeding a filed todo's supplied plan: a plan-drafting basis for a change, a pre-authorized task-plan for a task."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.core.next_machine.artifacts import read_artifact_write_timestamps
from teleclaude.core.next_machine.lifecycle import adopt_prepare_handoff_phase
from teleclaude.core.next_machine.state_mutation import ApprovalsManager, StateWriter

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore


async def seed_plan_drafting(todos_db: WorkflowStore, slug: str, *, repo_root: str) -> str:
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
    artifact_write_timestamps = await read_artifact_write_timestamps(todos_db, slug)
    phase = adopt_prepare_handoff_phase(
        writer.state,
        repo_root=repo_root,
        report_digests={},
        artifact_write_timestamps=artifact_write_timestamps,
    )
    writer.state.lifecycle_phase = phase
    await writer.commit(todos_db, slug)
    return phase.value


async def seed_task_plan_authorization(
    todos_db: WorkflowStore,
    slug: str,
    *,
    caller_session_id: str,
    prepared_session_id: str | None,
) -> str:
    """Mark a supplied ``--kind task --plan`` task-plan as pre-authorized."""
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        msg = f"Todo state missing after --kind task --plan creation for {slug!r}"
        raise RuntimeError(msg)
    writer = StateWriter(raw_state)
    artifact_write_timestamps = await read_artifact_write_timestamps(todos_db, slug)
    phase = adopt_prepare_handoff_phase(
        writer.state,
        report_digests={},
        artifact_write_timestamps=artifact_write_timestamps,
        prepared_session_id=prepared_session_id,
    )
    writer.state.lifecycle_phase = phase
    ApprovalsManager(writer).approve(
        "task_approved",
        caller_session_id=caller_session_id,
        approved_digest=writer.state.artifacts.task_plan.digest,
    )
    await writer.commit(todos_db, slug)
    return phase.value
