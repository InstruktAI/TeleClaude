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
from teleclaude.core.db import db as runtime_db
from teleclaude.core.db import get_session_field_sync
from teleclaude.core.next_machine._types import upstream_keys_for
from teleclaude.core.next_machine.claim_authority import ClaimOwnership, classify_claim_ownership
from teleclaude.core.next_machine.git_ops import get_origin_main_sha, has_build_commits_beyond_main
from teleclaude.core.next_machine.kinds import KIND_ENTRY_PHASE, KIND_TASK
from teleclaude.core.next_machine.lifecycle import LifecyclePhase
from teleclaude.core.next_machine.provenance import (
    read_owned_snippet_digests,
    read_referenced_snippet_digests,
    sync_artifact_provenance,
)
from teleclaude.core.next_machine.runtime.sessions import is_live_session_id
from teleclaude.core.next_machine.state_io import (
    _BUILD_VERDICT_PHASE,
    _BUILD_VERDICT_VALUES,
    _PREPARE_VERDICT_PHASES,
    _PREPARE_VERDICT_VALUES,
    stamp_finalize_ready,
    stamp_verdict,
)
from teleclaude.core.next_machine.state_mutation import ApprovalsManager, StateMutationError, StateWriter
from teleclaude.core.next_machine.task_wake import is_recurring_schedule
from teleclaude.core.todos_db import get_todos_db
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.project_root import resolve_project_root
from teleclaude.snippet_validation import snippet_body_digest
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import HoldAuditSource, HoldAuditState

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

_ALL_VERDICT_PHASES = (*_PREPARE_VERDICT_PHASES, _BUILD_VERDICT_PHASE)

_READINESS_ARTIFACT_KEY: dict[str, str] = {
    ARTIFACT_PRD: STATE_KEY_PRD,
    ARTIFACT_ARCHITECTURE: STATE_KEY_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS: STATE_KEY_DIAGNOSIS,
    ARTIFACT_REQUIREMENTS: STATE_KEY_REQUIREMENTS,
    ARTIFACT_IMPLEMENTATION_PLAN: STATE_KEY_IMPLEMENTATION_PLAN,
    ARTIFACT_TASK_PLAN: STATE_KEY_TASK_PLAN,
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
    ARTIFACT_TASK_PLAN: STATE_KEY_TASK_PLAN,
    STATE_KEY_TASK_PLAN: STATE_KEY_TASK_PLAN,
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

    Agent-authored stamps are gated by the caller's slug binding and the todo's
    active runner claim before any mutation is applied.
    """
    if stamp_type == "verdict":
        _validate_verdict_stamp(phase, value)

    todos_db = await get_todos_db(cwd)
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise ValueError(f"no state found for slug '{slug}'")

    writer = StateWriter(raw_state)
    await _validate_stamp_authority(
        slug=slug,
        stamp_type=stamp_type,
        caller_session_id=caller_session_id,
        active_runner=writer.state.active_runner,
    )

    if stamp_type == "verdict":
        return await asyncio.to_thread(stamp_verdict, cwd, slug, phase or "", value)

    if stamp_type == "finalize_ready":
        return await asyncio.to_thread(stamp_finalize_ready, cwd, slug, caller_session_id or "")

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
    elif stamp_type == "task_approved":
        await _apply_task_approval_stamp(
            todos_db,
            writer,
            slug,
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
        )
    elif stamp_type == "kickback":
        return await _apply_kickback_stamp(
            todos_db,
            writer,
            slug,
            reason=value,
            repo_root=cwd,
        )
    elif stamp_type == "task_outcome":
        return await _apply_task_outcome_stamp(
            todos_db,
            writer,
            slug,
            outcome=phase or "",
            reason=value,
            caller_session_id=caller_session_id,
        )
    else:
        raise ValueError(f"unknown stamp type: {stamp_type}")

    return await writer.commit(todos_db, slug)


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

    writer.state.kind = assigned_kind
    writer.state.lifecycle_phase = KIND_ENTRY_PHASE[assigned_kind].value

    return await writer.commit(todos_db, slug)


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


async def _apply_task_approval_stamp(
    todos_db: TodosDb,
    writer: StateWriter,
    slug: str,
    caller_session_id: str | None,
    *,
    repo_root: str,
    snippet_digest_fn: Callable[[str], str],
) -> None:
    if writer.state.kind != KIND_TASK:
        raise StateMutationError("cannot stamp task_approved: todo is not kind='task'")
    if writer.state.lifecycle_phase != LifecyclePhase.PREPARED.value:
        raise StateMutationError("cannot stamp task_approved: task is not prepared")
    if not await todos_db.artifact_exists(slug, ARTIFACT_TASK_PLAN):
        raise StateMutationError("cannot stamp task_approved: task-plan artifact missing")
    await _apply_readiness_stamp(
        todos_db,
        writer,
        slug,
        ARTIFACT_TASK_PLAN,
        "task_approved",
        repo_root=repo_root,
        snippet_digest_fn=snippet_digest_fn,
    )
    ApprovalsManager(writer).approve(
        "task_approved",
        caller_session_id=caller_session_id or "",
        approved_digest=writer.state.artifacts.task_plan.digest,
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
    upstream_digests = _current_upstream_digests(writer, state_key)
    entry = getattr(writer.state.artifacts, state_key)
    if not entry.async_provenance_complete:
        entry.owned_snippet_digests = owned_snippets
        entry.referenced_snippet_digests = referenced_snippets
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
    )


def _canonical_artifact_name(artifact: str) -> str:
    return _STATE_KEY_TO_ARTIFACT_NAME.get(artifact, artifact)


def _current_upstream_digests(writer: StateWriter, state_key: str) -> dict[str, str]:
    return {
        upstream_key: getattr(writer.state.artifacts, upstream_key).digest
        for upstream_key in upstream_keys_for(writer.state.kind, state_key)
    }


async def _apply_build_complete_stamp(
    writer: StateWriter,
    *,
    cwd: str,
    slug: str,
) -> None:
    """Record the worker's claim that the build is complete.

    Gate execution and lifecycle advancement run in the work state machine
    on its next dispatch entry. Keeping pytest out of the stamp prevents
    minute-long stamp calls and the zombie processes the previous design
    produced when the gate runner's queue thread blocked interpreter exit.
    """
    current = LifecyclePhase(writer.state.lifecycle_phase)
    if current not in (LifecyclePhase.BUILD_STARTED, LifecyclePhase.REVIEW_CHANGES_REQUESTED):
        raise StateMutationError(
            f"cannot stamp build_complete from lifecycle_phase {current.value!r}; "
            "expected build_started or review_changes_requested"
        )

    worktree_cwd = str(Path(resolve_project_root(cwd)) / WORKTREE_DIR / slug)
    if not has_build_commits_beyond_main(worktree_cwd):
        raise StateMutationError(f"build_complete: missing commits beyond main in {worktree_cwd}")

    writer.state.build_gate_claim_at = datetime.now(UTC).isoformat()


_KICKBACK_BLOCK_HEADER = "## Kickback to plan drafting"


def _format_kickback_block(reason: str) -> str:
    """Build the delimited, durable kickback block recorded to the input artifact."""
    stamped_at = datetime.now(UTC).isoformat()
    return (
        "<!-- kickback:start -->\n"
        f"{_KICKBACK_BLOCK_HEADER}\n\n"
        f"- Stamped at: {stamped_at}\n"
        f"- Reason: {reason.strip()}\n"
        "<!-- kickback:end -->"
    )


async def _apply_kickback_stamp(
    todos_db: TodosDb,
    writer: StateWriter,
    slug: str,
    *,
    reason: str,
    repo_root: str,
) -> dict[str, StateValue]:
    """Send an unbuildable todo back to plan drafting.

    Records the reason as a durable, delimited kickback block appended to the input
    artifact (creating input when the todo has none, e.g. a ``--plan`` todo) and
    invalidates the implementation-plan with the exact substantive-drift clearing a
    plan drift verdict produces, so phase derivation returns to ``plan_drafting``.

    The input write commits first; provenance then reads the committed digest and the
    state-write boundary persists the plan invalidation atomically. ``lifecycle_phase``
    is left untouched — the prepare machine derives ``plan_drafting`` on its next
    dispatch, and the work machine recognizes the kickback by the cleared plan-review
    flag.
    """
    if not reason.strip():
        raise StateMutationError("kickback requires a non-empty reason")

    existing_input = await todos_db.read_artifact(slug, ARTIFACT_INPUT)
    block = _format_kickback_block(reason)
    if existing_input.strip():
        new_body = f"{existing_input.rstrip()}\n\n{block}\n"
    else:
        new_body = f"# {slug} — Input\n\n{block}\n"
    await todos_db.write_artifact(slug, ARTIFACT_INPUT, new_body, updated_by="kickback")

    artifact_body = await todos_db.read_artifact(slug, ARTIFACT_INPUT)
    await sync_artifact_provenance(
        todos_db,
        writer,
        slug,
        ARTIFACT_INPUT,
        repo_root=repo_root,
        artifact_body=artifact_body,
        snippet_digest_fn=snippet_body_digest,
    )
    ApprovalsManager(writer).cascade_substantive_drift(ARTIFACT_IMPLEMENTATION_PLAN)
    return await writer.commit(todos_db, slug)


async def _apply_task_outcome_stamp(
    todos_db: TodosDb,
    writer: StateWriter,
    slug: str,
    *,
    outcome: str,
    reason: str,
    caller_session_id: str | None,
) -> dict[str, StateValue]:
    """Reconcile a task firing's outcome into the todo's terminal state.

    A one-shot ``success`` delivers the todo; a recurring ``success`` clears a
    prior task-error hold and leaves the todo live for its next instant; an
    ``error`` holds the todo with the task-error source and reason so a closed or
    killed run does not blindly re-dispatch. The terminal state is the durable
    outcome — no separate outcome field — and the lifecycle runner honors it
    unchanged on its next stateless re-evaluation.
    """
    if writer.state.kind != KIND_TASK:
        raise StateMutationError("cannot stamp task_outcome: todo is not kind='task'")
    if outcome not in {"success", "error"}:
        raise StateMutationError(f"task_outcome requires success or error, got: {outcome!r}")
    if outcome == "error" and not reason.strip():
        raise StateMutationError("task_outcome error requires a non-empty reason")

    if outcome == "error":
        writer.state.hold = True
        writer.state.hold_audit = HoldAuditState(
            source=HoldAuditSource.TASK_ERROR,
            set_at=datetime.now(UTC).isoformat(),
            set_by_session_id=caller_session_id or "",
            reason=reason,
        )
        return await writer.commit(todos_db, slug)

    recurring = is_recurring_schedule(await todos_db.get_schedule(slug))
    if recurring:
        if writer.state.hold_audit.source == HoldAuditSource.TASK_ERROR:
            writer.state.hold = False
            writer.state.hold_audit = HoldAuditState()
        return await writer.commit(todos_db, slug)

    if not await todos_db.deliver(slug):
        raise StateMutationError(f"task_outcome success could not deliver slug '{slug}': no active row")
    delivered = await todos_db.read_state_delivered(slug)
    if delivered is None:
        raise StateMutationError(f"task_outcome success delivered slug '{slug}' but its state is unreadable")
    return delivered


async def _validate_stamp_authority(
    *,
    slug: str,
    stamp_type: str,
    caller_session_id: str | None,
    active_runner: str | None,
) -> None:
    if caller_session_id and caller_session_id.startswith("human:"):
        if stamp_type in {
            "prd_approved",
            "task_approved",
            "creative_design_spec_confirmed",
            "creative_art_approved",
            "creative_visuals_approved",
        }:
            return
        raise PermissionError(f"{stamp_type} stamp for {slug} requires a TeleClaude session")

    if stamp_type == "kickback":
        system_role = (
            get_session_field_sync(str(MAIN_DB_PATH), caller_session_id, "system_role") if caller_session_id else None
        )
        if system_role != ROLE_ORCHESTRATOR:
            raise PermissionError(
                f"kickback stamp for {slug} is work-orchestrator-only; caller session "
                f"{caller_session_id or '<none>'} has system_role={system_role or '<none>'}. "
                "A worker session or a plain operator shell cannot kick a todo back to plan drafting."
            )
        return

    live_claimant = active_runner if active_runner and await is_live_session_id(runtime_db, active_runner) else None
    raw_working_slug = (
        get_session_field_sync(str(MAIN_DB_PATH), caller_session_id, "working_slug") if caller_session_id else None
    )
    working_slug = raw_working_slug if isinstance(raw_working_slug, str) else None
    ownership = classify_claim_ownership(
        slug=slug,
        caller_working_slug=working_slug,
        caller_session_id=caller_session_id,
        live_claimant=live_claimant,
    )

    if ownership in {ClaimOwnership.OWNS_BINDING, ClaimOwnership.OWNS_CLAIM, ClaimOwnership.UNCLAIMED}:
        return

    if ownership is ClaimOwnership.CONFLICTING_BINDING:
        raise PermissionError(
            f"{stamp_type} stamp for {slug} requires caller session {caller_session_id} "
            f"to own working_slug={slug}; caller owns working_slug={working_slug}"
        )

    if ownership is ClaimOwnership.FOREIGN_CLAIM:
        raise PermissionError(
            f"{stamp_type} stamp for {slug} refused: a live claim is held by session "
            f"{live_claimant} and caller session {caller_session_id or '<none>'} has no "
            f"working_slug binding. Give the human the claiming session id {live_claimant}."
        )
