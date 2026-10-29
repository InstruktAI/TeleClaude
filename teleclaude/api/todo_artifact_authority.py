"""Caller-authority resolution and write gates for todo artifact writes.

The artifact write boundary records *who* wrote (the resolved principal),
enforces the claiming-group ownership boundary (every writable artifact kind),
and, for prepare artifacts, refuses a todo whose contract is under execution and
a caller whose role does not reach the catalog's ``prepare-artifact-write``
capability. All of these live here so the route module stays focused on request
routing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity
from teleclaude.core.db import db as runtime_db
from teleclaude.core.next_machine.lifecycle import LifecyclePhase, coerce_lifecycle_phase, is_work_lifecycle_phase
from teleclaude.core.next_machine.runtime.sessions import claim_is_held
from teleclaude.core.roles import Capability, Role, allows, resolve_session_role
from teleclaude.core.session_utils import session_in_claiming_group
from teleclaude.types.creation_record import HUMAN_ROOT_PREFIX, SYSTEM_ROOT_PREFIX, Lineage

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


async def _live_claim_holder(todos_db: WorkflowStore, slug: str) -> str | None:
    """Return the session holding a live claim on the slug, if any."""
    state = await todos_db.read_state(slug)
    holder = (state or {}).get("active_runner")
    if not isinstance(holder, str) or not holder:
        return None
    if not await claim_is_held(runtime_db, todos_db.project_root, slug, holder):
        return None
    return holder


async def _foreign_live_claim_holder(
    todos_db: WorkflowStore,
    caller_session_id: str,
    slug: str,
) -> str | None:
    """Return the live claim holder when the caller is outside its group."""
    holder = await _live_claim_holder(todos_db, slug)
    if holder is None:
        return None
    if caller_session_id and await session_in_claiming_group(caller_session_id, holder):
        return None
    return holder


async def refuse_closed_contract(
    todos_db: WorkflowStore,
    identity: CallerIdentity,
    slug: str,
    name: str,
) -> None:
    """Refuse a prepare-artifact write while the todo's contract is under execution.

    The contract is under execution while the stored lifecycle phase is a work-lane
    phase. Every caller is refused, a direct human-identity writer included; the door
    back to preparation is the work lane's kickback. The store re-checks the same
    predicate inside the write's transaction, which is the guarantee; this precheck
    keeps the refusal order the contract states (claim, closed contract, capability).
    """
    state = await todos_db.read_state(slug)
    phase = coerce_lifecycle_phase((state or {}).get("lifecycle_phase"))
    if phase is None or not is_work_lifecycle_phase(phase):
        return
    raise await closed_contract_refusal(todos_db, identity, slug, name, phase)


async def closed_contract_refusal(
    todos_db: WorkflowStore,
    identity: CallerIdentity,
    slug: str,
    name: str,
    phase: LifecyclePhase,
) -> HTTPException:
    """Build the 409 for a prepare artifact whose contract is under execution, naming its door."""
    holder = await _live_claim_holder(todos_db, slug)
    if holder is not None and holder != identity.session_id:
        door = (
            f"Address session '{holder}', which holds the todo, about the change; it returns the todo to "
            f"preparation with `telec todo stamp {slug} --kickback --reason <why>`."
        )
    else:
        door = (
            "The todo's work orchestrator returns it to preparation with "
            f"`telec todo stamp {slug} --kickback --reason <why>`; the change is made there."
        )
    return HTTPException(
        status_code=409,
        detail=(
            f"prepare artifact '{name}' for '{slug}' is not writable: the todo's contract is under "
            f"execution (lifecycle phase '{phase.value}'). {door}"
        ),
    )


async def refuse_non_prepare_writer(identity: CallerIdentity, slug: str, name: str) -> None:
    """Refuse callers whose role does not reach the prepare-artifact write capability.

    A prepare artifact is writable by a direct human-identity session (empty
    session id), by a registered roleless session (the human-originated,
    operator-driven shape), and by a registered session whose catalog role
    reaches ``prepare-artifact-write``: every full-reach role, and the focused
    roles whose explicit set composes it (the diagnoser). The gate asks the
    role catalog and keeps no role list. A session id with no registry row is an
    unknown caller; a role the catalog does not name reaches nothing; every
    other focused role is refused with a 403 naming the capability.
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
    role = resolve_session_role(session.role, identity.session_id)
    if isinstance(role, Role) and allows(role, Capability.PREPARE_ARTIFACT_WRITE):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            f"prepare artifact '{name}' for '{slug}' is not writable by a role-bearing "
            f"session whose role '{session.role}' does not reach the "
            f"'{Capability.PREPARE_ARTIFACT_WRITE}' capability; a focused session's "
            "write belongs to the session that dispatched it"
        ),
    )
