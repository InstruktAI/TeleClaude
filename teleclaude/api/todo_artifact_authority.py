"""Caller-authority resolution and write gates for todo artifact writes.

The artifact write boundary records *who* wrote (the resolved principal),
enforces the claiming-group ownership boundary (every writable artifact kind),
and, for prepare artifacts, the prepare-phase role allowlist. All three concerns
live here so the route module stays focused on request routing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity
from teleclaude.core.db import db as runtime_db
from teleclaude.core.next_machine.lanes import PREPARE_AUTHOR_ROLES
from teleclaude.core.next_machine.runtime.sessions import is_live_session_id
from teleclaude.core.session_utils import session_in_claiming_group
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.types.creation_record import HUMAN_ROOT_PREFIX, SYSTEM_ROOT_PREFIX, Lineage
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore

_FOREIGN_ARTIFACT_CLAIM_DETAIL = (
    "todo '{slug}' is claimed by session '{holder}'; write refused. "
    "Address that session about the concern instead of writing into its "
    "record (sdlc/policy/todo-creation-discipline, "
    "'Reconcile a flagged live todo')."
)
_FOREIGN_UPDATE_CLAIM_DETAIL = (
    "todo '{slug}' is claimed by session '{holder}'; update refused. "
    "Address that session about the concern instead of updating its todo."
)


def resolved_write_principal(identity: CallerIdentity) -> str | None:
    """Resolve the session id recorded as an artifact's ``updated_by``.

    A session write is recorded under that session's id. An identified caller
    that is no session authors under no session and records nothing; the todo's
    own creation record carries who it ran under. Caller-supplied audit identity
    is never honored, and an unidentified caller may not write at all.
    """
    if identity.session_id:
        return identity.session_id
    if identity.principal or identity.email or identity.human_role:
        return None
    raise HTTPException(status_code=403, detail="caller identity required to write artifact")


def resolve_creation_lineage(identity: CallerIdentity | None) -> Lineage:
    """Resolve the create-time Creation Record lineage chain, or fail loudly.

    A carried human or system principal is the chain root for every caller;
    its acting session, when present, rides additively in the same value. Only
    a caller without a principal may derive a human root from its email. Every
    other unresolvable identity is refused before any roadmap row, state,
    artifact, or event is written (see local/projects/teleclaude/spec/domain/workflow, UC-WTC23).
    """
    if identity is not None:
        if identity.principal:
            if identity.principal.startswith((HUMAN_ROOT_PREFIX, SYSTEM_ROOT_PREFIX)):
                return Lineage.create(
                    root=identity.principal,
                    acting_session=identity.session_id or None,
                )
        elif identity.email:
            return Lineage.create(
                root=f"{HUMAN_ROOT_PREFIX}{identity.email}",
                acting_session=identity.session_id or None,
            )

    raise HTTPException(
        status_code=403,
        detail=("creation lineage is unresolvable: the caller has no human root and is not a standing-role session"),
    )


async def refuse_foreign_claim(todos_db: WorkflowStore, identity: CallerIdentity, slug: str) -> None:
    """Refuse an artifact write from outside a claimed slug's claiming group.

    A live ``active_runner`` on the slug's state names the claim holder; its
    claiming group is the holder plus every session it dispatched, transitively
    through ``initiator_session_id`` (`session_in_claiming_group`). A slug with
    no live holder carries no claim gate. A direct human-identity caller — no
    agent session id — is never gated by the claim (UC-WAV16, UC-WAV23). This
    check consults ``active_runner`` but never sets it.
    """
    if not identity.session_id:
        return
    holder = await _foreign_live_claim_holder(todos_db, identity.session_id, slug)
    if holder is None:
        return
    raise HTTPException(
        status_code=409,
        detail=_FOREIGN_ARTIFACT_CLAIM_DETAIL.format(slug=slug, holder=holder),
    )


async def refuse_todo_update_outside_claiming_group(
    todos_db: WorkflowStore,
    identity: CallerIdentity,
    slug: str,
) -> None:
    """Refuse an agent update from outside a slug's live claiming group."""
    if not identity.session_id and identity.role is None:
        return
    holder = await _foreign_live_claim_holder(todos_db, identity.session_id, slug)
    if holder is None:
        return
    raise HTTPException(
        status_code=409,
        detail=_FOREIGN_UPDATE_CLAIM_DETAIL.format(slug=slug, holder=holder),
    )


async def _foreign_live_claim_holder(
    todos_db: WorkflowStore,
    caller_session_id: str,
    slug: str,
) -> str | None:
    """Return the live claim holder when the caller is outside its group."""
    state = await todos_db.read_state(slug)
    holder = (state or {}).get("active_runner")
    if not isinstance(holder, str) or not holder:
        return None
    if not await is_live_session_id(runtime_db, holder):
        return None
    if caller_session_id and await session_in_claiming_group(caller_session_id, holder):
        return None
    return holder


async def refuse_non_prepare_writer(identity: CallerIdentity, slug: str, name: str) -> None:
    """Refuse callers outside the prepare-artifact authoring role allowlist.

    A prepare artifact is writable by a prepare-phase writer — a direct
    human-identity session (empty session id), a registered session carrying one
    of the prepare-authoring roles (`PREPARE_AUTHOR_ROLES`: the prepare
    orchestrator and the intake, architecture, diagnosis, and planning authors),
    or a registered roleless session that carries no role (the human-originated,
    operator-driven shape). The gate reads the role alone; a dispatched diagnosis
    session is a worker for fleet classification and still admitted here on its
    role. A session id with no registry row is an unknown caller; every
    registered session that carries a non-prepare-authoring role — work
    orchestrator, create orchestrator, integrator, and every other worker role —
    is refused by role with a 403.
    """
    if not identity.session_id:
        return
    session = await runtime_db.get_session(identity.session_id)
    if session is None:
        raise HTTPException(
            status_code=403,
            detail=(
                f"prepare artifact '{name}' for '{slug}' is not writable by an "
                f"unknown caller; session '{identity.session_id}' is not registered"
            ),
        )
    if session.role is None:
        return
    if session.role not in PREPARE_AUTHOR_ROLES:
        raise HTTPException(
            status_code=403,
            detail=(
                f"prepare artifact '{name}' for '{slug}' is not writable by a "
                f"role-bearing session; caller role '{session.role}' is refused"
            ),
        )


INTENT_UNCLAIMED = "{slug} has no holder: the intent body is edited only by the driver that holds the item"
INTENT_FOREIGN = "{slug} is held by session {holder}; the intent body is edited only by the holder or a session of its claiming group"
INTENT_HELD_READY = "{slug} is ready: a held ready item admits no edit of its intent body"
SESSION_ANCESTRY_CAP = 32


class IntentBodyRefused(Exception):
    """An agent session's write of the intent body was refused for one named cause; nothing was written."""


async def session_ancestry(session_id: str) -> frozenset[str]:
    """The session and every session it descends from through its persisted initiator links."""
    chain = {session_id}
    current = session_id
    for _ in range(SESSION_ANCESTRY_CAP):
        session = await runtime_db.get_session(current)
        if session is None or not session.initiator_session_id or session.initiator_session_id in chain:
            break
        current = session.initiator_session_id
        chain.add(current)
    return frozenset(chain)


def intent_body_mutation(
    slug: str, ancestry: frozenset[str]
) -> Callable[[dict[str, StateValue] | None], ItemChange | None]:
    """The authority over the intent body of an item outside the task lane, on the row the write's transaction reads.

    Only the holder, or a session of its claiming group, edits the body; no role, terminal or principal alone grants
    it. An unclaimed item, a caller with no session, a session with no claim and a session of an earlier claiming
    group have none, and a held ready item admits no edit (``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``, Helpers of a driver). The mutation
    changes no state: it only refuses, before the body is written.
    """

    def decide(current: dict[str, StateValue] | None) -> ItemChange | None:
        if current is None:
            raise IntentBodyRefused(INTENT_UNCLAIMED.format(slug=slug))
        state = TodoState.model_validate(current)
        holder = state.active_runner
        if not holder:
            raise IntentBodyRefused(INTENT_UNCLAIMED.format(slug=slug))
        if holder not in ancestry:
            raise IntentBodyRefused(INTENT_FOREIGN.format(slug=slug, holder=holder))
        if state.lifecycle_phase is LifecyclePhase.READY or state.workflow.admitted is not None:
            raise IntentBodyRefused(INTENT_HELD_READY.format(slug=slug))
        return None

    return decide
