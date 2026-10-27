"""Todo lifecycle stamp service.

This module is the domain boundary for ``telec todo stamp``.  It accepts a
parsed stamp intent, validates the relevant evidence, and persists the resulting
state through :class:`StateWriter`.

Database access goes through the project's memoized factories
(``get_db``, ``get_workflow_store``). They are the singular location and are
free to call inline — each operation that needs a database just calls the
factory; nothing is threaded through parameters.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_REQUIREMENTS,
    ARTIFACT_TASK_PLAN,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS,
    STATE_KEY_TASK_PLAN,
    WORKTREE_DIR,
)
from teleclaude.core.dates import is_recurring_schedule
from teleclaude.core.db import db as runtime_db
from teleclaude.core.db import get_session_field_sync
from teleclaude.core.next_machine._types import upstream_keys_for
from teleclaude.core.next_machine.claim_authority import ClaimOwnership, classify_claim_ownership
from teleclaude.core.next_machine.git_ops import (
    DRIFT_COSMETIC,
    dependency_artifact_evidence,
    get_head_commit,
    get_origin_main_sha,
    has_build_commits_beyond_main,
)
from teleclaude.core.next_machine.kinds import KIND_BUG, KIND_TASK
from teleclaude.core.next_machine.lifecycle import LifecyclePhase, diagnosis_settled_current, reset_finalize
from teleclaude.core.next_machine.marker_reconciliation import MarkerMoment, reconcile_lifecycle_markers
from teleclaude.core.next_machine.provenance import (
    read_dependency_artifact_snapshot,
    read_owned_snippet_digests,
    read_owned_snippet_ids,
    read_referenced_snippet_digests,
    sync_artifact_provenance,
)
from teleclaude.core.next_machine.review_evidence import REVIEW_EVIDENCE_ARTIFACTS
from teleclaude.core.next_machine.runtime.sessions import claim_is_held
from teleclaude.core.next_machine.session_hold import hold_todo_for_diagnosis_unresolved
from teleclaude.core.next_machine.state_io import (
    _BUILD_VERDICT_PHASE,
    _BUILD_VERDICT_VALUES,
    _PREPARE_VERDICT_PHASES,
    _PREPARE_VERDICT_VALUES,
    stamp_finalize_ready,
)
from teleclaude.core.next_machine.state_mutation import (
    ApprovalsManager,
    ReviewManager,
    StateMutationError,
    StateWriter,
)
from teleclaude.core.next_machine.work_lane_release import WorkLaneReturnReason, work_lane_return_follow_through
from teleclaude.core.operation_follow_through import FollowThrough
from teleclaude.core.roles import RoleName
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.project_root import resolve_project_root
from teleclaude.snippet_validation import snippet_body_digest_for
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import HoldAuditSource, HoldAuditState

logger = get_logger(__name__)

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore

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
_EMPTY_TEXT = ""
_KICKBACK_REQUEST_ACCEPTED_EVENT = "todo_kickback_request_accepted"
_KICKBACK_APPLIED_EVENT = "todo_kickback_applied"
_KICKBACK_REQUEST_ACCEPTED_MESSAGE = "todo kickback request accepted"
_KICKBACK_APPLIED_MESSAGE = "todo kickback applied"
_KICKBACK_ACCEPTED_OUTCOME = "accepted"
_KICKBACK_APPLIED_OUTCOME = "plan_invalidated"
_KICKBACK_CLAIM_REASON = "work_orchestrator_claim"
_KICKBACK_REASON = "kickback"
_DEPENDENCY_GATE_CLOSED = "closed"
_DRIFT_REASON_SEPARATOR = "; "
_BOOTSTRAP_BASELINE_REASON = "bootstrap: established baseline anchor for sync-written artifact"
_REKEYED_OWNED_BASELINE_REASON = "re-keyed owned snippet baseline to the reviewed identity set"


class HumanGateStamp(StrEnum):
    """Stamp types whose accepted human authority continues workflow routing."""

    PRD_APPROVED = "prd_approved"
    TASK_APPROVED = "task_approved"
    CREATIVE_DESIGN_SPEC_CONFIRMED = "creative_design_spec_confirmed"
    CREATIVE_ART_APPROVED = "creative_art_approved"
    CREATIVE_VISUALS_APPROVED = "creative_visuals_approved"


def is_human_gate_stamp(stamp_type: str) -> bool:
    """Return whether ``stamp_type`` records one of the workflow human gates."""
    try:
        HumanGateStamp(stamp_type)
    except ValueError:
        return False
    return True


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
    project_root = str(resolve_project_root(cwd))
    request_id = str(uuid.uuid4())
    if stamp_type == "verdict":
        _validate_and_log_verdict_stamp_request(
            slug=slug,
            phase=phase,
            verdict=value,
            caller_session_id=caller_session_id or "",
            request_id=request_id,
        )

    todos_db = await get_workflow_store(project_root)
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise ValueError(f"no state found for slug '{slug}'")

    writer = StateWriter(raw_state)
    await _validate_stamp_authority(
        project_root=project_root,
        slug=slug,
        stamp_type=stamp_type,
        caller_session_id=caller_session_id,
        active_runner=writer.state.active_runner,
    )
    _log_kickback_request_acceptance(stamp_type, slug=slug, caller_session_id=caller_session_id)

    if stamp_type == "verdict":
        return await _apply_verdict_stamp(
            todos_db, project_root, slug, phase or "", value, caller_session_id or "", request_id
        )

    if stamp_type == "finalize_ready":
        return await asyncio.to_thread(stamp_finalize_ready, project_root, slug, caller_session_id or "")

    return await _apply_mutation_stamp(
        todos_db,
        writer,
        slug,
        stamp_type=stamp_type,
        value=value,
        phase=phase,
        caller_session_id=caller_session_id,
        cwd=project_root,
    )


def stamp_follow_through(
    stamp_type: str,
    *,
    slug: str,
    cwd: str,
    caller_session_id: str | None,
) -> FollowThrough | None:
    """The deferred follow-through an applied stamp owes, run after its call has answered.

    A kickback returns the todo to preparation: the platform releases the stamping work
    orchestrator's claim and ends the work lane. It runs only after the stamp has
    answered, so the answer is returned before any session of the lane ends.
    """
    if stamp_type != _KICKBACK_REASON or caller_session_id is None:
        return None
    return work_lane_return_follow_through(
        runtime_db,
        slug=slug,
        project_root=str(resolve_project_root(cwd)),
        orchestrator_session_id=caller_session_id,
        reason=WorkLaneReturnReason.KICKBACK,
    )


async def _apply_mutation_stamp(
    todos_db: WorkflowStore,
    writer: StateWriter,
    slug: str,
    *,
    stamp_type: str,
    value: str,
    phase: str | None,
    caller_session_id: str | None,
    cwd: str,
) -> dict[str, StateValue]:
    """Route every remaining stamp type to its handler and commit the result.

    Split from :func:`apply_todo_stamp` to keep that function's own branch
    count under the complexity guardrail; ``verdict`` and ``finalize_ready``
    are handled there because they never reach this generic routing.
    """
    snippet_digest_fn = snippet_body_digest_for(cwd)
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
            snippet_digest_fn=snippet_digest_fn,
        )
    elif stamp_type == "plan_ready":
        await _apply_readiness_stamp(
            todos_db,
            writer,
            slug,
            ARTIFACT_IMPLEMENTATION_PLAN,
            "plan_ready",
            repo_root=cwd,
            snippet_digest_fn=snippet_digest_fn,
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
            snippet_digest_fn=snippet_digest_fn,
        )
    elif stamp_type == "task_approved":
        await _apply_task_approval_stamp(
            todos_db,
            writer,
            slug,
            caller_session_id,
            repo_root=cwd,
            snippet_digest_fn=snippet_digest_fn,
        )
    elif stamp_type == "diagnosis_settled":
        await _apply_diagnosis_settled_stamp(
            todos_db,
            writer,
            slug,
            caller_session_id,
            repo_root=cwd,
            snippet_digest_fn=snippet_digest_fn,
        )
    elif stamp_type == "diagnosis_unresolved":
        _apply_diagnosis_unresolved_stamp(writer, reason=value, caller_session_id=caller_session_id)
    elif stamp_type == "architecture_skipped":
        ApprovalsManager(writer).skip("architecture_skipped", reason=value, caller_session_id=caller_session_id or "")
    elif stamp_type == "drift_reviewed":
        await _apply_drift_reviewed_stamp(
            todos_db,
            writer,
            slug,
            value,
            repo_root=cwd,
            snippet_digest_fn=snippet_digest_fn,
            caller_session_id=caller_session_id or "",
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
            caller_session_id=caller_session_id or _EMPTY_TEXT,
        )
    elif stamp_type == "task_outcome":
        return await _apply_task_outcome_stamp(
            todos_db,
            writer,
            slug,
            outcome=phase or "",
            reason=value,
            caller_session_id=caller_session_id,
            project_root=cwd,
        )
    else:
        raise ValueError(f"unknown stamp type: {stamp_type}")

    return await writer.commit(todos_db, slug)


def _log_kickback_request_acceptance(stamp_type: str, *, slug: str, caller_session_id: str | None) -> None:
    if stamp_type != _KICKBACK_REASON:
        return
    logger.info(
        _KICKBACK_REQUEST_ACCEPTED_MESSAGE,
        event=_KICKBACK_REQUEST_ACCEPTED_EVENT,
        outcome=_KICKBACK_ACCEPTED_OUTCOME,
        reason=_KICKBACK_CLAIM_REASON,
        slug=slug,
        caller_session_id=caller_session_id or _EMPTY_TEXT,
    )


def _validate_verdict_stamp(phase: str | None, verdict: str) -> None:
    if not phase:
        raise ValueError("verdict stamp requires explicit phase")
    if phase not in _ALL_VERDICT_PHASES:
        raise ValueError(f"invalid verdict phase '{phase}': must be one of {', '.join(_ALL_VERDICT_PHASES)}")
    allowed_values = _BUILD_VERDICT_VALUES if phase == _BUILD_VERDICT_PHASE else _PREPARE_VERDICT_VALUES
    if verdict not in allowed_values:
        raise ValueError(f"invalid verdict '{verdict}' for phase '{phase}': must be one of {', '.join(allowed_values)}")


def _validate_and_log_verdict_stamp_request(
    *, slug: str, phase: str | None, verdict: str, caller_session_id: str, request_id: str
) -> None:
    """Record a verdict ingress and its rejected validation outcome when applicable."""
    logger.info(
        "workflow.review_verdict_stamp_requested",
        slug=slug,
        phase=phase or "",
        verdict=verdict,
        caller_session_id=caller_session_id,
        request_id=request_id,
    )
    try:
        _validate_verdict_stamp(phase, verdict)
    except ValueError:
        reason = "retired_phase" if phase == "requirements_review" else "phase_validation_failed"
        logger.info(
            "workflow.review_verdict_stamp_decided",
            slug=slug,
            phase=phase or "",
            verdict=verdict,
            caller_session_id=caller_session_id,
            request_id=request_id,
            outcome="refused",
            reason=reason,
        )
        raise


async def _apply_verdict_stamp(
    todos_db: WorkflowStore,
    cwd: str,
    slug: str,
    phase: str,
    verdict: str,
    caller_session_id: str,
    request_id: str,
) -> dict[str, StateValue]:
    """Bind a verdict and both current evidence digests in one DB transaction."""
    binding = REVIEW_EVIDENCE_ARTIFACTS[phase]
    external_target_digest = ""
    if binding.target_artifact_key is None:
        worktree = Path(cwd) / WORKTREE_DIR / slug
        external_target_digest = await asyncio.to_thread(get_head_commit, str(worktree))
    artifact_names = [binding.report_artifact_name]
    target_artifact = None
    if binding.target_artifact_key is not None:
        target_artifact = _STATE_KEY_TO_ARTIFACT_NAME[binding.target_artifact_key]
        artifact_names.append(target_artifact)

    target_digest = ""
    report_digest = ""

    def update_state(
        raw_state: dict[str, StateValue] | None,
        digests: dict[str, str],
    ) -> dict[str, StateValue]:
        nonlocal target_digest, report_digest
        if raw_state is None:
            raise ValueError(f"no state found for slug '{slug}'")
        report_digest = digests[binding.report_artifact_name]
        target_digest = external_target_digest if target_artifact is None else digests[target_artifact]
        refusal_reason = ""
        if not target_digest:
            refusal_reason = "missing_target_digest"
        elif not report_digest:
            refusal_reason = "missing_report_digest"
        elif not caller_session_id:
            refusal_reason = "missing_caller_session_id"
        if refusal_reason:
            logger.info(
                "workflow.review_verdict_stamp_decided",
                slug=slug,
                phase=phase,
                verdict=verdict,
                caller_session_id=caller_session_id,
                request_id=request_id,
                outcome="refused",
                reason=refusal_reason,
            )
            raise StateMutationError(f"cannot stamp review verdict: {refusal_reason}")
        writer = StateWriter(raw_state)
        ReviewManager(writer).stamp_verdict(
            phase,
            verdict,
            reviewed_target_digest=target_digest,
            review_report_digest=report_digest,
            caller_session_id=caller_session_id,
        )
        return writer.to_dict()

    payload = await todos_db.update_state_with_artifact_evidence(slug, artifact_names, update_state)
    logger.info(
        "workflow.review_verdict_stamp_decided",
        slug=slug,
        phase=phase,
        verdict=verdict,
        target_digest=target_digest,
        report_digest=report_digest,
        caller_session_id=caller_session_id,
        request_id=request_id,
        outcome="stamped",
    )
    return payload


async def _apply_readiness_stamp(
    todos_db: WorkflowStore,
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
    todos_db: WorkflowStore,
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
    todos_db: WorkflowStore,
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


async def _apply_diagnosis_settled_stamp(
    todos_db: WorkflowStore,
    writer: StateWriter,
    slug: str,
    caller_session_id: str | None,
    *,
    repo_root: str,
    snippet_digest_fn: Callable[[str], str],
) -> None:
    """Record the bug lane's settlement stamp, bound to the diagnosis digest.

    Never human-gated: the driving prepare session that settles a diagnosis is
    an agent. Currency is enforced downstream by ``_diagnosis_settled_current``
    comparing ``approved_digest`` to the artifact's live digest.
    """
    if writer.state.kind != KIND_BUG:
        raise StateMutationError(f"cannot stamp diagnosis_settled: todo is not kind={KIND_BUG!r}")
    if not await todos_db.artifact_exists(slug, ARTIFACT_DIAGNOSIS):
        raise StateMutationError("cannot stamp diagnosis_settled: diagnosis artifact missing")
    await _apply_readiness_stamp(
        todos_db,
        writer,
        slug,
        ARTIFACT_DIAGNOSIS,
        "diagnosis_settled",
        repo_root=repo_root,
        snippet_digest_fn=snippet_digest_fn,
    )
    ApprovalsManager(writer).approve(
        "diagnosis_settled",
        caller_session_id=caller_session_id or "",
        approved_digest=writer.state.artifacts.diagnosis.digest,
    )


def _apply_diagnosis_unresolved_stamp(writer: StateWriter, *, reason: str, caller_session_id: str | None) -> None:
    """Hold a bug todo whose dispatched peer could not settle a cause.

    Records no settlement — the diagnosis stays unconsumable by planning — and
    the hold itself is what stops a subsequent prepare dispatch from
    re-deriving the same DIAGNOSE dispatch indefinitely. Refused when the
    current diagnosis is already settled: the two outcomes are mutually
    exclusive, and admitting both would leave `diagnosis_settled` current
    underneath the hold, so releasing it would route straight to
    `PLAN_DRAFTING` instead of back to `DIAGNOSE` — the exact defect
    `UC-WSS17` exists to prevent.
    """
    if writer.state.kind != KIND_BUG:
        raise StateMutationError(f"cannot stamp diagnosis_unresolved: todo is not kind={KIND_BUG!r}")
    if not reason.strip():
        raise StateMutationError("diagnosis_unresolved requires a non-empty reason")
    if diagnosis_settled_current(writer.state.approvals.diagnosis_settled, writer.state.artifacts.diagnosis.digest):
        raise StateMutationError(
            "cannot stamp diagnosis_unresolved: the current diagnosis is already settled; "
            "a settled cause and an unresolved outcome are mutually exclusive for the same digest"
        )
    hold_todo_for_diagnosis_unresolved(writer, reason=reason, caller_session_id=caller_session_id or "")


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
    todos_db: WorkflowStore,
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
        repo_root=repo_root,
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
    dependency_digests_at_review: dict[str, dict[str, str]] = {}
    if state_key == STATE_KEY_IMPLEMENTATION_PLAN:
        dependency_snapshot = await read_dependency_artifact_snapshot(todos_db, slug)
        dependency_digests_at_review, _ = dependency_artifact_evidence(
            entry.dependency_artifact_digests,
            dependency_snapshot,
        )
    bootstrap = not entry.async_provenance_complete
    # A cosmetic verdict reviews the todo's current owned snippets. When an owned snippet changed identity after
    # provenance was captured, the recorded keys can never be compared with that review, so the verdict could never
    # settle the class. Re-key the baseline to the reviewed set, unless an owned ID is unresolvable (fail-safe: stays
    # pending). A substantive verdict is not re-keyed: it routes to re-derivation and the rewrite re-captures provenance.
    rekey_owned = (
        not bootstrap
        and verdict == DRIFT_COSMETIC
        and set(entry.owned_snippet_digests) != set(owned_snippets)
        and set(owned_snippets) == set(read_owned_snippet_ids(slug, repo_root=repo_root))
    )
    if bootstrap or rekey_owned:
        entry.owned_snippet_digests = owned_snippets
        baseline_reason = _BOOTSTRAP_BASELINE_REASON if bootstrap else _REKEYED_OWNED_BASELINE_REASON
        reason = _DRIFT_REASON_SEPARATOR.join((reason, baseline_reason)) if reason.strip() else baseline_reason
    if bootstrap:
        entry.referenced_snippet_digests = referenced_snippets
        entry.async_provenance_complete = True
    ApprovalsManager(writer).drift_reviewed(
        artifact=artifact_name,
        verdict=verdict,
        reason=reason,
        caller_session_id=caller_session_id,
        head_sha_at_review=get_origin_main_sha(repo_root),
        upstream_digests_at_review=upstream_digests,
        snippet_digests_at_review={**owned_snippets, **referenced_snippets},
        dependency_digests_at_review=dependency_digests_at_review,
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

    worktree_cwd = str(Path(cwd) / WORKTREE_DIR / slug)
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
    todos_db: WorkflowStore,
    writer: StateWriter,
    slug: str,
    *,
    reason: str,
    repo_root: str,
    caller_session_id: str,
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
    await todos_db.write_artifact(slug, ARTIFACT_INPUT, new_body, updated_by=caller_session_id)

    artifact_body = await todos_db.read_artifact(slug, ARTIFACT_INPUT)
    await sync_artifact_provenance(
        todos_db,
        writer,
        slug,
        ARTIFACT_INPUT,
        repo_root=repo_root,
        artifact_body=artifact_body,
        snippet_digest_fn=snippet_body_digest_for(repo_root),
    )
    ApprovalsManager(writer).cascade_substantive_drift(ARTIFACT_IMPLEMENTATION_PLAN)
    writer.state.build_gate_claim_at = _EMPTY_TEXT
    reset_finalize(writer.state)
    payload = await writer.commit(todos_db, slug)
    logger.info(
        _KICKBACK_APPLIED_MESSAGE,
        event=_KICKBACK_APPLIED_EVENT,
        outcome=_KICKBACK_APPLIED_OUTCOME,
        reason=_KICKBACK_REASON,
        slug=slug,
        caller_session_id=caller_session_id,
        old_plan_digest=writer.state.build_plan_digest,
        current_plan_digest=writer.state.artifacts.implementation_plan.digest,
        build_gate_claim_present=bool(writer.state.build_gate_claim_at),
        finalize_status=writer.state.finalize.status,
        dependency_gate=_DEPENDENCY_GATE_CLOSED,
    )
    return payload


async def _apply_task_outcome_stamp(
    todos_db: WorkflowStore,
    writer: StateWriter,
    slug: str,
    *,
    outcome: str,
    reason: str,
    caller_session_id: str | None,
    project_root: str,
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

    receipt = reconcile_lifecycle_markers(Path(project_root), slug, MarkerMoment.DELIVER)
    if not receipt.succeeded:
        raise StateMutationError(f"task_outcome success could not reconcile slug '{slug}': {receipt.reason}")
    if not await todos_db.deliver(slug, reconciliation_receipt=receipt, reconciliation_root=Path(project_root)):
        raise StateMutationError(f"task_outcome success could not deliver slug '{slug}': no active row")
    delivered = await todos_db.read_state_delivered(slug)
    if delivered is None:
        raise StateMutationError(f"task_outcome success delivered slug '{slug}' but its state is unreadable")
    return delivered


async def _validate_stamp_authority(
    *,
    project_root: str | Path,
    slug: str,
    stamp_type: str,
    caller_session_id: str | None,
    active_runner: str | None,
) -> None:
    if caller_session_id and caller_session_id.startswith("human:"):
        if is_human_gate_stamp(stamp_type):
            return
        raise PermissionError(f"{stamp_type} stamp for {slug} requires a TeleClaude session")

    if stamp_type == "kickback":
        role = get_session_field_sync(str(MAIN_DB_PATH), caller_session_id, "role") if caller_session_id else None
        if role != RoleName.WORK_ORCHESTRATOR.value:
            raise PermissionError(
                f"kickback stamp for {slug} is work-orchestrator-only; caller session "
                f"{caller_session_id or '<none>'} has role={role or '<none>'}. "
                "A worker session or a plain operator shell cannot kick a todo back to plan drafting."
            )

    live_claimant = (
        active_runner if active_runner and await claim_is_held(runtime_db, project_root, slug, active_runner) else None
    )
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
