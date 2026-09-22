"""Caller-authority resolution and write gates for todo artifact writes.

The artifact write boundary records *who* wrote (the resolved principal),
enforces the claiming-group ownership boundary (every writable artifact kind),
and, for prepare artifacts, the prepare-phase role allowlist. All three concerns
live here so the route module stays focused on request routing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity
from teleclaude.constants import PREPARE_AUTHOR_JOB_ROLES, is_standing_role
from teleclaude.core.db import db as runtime_db
from teleclaude.core.next_machine.runtime.sessions import is_live_session_id
from teleclaude.core.session_utils import session_in_claiming_group
from teleclaude.types.creation_record import Lineage

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


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

    The chain-root authority is a human principal or email whenever one
    resolves; the acting agent session, when present alongside a human root,
    rides additively in the same value. A root with no human is legitimate
    only for a standing-role session — every other unresolvable identity is a
    contract violation, refused before any roadmap row, state, artifact, or
    event is written (see project/spec/domain/workflow, UC-WTC23).
    """
    if identity is not None:
        human_root: str | None = None
        if identity.principal and identity.principal.startswith("human:"):
            human_root = identity.principal
        elif identity.email:
            human_root = f"human:{identity.email}"
        if human_root is not None:
            return Lineage.create(root=human_root, acting_session=identity.session_id or None)

        if (
            identity.principal
            and identity.principal.startswith("system:")
            and is_standing_role(identity.system_role, identity.job)
        ):
            return Lineage.create(root=identity.principal)

    raise HTTPException(
        status_code=403,
        detail=("creation lineage is unresolvable: the caller has no human root and is not a standing-role session"),
    )


async def refuse_foreign_claim(todos_db: TodosDb, identity: CallerIdentity, slug: str) -> None:
    """Refuse an artifact write from outside a claimed slug's claiming group.

    A live ``active_runner`` on the slug's state names the claim holder; its
    claiming group is the holder plus every session it dispatched, transitively
    through ``initiator_session_id`` (`session_in_claiming_group`). A slug with
    no live holder carries no claim gate. A direct human-identity caller — no
    agent session id — is never gated by the claim (UC-WAV16, UC-WAV23). This
    check consults ``active_runner`` but never sets it.
    """
    state = await todos_db.read_state(slug)
    active_runner = (state or {}).get("active_runner")
    if not isinstance(active_runner, str) or not active_runner:
        return
    if not await is_live_session_id(runtime_db, active_runner):
        return
    if not identity.session_id:
        return
    if await session_in_claiming_group(identity.session_id, active_runner):
        return
    raise HTTPException(
        status_code=409,
        detail=(
            f"todo '{slug}' is claimed by session '{active_runner}'; write refused. "
            "Address that session about the concern instead of writing into its "
            "record (software-development/policy/todo-creation-discipline, "
            "'Reconcile a flagged live todo')."
        ),
    )


async def refuse_non_prepare_writer(identity: CallerIdentity, slug: str, name: str) -> None:
    """Refuse callers outside the prepare-artifact authoring role allowlist.

    A prepare artifact is writable by a prepare-phase writer — a direct
    human-identity session (empty session id), a registered session carrying one
    of the prepare-authoring job roles (`PREPARE_AUTHOR_JOB_ROLES`: the prepare
    orchestrator and the intake, architecture, diagnosis, and planning authors),
    or a registered roleless session that carries no job (the human-originated,
    operator-driven shape). The gate reads the job alone; a dispatched diagnosis
    session is a worker for fleet classification and still admitted here on its
    job. A session id with no registry row is an unknown caller; every
    registered session that carries a non-prepare-authoring job — work
    orchestrator, create orchestrator, integrator, and every other worker job —
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
    if session.job is None:
        return
    if session.job not in PREPARE_AUTHOR_JOB_ROLES:
        raise HTTPException(
            status_code=403,
            detail=(
                f"prepare artifact '{name}' for '{slug}' is not writable by a "
                f"role-bearing session; caller job '{session.job}' is refused"
            ),
        )
