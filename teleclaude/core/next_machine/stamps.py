"""Todo lifecycle stamp service.

This module is the domain boundary for ``telec todo stamp``.  It accepts a
parsed stamp intent, validates the relevant evidence, and persists the resulting
state through :class:`StateWriter`.

Database access goes through the project's memoized factories
(``get_db``, ``get_todos_db``). They are the singular location and are
free to call inline — each operation that needs a database just calls the
factory; nothing is threaded through parameters.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
    ARTIFACT_TASK_PLAN,
    ROLE_ORCHESTRATOR,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS,
    STATE_KEY_TASK_PLAN,
    WORKTREE_DIR,
)
from teleclaude.core.db import get_session_field_sync
from teleclaude.core.next_machine._types import ARTIFACT_UPSTREAMS
from teleclaude.core.next_machine.git_ops import get_origin_main_sha, has_build_commits_beyond_main
from teleclaude.core.next_machine.kinds import KIND_ENTRY_PHASE, KIND_TASK
from teleclaude.core.next_machine.lifecycle import ApprovalGate, LifecyclePhase, pending_approval_gate
from teleclaude.core.next_machine.provenance import (
    read_dependency_set,
    read_owned_snippet_digests,
    read_referenced_snippet_digests,
    sync_artifact_provenance,
)
from teleclaude.core.next_machine.state_io import (
    _BUILD_VERDICT_PHASE,
    _BUILD_VERDICT_VALUES,
    _PREPARE_VERDICT_PHASES,
    _PREPARE_VERDICT_VALUES,
    stamp_finalize_ready,
    stamp_verdict,
)
from teleclaude.core.next_machine.state_mutation import (
    ApprovalsManager,
    StateMutationError,
    StateWriter,
)
from teleclaude.core.todos_db import get_todos_db
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.project_root import resolve_state_root
from teleclaude.snippet_validation import snippet_body_digest
from teleclaude.types.state_value import StateValue

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

_ALL_VERDICT_PHASES = (*_PREPARE_VERDICT_PHASES, _BUILD_VERDICT_PHASE)

_READINESS_ARTIFACT_KEY: dict[str, str] = {
    ARTIFACT_PRD: STATE_KEY_PRD,
    ARTIFACT_ARCHITECTURE: STATE_KEY_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS: STATE_KEY_DIAGNOSIS,
    ARTIFACT_REQUIREMENTS: STATE_KEY_REQUIREMENTS,
    ARTIFACT_IMPLEMENTATION_PLAN: STATE_KEY_IMPLEMENTATION_PLAN,
}
_STATE_KEY_TO_ARTIFACT_NAME: dict[str, str] = {
    STATE_KEY_INPUT: ARTIFACT_INPUT,
    STATE_KEY_PRD: ARTIFACT_PRD,
    STATE_KEY_ARCHITECTURE: ARTIFACT_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS: ARTIFACT_DIAGNOSIS,
    STATE_KEY_REQUIREMENTS: ARTIFACT_REQUIREMENTS,
    STATE_KEY_IMPLEMENTATION_PLAN: ARTIFACT_IMPLEMENTATION_PLAN,
    STATE_KEY_TASK_PLAN: ARTIFACT_TASK_PLAN,
}
_ARTIFACT_TO_STATE_KEY: dict[str, str] = {
    **_READINESS_ARTIFACT_KEY,
    ARTIFACT_INPUT: STATE_KEY_INPUT,
    STATE_KEY_INPUT: STATE_KEY_INPUT,
    STATE_KEY_PRD: STATE_KEY_PRD,
    STATE_KEY_ARCHITECTURE: STATE_KEY_ARCHITECTURE,
    STATE_KEY_REQUIREMENTS: STATE_KEY_REQUIREMENTS,
    STATE_KEY_IMPLEMENTATION_PLAN: STATE_KEY_IMPLEMENTATION_PLAN,
}
_KIND_ASSIGN_VALUE = "kind_assign"

_CREATIVE_GATE_STAMPS: dict[str, tuple[str, str]] = {
    "creative_design_spec_confirmed": ("design_spec", "confirmed"),
    "creative_art_approved": ("art", "approved"),
    "creative_visuals_approved": ("visuals", "approved"),
}


async def apply_todo_stamp(
    *,
    cwd: str,
    slug: str,
    stamp_type: str,
    value: str = "",
    phase: str | None = None,
    caller_session_id: str | None = None,
) -> dict[str, StateValue]:
    """Apply one parsed todo stamp and return the updated state.

    ``build_complete`` is intentionally worker- or orchestrator-owned: the caller
    must be a trusted TeleClaude session for the stamped slug.
    """
    if stamp_type == "verdict":
        _validate_verdict_stamp(phase, value)
        return await asyncio.to_thread(stamp_verdict, cwd, slug, phase or "", value)

    if stamp_type == "finalize_ready":
        return await asyncio.to_thread(stamp_finalize_ready, cwd, slug, caller_session_id or "")

    todos_db = await get_todos_db(cwd)
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise ValueError(f"no state found for slug '{slug}'")

    writer = StateWriter(raw_state)

    if stamp_type == "deferrals_processed":
        writer.state.deferrals_processed = True
    elif stamp_type in _CREATIVE_GATE_STAMPS:
        section, flag = _CREATIVE_GATE_STAMPS[stamp_type]
        _apply_creative_gate_stamp(writer, section=section, flag=flag)
    elif stamp_type == "requirements_ready":
        await _apply_readiness_stamp(
            todos_db,
            writer,
            slug,
            ARTIFACT_REQUIREMENTS,
            "requirements_ready",
            repo_root=cwd,
            snippet_digest_fn=snippet_body_digest,
        )
    elif stamp_type == "plan_ready":
        await _apply_readiness_stamp(
            todos_db,
            writer,
            slug,
            ARTIFACT_IMPLEMENTATION_PLAN,
            "plan_ready",
            repo_root=cwd,
            snippet_digest_fn=snippet_body_digest,
        )
    elif stamp_type == "approve_current_gate":
        await _apply_current_gate_approval(
            todos_db,
            writer,
            slug,
            caller_session_id,
            repo_root=cwd,
            snippet_digest_fn=snippet_body_digest,
        )
    elif stamp_type == "prd_approved":
        await _apply_approval_stamp(
            todos_db,
            writer,
            slug,
            ARTIFACT_PRD,
            "prd_approved",
            caller_session_id,
            repo_root=cwd,
            snippet_digest_fn=snippet_body_digest,
        )
    elif stamp_type == "architecture_skipped":
        ApprovalsManager(writer).skip("architecture_skipped", reason=value, caller_session_id=caller_session_id or "")
    elif stamp_type == "drift_reviewed":
        await _apply_drift_reviewed_stamp(
            todos_db,
            writer,
            slug,
            value,
            repo_root=cwd,
            snippet_digest_fn=snippet_body_digest,
            caller_session_id=caller_session_id or "",
        )
    elif stamp_type == _KIND_ASSIGN_VALUE:
        if phase is None:
            raise ValueError("--kind-assign requires a kind value")
        return await _apply_kind_assign_stamp(
            todos_db,
            writer,
            slug,
            assigned_kind=phase,
            content=value,
        )
    elif stamp_type == "build_complete":
        await _apply_build_complete_stamp(
            writer,
            cwd=cwd,
            slug=slug,
            caller_session_id=caller_session_id,
        )
    else:
        raise ValueError(f"unknown stamp type: {stamp_type}")

    return await writer.commit(todos_db, slug)


# Maps a derived approval gate to the creative section + flag its ``A`` approval sets.
_CREATIVE_GATE_APPROVAL: dict[ApprovalGate, tuple[str, str]] = {
    ApprovalGate.CREATIVE_DESIGN_SPEC: ("design_spec", "confirmed"),
    ApprovalGate.CREATIVE_ART: ("art", "approved"),
    ApprovalGate.CREATIVE_VISUALS: ("visuals", "approved"),
}


async def _apply_current_gate_approval(
    todos_db: TodosDb,
    writer: StateWriter,
    slug: str,
    caller_session_id: str | None,
    *,
    repo_root: str,
    snippet_digest_fn: Callable[[str], str],
) -> None:
    gate = pending_approval_gate(writer.state)
    if gate is None:
        raise StateMutationError("no pending approval gate")
    if gate is ApprovalGate.PRD:
        await _apply_approval_stamp(
            todos_db,
            writer,
            slug,
            ARTIFACT_PRD,
            "prd_approved",
            caller_session_id,
            repo_root=repo_root,
            snippet_digest_fn=snippet_digest_fn,
        )
        return
    creative_target = _CREATIVE_GATE_APPROVAL.get(gate)
    if creative_target is None:
        raise StateMutationError(f"unsupported approval gate: {gate.value}")
    section, flag = creative_target
    _apply_creative_gate_stamp(writer, section=section, flag=flag)


async def _apply_kind_assign_stamp(
    todos_db: TodosDb,
    writer: StateWriter,
    slug: str,
    *,
    assigned_kind: str,
    content: str,
) -> dict[str, StateValue]:
    if assigned_kind not in KIND_ENTRY_PHASE:
        raise StateMutationError(f"unknown assigned kind: {assigned_kind!r}")
    if writer.state.kind is not None:
        raise StateMutationError("cannot assign kind after kind is already fixed")

    now = datetime.now(UTC).isoformat()
    writer.state.kind = assigned_kind
    writer.state.lifecycle_phase = KIND_ENTRY_PHASE[assigned_kind].value

    if assigned_kind != KIND_TASK:
        return await writer.commit(todos_db, slug)
    if not content.strip():
        raise StateMutationError("--kind-assign task requires task-plan content")

    task_plan = _render_task_plan(slug=slug, content=content.strip(), assigned_at=now)
    async with todos_db._session() as session:  # pylint: disable=protected-access
        async with session.begin():
            await todos_db.write_artifact(
                slug,
                ARTIFACT_TASK_PLAN,
                task_plan,
                updated_by="todo.kind_assign",
                session=session,
            )
            return await writer.commit(todos_db, slug, session=session)


def _render_task_plan(*, slug: str, content: str, assigned_at: str) -> str:
    return (
        f"# {slug} — Task Plan\n\n"
        "## Intent\n\n"
        f"{content}\n\n"
        "## Steps\n\n"
        "1. [todo] Refine this task-plan into executable steps.\n\n"
        "## Log\n\n"
        f"- {assigned_at}: Assigned task kind.\n"
    )


def _validate_verdict_stamp(phase: str | None, verdict: str) -> None:
    if not phase:
        raise ValueError("verdict stamp requires explicit phase")
    if phase not in _ALL_VERDICT_PHASES:
        raise ValueError(f"invalid verdict phase '{phase}': must be one of {', '.join(_ALL_VERDICT_PHASES)}")
    allowed_values = _BUILD_VERDICT_VALUES if phase == _BUILD_VERDICT_PHASE else _PREPARE_VERDICT_VALUES
    if verdict not in allowed_values:
        raise ValueError(f"invalid verdict '{verdict}' for phase '{phase}': must be one of {', '.join(allowed_values)}")


async def _apply_readiness_stamp(
    todos_db: TodosDb,
    writer: StateWriter,
    slug: str,
    artifact_name: str,
    signal: str,
    *,
    repo_root: str,
    snippet_digest_fn: Callable[[str], str],
) -> None:
    """Validate artifact existence and hydrate provenance.

    Provenance hydration (digest, ``produced_at``, ``upstream_digests``) is
    the fact this stamp records. The corresponding lifecycle signal fires
    from the prepare state machine on its next dispatch when it observes
    the populated provenance.
    """
    if not await todos_db.artifact_exists(slug, artifact_name):
        raise StateMutationError(f"cannot stamp {signal}: {artifact_name} artifact missing")
    state_key = _READINESS_ARTIFACT_KEY.get(artifact_name)
    if state_key:
        artifact_body = await todos_db.read_artifact(slug, artifact_name)
        await sync_artifact_provenance(
            todos_db,
            writer,
            slug,
            artifact_name,
            repo_root=repo_root,
            artifact_body=artifact_body,
            snippet_digest_fn=snippet_digest_fn,
        )


async def _apply_approval_stamp(
    todos_db: TodosDb,
    writer: StateWriter,
    slug: str,
    artifact_name: str,
    field_name: str,
    caller_session_id: str | None,
    *,
    repo_root: str,
    snippet_digest_fn: Callable[[str], str],
) -> None:
    if not await todos_db.artifact_exists(slug, artifact_name):
        raise StateMutationError(f"cannot stamp {field_name}: {artifact_name} artifact missing")
    await _apply_readiness_stamp(
        todos_db,
        writer,
        slug,
        artifact_name,
        field_name,
        repo_root=repo_root,
        snippet_digest_fn=snippet_digest_fn,
    )
    approved_digest = writer.state.artifacts.prd.digest if artifact_name == ARTIFACT_PRD else ""
    ApprovalsManager(writer).approve(
        field_name,
        caller_session_id=caller_session_id or "",
        approved_digest=approved_digest,
    )


def _apply_creative_gate_stamp(writer: StateWriter, *, section: str, flag: str) -> None:
    creative = writer.state.creative
    if creative is None:
        creative = {}
        writer.state.creative = creative

    raw_section = creative.get(section)
    section_state: dict[str, StateValue] = dict(raw_section) if isinstance(raw_section, dict) else {}
    section_state[flag] = True
    creative[section] = section_state


async def _apply_drift_reviewed_stamp(
    todos_db: TodosDb,
    writer: StateWriter,
    slug: str,
    value: str,
    *,
    repo_root: str,
    snippet_digest_fn: Callable[[str], str],
    caller_session_id: str,
) -> None:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise StateMutationError(f"drift_reviewed value must be JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise StateMutationError("drift_reviewed value must be a JSON object")
    artifact = payload.get("artifact")
    verdict = payload.get("verdict")
    reason = payload.get("reason", "")
    if not isinstance(artifact, str) or not isinstance(verdict, str) or not isinstance(reason, str):
        raise StateMutationError("drift_reviewed requires string artifact, verdict, and reason fields")
    artifact_name = _canonical_artifact_name(artifact)
    state_key = _ARTIFACT_TO_STATE_KEY.get(artifact_name)
    if state_key is None:
        raise StateMutationError(f"unknown drift_reviewed artifact: {artifact!r}")
    artifact_body = await todos_db.read_artifact(slug, artifact_name)
    owned_snippets = await read_owned_snippet_digests(
        todos_db,
        slug,
        artifact_name,
        snippet_digest_fn=snippet_digest_fn,
    )
    referenced_snippets = await read_referenced_snippet_digests(
        todos_db,
        slug,
        artifact_name,
        artifact_body,
        repo_root=repo_root,
        snippet_digest_fn=snippet_digest_fn,
    )
    dependency_set = await read_dependency_set(todos_db, slug)
    upstream_digests = _current_upstream_digests(writer, state_key)
    entry = getattr(writer.state.artifacts, state_key)
    if not entry.async_provenance_complete:
        entry.owned_snippet_digests = owned_snippets
        entry.referenced_snippet_digests = referenced_snippets
        entry.dependency_set_at_write = dependency_set
        entry.async_provenance_complete = True
        bootstrap_reason = "bootstrap: established baseline anchor for sync-written artifact"
        reason = f"{reason}; {bootstrap_reason}" if reason.strip() else bootstrap_reason
    ApprovalsManager(writer).drift_reviewed(
        artifact=artifact_name,
        verdict=verdict,
        reason=reason,
        caller_session_id=caller_session_id,
        head_sha_at_review=get_origin_main_sha(repo_root),
        upstream_digests_at_review=upstream_digests,
        snippet_digests_at_review={**owned_snippets, **referenced_snippets},
        dep_set_at_review=dependency_set,
    )


def _canonical_artifact_name(artifact: str) -> str:
    return _STATE_KEY_TO_ARTIFACT_NAME.get(artifact, artifact)


def _current_upstream_digests(writer: StateWriter, state_key: str) -> dict[str, str]:
    return {
        upstream_key: getattr(writer.state.artifacts, upstream_key).digest
        for upstream_key in ARTIFACT_UPSTREAMS.get(state_key, ())
    }


async def _apply_build_complete_stamp(
    writer: StateWriter,
    *,
    cwd: str,
    slug: str,
    caller_session_id: str | None,
) -> None:
    """Record the worker's claim that the build is complete.

    Gate execution and lifecycle advancement run in the work state machine
    on its next dispatch entry. Keeping pytest out of the stamp prevents
    minute-long stamp calls and the zombie processes the previous design
    produced when the gate runner's queue thread blocked interpreter exit.
    """
    await _validate_build_complete_owner(slug=slug, caller_session_id=caller_session_id)

    current = LifecyclePhase(writer.state.lifecycle_phase)
    if current not in (LifecyclePhase.BUILD_STARTED, LifecyclePhase.REVIEW_CHANGES_REQUESTED):
        raise StateMutationError(
            f"cannot stamp build_complete from lifecycle_phase {current.value!r}; "
            "expected build_started or review_changes_requested"
        )

    worktree_cwd = str(Path(resolve_state_root(cwd)) / WORKTREE_DIR / slug)
    if not has_build_commits_beyond_main(worktree_cwd):
        raise StateMutationError(f"build_complete: missing commits beyond main in {worktree_cwd}")

    writer.state.build_gate_claim_at = datetime.now(UTC).isoformat()


async def _validate_build_complete_owner(
    *,
    slug: str,
    caller_session_id: str | None,
) -> None:
    if not caller_session_id:
        raise PermissionError(f"build_complete stamp for {slug} requires a TeleClaude worker session")
    working_slug = get_session_field_sync(str(MAIN_DB_PATH), caller_session_id, "working_slug")
    system_role = get_session_field_sync(str(MAIN_DB_PATH), caller_session_id, "system_role")
    if working_slug == slug or system_role == ROLE_ORCHESTRATOR:
        return
    raise PermissionError(
        f"build_complete stamp for {slug} requires caller session {caller_session_id} "
        f"to own working_slug={slug} or have system_role={ROLE_ORCHESTRATOR}"
    )
