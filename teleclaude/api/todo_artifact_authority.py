"""Caller-authority resolution and the role allowlist for todo artifact writes.

The artifact write boundary records *who* wrote (the resolved principal) and, for
prepare artifacts, enforces *who may write* (the prepare-phase role allowlist).
Both concerns live here so the route module stays focused on request routing.
"""

from __future__ import annotations

from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity
from teleclaude.constants import PREPARE_AUTHOR_JOB_ROLES, ROLE_JOB_RUNNER
from teleclaude.core.db import db as runtime_db
from teleclaude.types.creation_record import Lineage


def resolved_write_principal(identity: CallerIdentity) -> str:
    """Resolve the caller principal recorded as an artifact's ``updated_by``.

    Mirrors ``todo_stamp``: an agent session is recorded under its session id, a
    human-driven terminal under its verified human principal. Caller-supplied
    audit identity is never honored.
    """
    if identity.session_id:
        return identity.session_id
    if identity.principal and identity.principal.startswith("human:"):
        return identity.principal
    if identity.email:
        return f"human:{identity.email}"
    if identity.human_role:
        return "human:terminal"
    raise HTTPException(status_code=403, detail="caller identity required to write artifact")


def resolve_creation_lineage(identity: CallerIdentity | None) -> Lineage:
    """Resolve the create-time Creation Record lineage chain, or fail loudly.

    The chain-root authority is a human principal or email whenever one
    resolves; the acting agent session, when present alongside a human root,
    rides additively in the same value. A root with no human is legitimate
    only for a job-runner session — every other unresolvable identity is a
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

        if identity.principal and identity.principal.startswith("system:") and identity.system_role == ROLE_JOB_RUNNER:
            return Lineage.create(root=identity.principal)

    raise HTTPException(
        status_code=403,
        detail=("creation lineage is unresolvable: the caller has no human root and is not a job-runner session"),
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
