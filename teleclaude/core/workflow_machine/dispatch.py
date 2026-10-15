"""The platform's creative dispatch of a holder's handoff: start the creative orchestrator, once, by an exact identity.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (the creative capabilities, row 6): the dispatch
completes idempotently after the sweep found nothing and before the claim is released. The creative lane already has an
owner, the creative orchestrator (``creative/procedure/creative-orchestration``): it drives the creative state machine,
dispatches the lane's workers, parks at the human gates and ends the lane's sessions when the design is complete. The
handoff reaches that capability by starting it, whoever the holder was; the holder does not continue the lane and has no
parent to be told. The session's identity is derived from the durable effect and the owning project, so the start is
exact wherever it is interrupted: a session of that identity, open or already ended, is the dispatch, and nothing is
started twice. The start runs in process, under the platform's own identity, through the one session-run path.
"""

from __future__ import annotations

from dataclasses import dataclass

from teleclaude.core.db import db
from teleclaude.events.envelope import occurrence_id
from teleclaude.types.claim_change import workflow_record_of
from teleclaude.types.workflow_record import EffectKind, WorkflowRecord

ORCHESTRATOR_IDENTITY = "creative-orchestrator"
RECIPIENT_PARAM = "session_id"


@dataclass(frozen=True)
class OrchestratorSpec:
    """The creative orchestrator a handoff starts: the item it works on and the project it lives in."""

    command: str
    slug: str
    project_root: str


def orchestrator_session_id(project_root: str, todo_id: str, effect_id: str) -> str:
    """The identity of the orchestrator session of one handoff effect."""
    return occurrence_id(project_root, todo_id, effect_id, ORCHESTRATOR_IDENTITY)


async def start_orchestrator(spec: OrchestratorSpec, session_id: str) -> str:
    """Start the creative orchestrator under ``session_id`` unless that session already exists; return its identity."""
    from teleclaude.api.sessions_actions_routes import (  # noqa: PLC0415 - deferred cycle: the routes read this package
        platform_run_matches,
        run_platform_session,
    )
    from teleclaude.api_models import RunSessionRequest  # noqa: PLC0415 - deferred cycle: the models read this package

    request = RunSessionRequest(command=spec.command, args=spec.slug, project=spec.project_root, detach=True)
    try:
        await run_platform_session(request, session_id=session_id)
    except Exception:
        existing = await db.get_session(session_id)
        if existing is None or not platform_run_matches(existing, request):
            raise
    return session_id


def accepted_orchestrators(project_root: str, todo_id: str, record: WorkflowRecord) -> set[str]:
    """The creative orchestrators the item's handoffs have accepted: the recorded ones and the ones about to be.

    A pending dispatch effect already fixes the identity of the session it starts, so the orchestrator is known to the
    item before the effect records it, and before the claim is released.
    """
    pending = {
        orchestrator_session_id(project_root, todo_id, effect.id)
        for effect in record.pending_effects
        if effect.kind is EffectKind.CREATIVE_DISPATCH
    }
    return pending | set(record.dispatch_workers)


async def holds_handoff_authority(project_root: str, slug: str, session_id: str) -> bool:
    """Whether ``session_id`` is the creative orchestrator a pending handoff of the item's current holder will start.

    The authority is exact and durable: a pending ``creative_dispatch`` effect of the item fixes the identity of the one
    session it starts, and was committed by the holder\'s own handoff, so the holder is the effect\'s recipient. Only that
    session, started while that holder still holds the item, is exempt from the duplicate-driver refusal; any other
    creative orchestrator for the item is refused as before.
    """
    from teleclaude.core.workflow_store.store import get_workflow_store  # noqa: PLC0415 - the store reads this package

    store = await get_workflow_store(project_root)
    todo_id = store.resolve_store_address_sync(slug)
    raw = await store.read_state(slug)
    if todo_id is None or raw is None:
        return False
    record = workflow_record_of(raw)
    holder = str(raw.get("active_runner") or "")
    for effect in record.pending_effects:
        if (
            effect.kind is EffectKind.CREATIVE_DISPATCH
            and effect.params.get(RECIPIENT_PARAM) == holder
            and orchestrator_session_id(str(store.project_root), todo_id, effect.id) == session_id
        ):
            return True
    return False
