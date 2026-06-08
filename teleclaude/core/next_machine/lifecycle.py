"""Canonical lifecycle helpers.

This module owns lifecycle phase coercion, projection, and the v2 prepare
derivation table. Prepare no longer persists pair identity or grounding state;
it derives progress from artifacts, review verdicts, approval stamps, skip
stamps, and drift-review stamps.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_DIAGNOSIS,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_PRD,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS,
)
from teleclaude.core.db import SessionIdentityError, get_session_field_sync, resolve_session_principal
from teleclaude.core.models import Session
from teleclaude.core.next_machine.git_ops import (
    DRIFT_COSMETIC,
    DRIFT_FRESH,
    DRIFT_PENDING,
    DRIFT_SUBSTANTIVE,
    ArtifactDriftStatus,
    DependencyStatusReader,
    derive_age_drift,
    derive_artifact_drift,
    derive_dependency_graph_drift,
    derive_owned_snippet_drift,
    derive_upstream_artifact_drift,
    derive_upstream_snippet_drift,
    get_head_commit,
)
from teleclaude.core.next_machine.kinds import (
    BUG_DIAGNOSE_KINDS,
    FAST_TRACK_PREPARED_KINDS,
    FEATURE_PREPARE_KINDS,
    PLAN_ONLY_PREPARE_KINDS,
)
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.types.lifecycle import (
    LEGACY_LIFECYCLE_PHASE_NORMALIZATION,
    LIFECYCLE_PHASE_ORDER,
    PREPARE_LIFECYCLE_PHASES,
    WORK_LIFECYCLE_PHASES,
    LifecyclePhase,
    LifecycleStage,
)
from teleclaude.types.todos import ApprovalStamp, ReviewVerdictState, TodoState

__all__ = [
    "LIFECYCLE_PHASE_ORDER",
    "PREPARE_LIFECYCLE_PHASES",
    "READY_BAND_PHASES",
    "WORK_LIFECYCLE_PHASES",
    "LifecyclePhase",
    "LifecycleStage",
    "adopt_prepare_handoff_phase",
    "apply_authoritative_signal",
    "coerce_lifecycle_phase",
    "collapse_drift",
    "derive_lifecycle_drift",
    "infer_lifecycle_stage",
    "invalidate_downstream_on_refine",
    "is_in_prepare_lane",
    "is_prepare_lifecycle_phase",
    "is_ready_band_eligible",
    "is_ready_for_work",
    "is_settled_ok_phase",
    "is_work_lifecycle_phase",
    "lifecycle_phase_index",
    "normalize_mark_phase",
    "phase_is_complete",
    "prepare_blockers",
    "reconcile_lifecycle_phase",
    "require_lifecycle_phase",
]

_ArtifactPresence = Mapping[str, bool]
_FEATURE_KINDS = FEATURE_PREPARE_KINDS
READY_BAND_PHASES: frozenset[LifecyclePhase] = frozenset(
    {
        LifecyclePhase.PREPARED,
        LifecyclePhase.BUILD_STARTED,
        LifecyclePhase.BUILD_COMPLETE,
        LifecyclePhase.REVIEW_CHANGES_REQUESTED,
        LifecyclePhase.REVIEW_APPROVED,
    }
)
_DRIFT_CLASS_CODE = "code"
_DRIFT_CLASS_UPSTREAM_ARTIFACT = "upstream-artifact"
_DRIFT_CLASS_OWNED_SNIPPET = "owned-snippet"
_DRIFT_CLASS_UPSTREAM_SNIPPET = "upstream-snippet"
_DRIFT_CLASS_DEPENDENCY_GRAPH = "dependency-graph"
_DRIFT_CLASS_AGE = "age"
_ALL_DRIFT_CLASSES = (
    _DRIFT_CLASS_CODE,
    _DRIFT_CLASS_UPSTREAM_ARTIFACT,
    _DRIFT_CLASS_OWNED_SNIPPET,
    _DRIFT_CLASS_UPSTREAM_SNIPPET,
    _DRIFT_CLASS_DEPENDENCY_GRAPH,
    _DRIFT_CLASS_AGE,
)
_INTENT_DRIFT_CLASSES = (
    _DRIFT_CLASS_CODE,
    _DRIFT_CLASS_UPSTREAM_SNIPPET,
    _DRIFT_CLASS_DEPENDENCY_GRAPH,
    _DRIFT_CLASS_AGE,
)
_IMPLEMENTATION_PLAN_DRIFT_CLASSES = (
    _DRIFT_CLASS_CODE,
    _DRIFT_CLASS_UPSTREAM_ARTIFACT,
    _DRIFT_CLASS_UPSTREAM_SNIPPET,
    _DRIFT_CLASS_DEPENDENCY_GRAPH,
    _DRIFT_CLASS_AGE,
)
_DRIFT_TRACKED_ARTIFACTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (STATE_KEY_INPUT, STATE_KEY_INPUT, _INTENT_DRIFT_CLASSES),
    (STATE_KEY_PRD, STATE_KEY_PRD, _ALL_DRIFT_CLASSES),
    (STATE_KEY_REQUIREMENTS, STATE_KEY_REQUIREMENTS, _INTENT_DRIFT_CLASSES),
    (STATE_KEY_ARCHITECTURE, STATE_KEY_ARCHITECTURE, _ALL_DRIFT_CLASSES),
    (ARTIFACT_DIAGNOSIS, STATE_KEY_DIAGNOSIS, _ALL_DRIFT_CLASSES),
    (ARTIFACT_IMPLEMENTATION_PLAN, STATE_KEY_IMPLEMENTATION_PLAN, _IMPLEMENTATION_PLAN_DRIFT_CLASSES),
)
_DRIFT_PRIORITY: tuple[ArtifactDriftStatus, ...] = (
    DRIFT_SUBSTANTIVE,
    DRIFT_PENDING,
    DRIFT_COSMETIC,
    DRIFT_FRESH,
)


def coerce_lifecycle_phase(raw: object) -> LifecyclePhase | None:
    """Return a lifecycle phase enum member for a stored raw value."""
    if not isinstance(raw, str) or not raw:
        return None
    normalized = LEGACY_LIFECYCLE_PHASE_NORMALIZATION.get(raw, raw)
    try:
        return LifecyclePhase(normalized)
    except ValueError:
        return None


def require_lifecycle_phase(raw: object, *, context: str) -> LifecyclePhase:
    """Return the stored lifecycle phase or raise on invalid canonical state."""
    lifecycle = coerce_lifecycle_phase(raw)
    if lifecycle is None:
        raise ValueError(f"{context}: missing or invalid lifecycle_phase {raw!r}")
    return lifecycle


def lifecycle_phase_index(phase: LifecyclePhase) -> int:
    """Return the stable phase order index."""
    return LIFECYCLE_PHASE_ORDER.index(phase)


def is_prepare_lifecycle_phase(phase: LifecyclePhase) -> bool:
    """Return True when the phase belongs to the prepare lane."""
    return phase in PREPARE_LIFECYCLE_PHASES


def is_work_lifecycle_phase(phase: LifecyclePhase) -> bool:
    """Return True when the phase belongs to the work lane."""
    return phase in WORK_LIFECYCLE_PHASES


def infer_lifecycle_stage(phase: LifecyclePhase) -> LifecycleStage:
    """Return the stage bucket implied by the canonical lifecycle pointer."""
    if is_prepare_lifecycle_phase(phase):
        return LifecycleStage.PREPARE
    return LifecycleStage.WORK


def is_ready_for_work(*, kind: str | None, lifecycle_phase: str | None) -> tuple[bool, str]:
    """Authoritative gate for entering or resuming the work lane."""
    _ = kind
    phase = coerce_lifecycle_phase(lifecycle_phase)
    if phase is None:
        return False, f"unknown lifecycle_phase {lifecycle_phase!r}"
    if lifecycle_phase_index(phase) < lifecycle_phase_index(LifecyclePhase.PREPARED):
        return False, f"lifecycle_phase {phase.value!r} is before 'prepared'"
    return True, ""


def is_ready_band_eligible(
    *,
    kind: str | None,
    lifecycle_phase: str | None,
    after_deps: list[str],
    delivered_slugs: set[str],
) -> bool:
    """Return whether a todo belongs in the active Ready band."""
    all_deps_delivered = all(dep in delivered_slugs for dep in after_deps)
    phase = coerce_lifecycle_phase(lifecycle_phase)
    phase_ok = kind in FAST_TRACK_PREPARED_KINDS or phase in READY_BAND_PHASES
    return all_deps_delivered and phase_ok


def is_in_prepare_lane(lifecycle_phase: str | None) -> bool:
    """At-or-before ``PREPARED`` (the prepare lane plus its terminal pointer)."""
    phase = coerce_lifecycle_phase(lifecycle_phase)
    if phase is None:
        return False
    return phase in PREPARE_LIFECYCLE_PHASES


def is_settled_ok_phase(lifecycle_phase: str | None) -> bool:
    """Phase represents a settled positive state used for "ok" rendering."""
    phase = coerce_lifecycle_phase(lifecycle_phase)
    return phase in (LifecyclePhase.PREPARED, LifecyclePhase.REVIEW_APPROVED)


def derive_build_status(
    lifecycle_phase: str | None,
    *,
    is_draft: bool,
    is_delivered: bool,
) -> str | None:
    """Project canonical lifecycle pointer to the legacy build_status display string."""
    if is_draft or is_delivered:
        return None
    phase = coerce_lifecycle_phase(lifecycle_phase)
    if phase is None:
        return None
    if phase == LifecyclePhase.BUILD_STARTED:
        return "started"
    if phase in (
        LifecyclePhase.BUILD_COMPLETE,
        LifecyclePhase.REVIEW_CHANGES_REQUESTED,
        LifecyclePhase.REVIEW_APPROVED,
        LifecyclePhase.FINALIZE_READY,
    ):
        return "complete"
    return None


def derive_review_status(
    lifecycle_phase: str | None,
    *,
    is_draft: bool,
    is_delivered: bool,
) -> str | None:
    """Project canonical lifecycle pointer to the legacy review_status display string."""
    if is_draft or is_delivered:
        return None
    phase = coerce_lifecycle_phase(lifecycle_phase)
    if phase is None:
        return None
    if phase == LifecyclePhase.BUILD_COMPLETE:
        return "pending"
    if phase == LifecyclePhase.REVIEW_CHANGES_REQUESTED:
        return "changes_requested"
    if phase in (
        LifecyclePhase.REVIEW_APPROVED,
        LifecyclePhase.FINALIZE_READY,
    ):
        return "approved"
    return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _artifact_exists(model: TodoState, key: str) -> bool:
    entry = getattr(model.artifacts, key)
    return bool(entry.digest or entry.produced_at)


def _artifact_present(model: TodoState, key: str, *, artifact_presence: _ArtifactPresence | None = None) -> bool:
    if artifact_presence is not None and key in artifact_presence:
        return artifact_presence[key]
    return _artifact_exists(model, key)


def _intent_artifact_exists(model: TodoState) -> bool:
    return _artifact_exists(model, STATE_KEY_PRD) or _artifact_exists(model, STATE_KEY_REQUIREMENTS)


def _intent_artifact_present(
    model: TodoState,
    *,
    artifact_presence: _ArtifactPresence | None = None,
) -> bool:
    return _artifact_present(model, STATE_KEY_PRD, artifact_presence=artifact_presence) or _artifact_present(
        model, STATE_KEY_REQUIREMENTS, artifact_presence=artifact_presence
    )


def _session_principal(session_id: str) -> str:
    session = Session(
        session_id=session_id,
        computer_name="",
        tmux_session_name="",
        title="",
        principal=_string_session_field(session_id, "principal"),
        human_email=_string_session_field(session_id, "human_email"),
        human_role=_string_session_field(session_id, "human_role"),
        system_role=_string_session_field(session_id, "system_role"),
    )
    try:
        principal, _role = resolve_session_principal(session)
    except SessionIdentityError:
        return ""
    return principal


def _string_session_field(session_id: str, field: str) -> str | None:
    value = get_session_field_sync(str(MAIN_DB_PATH), session_id, field)
    return value if isinstance(value, str) and value else None


def _approval_is_human(stamp: ApprovalStamp) -> bool:
    if not stamp.approved:
        return False
    if not stamp.caller_session_id:
        return False
    return _session_principal(stamp.caller_session_id).startswith("human:")


def _review_approved(review: ReviewVerdictState) -> bool:
    return review.verdict in ("approve", "skipped")


def _clear_prepare_review(review: ReviewVerdictState) -> None:
    review.verdict = ""
    review.reviewed_at = ""
    review.approved_digest = ""


def _clear_build_review(model: TodoState) -> None:
    model.build_review.verdict = ""
    model.build_review.reviewed_at = ""
    model.build_review.dispatch_head = ""


def _reset_finalize(model: TodoState) -> None:
    model.finalize.status = "pending"
    model.finalize.ready_at = ""


def _reset_dor(model: TodoState) -> None:
    if model.dor is None:
        return
    model.dor.last_assessed_at = None
    model.dor.score = 0
    model.dor.status = "needs_work"


def _clear_work_entry_state(model: TodoState) -> None:
    _clear_build_review(model)
    _reset_finalize(model)
    model.build_start_base_sha = ""
    model.build_completed_at = ""
    model.build_gate_claim_at = ""


async def derive_lifecycle_drift(
    slug: str,
    model: TodoState,
    *,
    repo_root: str | None = None,
    todos_db: DependencyStatusReader,
    snippet_digest_fn: Callable[[str], str],
    writer: object,
) -> dict[str, dict[str, ArtifactDriftStatus]]:
    """Return per-artifact, per-class drift for every present tracked artifact."""
    _ = writer
    drift: dict[str, dict[str, ArtifactDriftStatus]] = {}
    for artifact_name, state_key, applicable_classes in _DRIFT_TRACKED_ARTIFACTS:
        entry = getattr(model.artifacts, state_key)
        if not entry.digest and not entry.produced_at:
            continue
        class_drift: dict[str, ArtifactDriftStatus] = {}
        for class_name in applicable_classes:
            if class_name == _DRIFT_CLASS_CODE:
                class_drift[class_name] = derive_artifact_drift(
                    entry,
                    model.approvals.drift_reviewed.get(artifact_name),
                    "",
                    repo_root or "",
                )
            elif class_name == _DRIFT_CLASS_UPSTREAM_ARTIFACT:
                class_drift[class_name] = derive_upstream_artifact_drift(model, artifact_name)
            elif class_name == _DRIFT_CLASS_OWNED_SNIPPET:
                class_drift[class_name] = derive_owned_snippet_drift(
                    model,
                    artifact_name,
                    snippet_digest_fn=snippet_digest_fn,
                )
            elif class_name == _DRIFT_CLASS_UPSTREAM_SNIPPET:
                class_drift[class_name] = derive_upstream_snippet_drift(
                    model,
                    artifact_name,
                    snippet_digest_fn=snippet_digest_fn,
                )
            elif class_name == _DRIFT_CLASS_DEPENDENCY_GRAPH:
                class_drift[class_name] = await derive_dependency_graph_drift(
                    slug,
                    model,
                    artifact_name,
                    todos_db=todos_db,
                )
            elif class_name == _DRIFT_CLASS_AGE:
                class_drift[class_name] = derive_age_drift(
                    model,
                    artifact_name,
                    age_window_seconds=None,
                    drift_reviewed_stamp=model.approvals.drift_reviewed.get(artifact_name),
                )
        drift[artifact_name] = class_drift
    return drift


def collapse_drift(
    result: dict[str, dict[str, ArtifactDriftStatus]],
) -> dict[str, ArtifactDriftStatus]:
    """Collapse per-class drift to per-artifact status by priority."""
    collapsed: dict[str, ArtifactDriftStatus] = {}
    for artifact_name, class_statuses in result.items():
        for status in _DRIFT_PRIORITY:
            if status in class_statuses.values():
                collapsed[artifact_name] = status
                break
    return collapsed


def prepare_blockers(model: TodoState, *, repo_root: str | None = None) -> list[str]:
    """Return deterministic prepare blockers for advisory payloads and phase derivation."""
    _ = repo_root
    return _non_drift_prepare_blockers(model)


def _non_drift_prepare_blockers(model: TodoState) -> list[str]:
    blockers: list[str] = []
    blockers.extend(_missing_upstream_blockers(model))
    blockers.extend(_review_remediation_blockers(model))
    blockers.extend(_upcycle_blockers(model))
    return blockers


def _missing_upstream_blockers(model: TodoState) -> list[str]:
    """Return blockers for artifacts whose required upstream artifact is absent."""
    blockers: list[str] = []
    if _artifact_exists(model, STATE_KEY_ARCHITECTURE) and not _intent_artifact_exists(model):
        blockers.append("architecture artifact is present but required upstream prd/requirements intent is missing")
    if (
        model.kind in _FEATURE_KINDS
        and _artifact_exists(model, STATE_KEY_IMPLEMENTATION_PLAN)
        and not _intent_artifact_exists(model)
    ):
        blockers.append(
            "implementation-plan artifact is present but required upstream prd/requirements intent is missing"
        )
    return blockers


def _review_remediation_blockers(model: TodoState) -> list[str]:
    blockers: list[str] = []
    review_pairs = (
        (STATE_KEY_ARCHITECTURE, model.architecture_review),
        (STATE_KEY_IMPLEMENTATION_PLAN, model.plan_review),
    )
    for artifact_key, review in review_pairs:
        if review.verdict not in ("changes_requested", "needs_work"):
            continue
        entry = getattr(model.artifacts, artifact_key)
        if not entry.produced_at or (review.reviewed_at and entry.produced_at <= review.reviewed_at):
            blockers.append(f"{artifact_key} review requested changes with no newer artifact write")
    return blockers


def _upcycle_blockers(model: TodoState) -> list[str]:
    if model.schema_version < 3:
        return ["todo state could not be upcycled to schema_version 3"]
    return []


def _plan_only_phase(
    model: TodoState,
    *,
    artifact_presence: _ArtifactPresence | None,
    repo_root: str | None,
) -> LifecyclePhase:
    if not _artifact_present(model, STATE_KEY_IMPLEMENTATION_PLAN, artifact_presence=artifact_presence):
        return LifecyclePhase.PLAN_DRAFTING
    if not _review_approved(model.plan_review):
        if model.plan_review.cleared_by_substantive_drift:
            return LifecyclePhase.PLAN_DRAFTING
        return LifecyclePhase.PLAN_REVIEW
    if prepare_blockers(model, repo_root=repo_root):
        return LifecyclePhase.BLOCKED
    return LifecyclePhase.PREPARED


def _diagnose_phase(
    model: TodoState,
    *,
    artifact_presence: _ArtifactPresence | None,
    repo_root: str | None,
) -> LifecyclePhase:
    if not _artifact_present(model, STATE_KEY_DIAGNOSIS, artifact_presence=artifact_presence):
        return LifecyclePhase.DIAGNOSE
    return _plan_only_phase(model, artifact_presence=artifact_presence, repo_root=repo_root)


def _feature_phase(
    model: TodoState,
    *,
    artifact_presence: _ArtifactPresence | None,
    repo_root: str | None,
) -> LifecyclePhase:
    if not any(
        [
            _artifact_present(model, STATE_KEY_INPUT, artifact_presence=artifact_presence),
            _intent_artifact_present(model, artifact_presence=artifact_presence),
            _artifact_present(model, STATE_KEY_ARCHITECTURE, artifact_presence=artifact_presence),
            _artifact_present(model, STATE_KEY_IMPLEMENTATION_PLAN, artifact_presence=artifact_presence),
        ]
    ):
        return LifecyclePhase.DRAFT

    has_prd = _artifact_present(model, STATE_KEY_PRD, artifact_presence=artifact_presence)
    has_legacy_requirements = _artifact_present(model, STATE_KEY_REQUIREMENTS, artifact_presence=artifact_presence)
    if not (has_prd or has_legacy_requirements):
        return LifecyclePhase.PRD_DRAFTING
    if has_prd and not _approval_is_human(model.approvals.prd_approved):
        return LifecyclePhase.PRD_HUMAN_APPROVAL
    if not has_prd and has_legacy_requirements and not _review_approved(model.requirements_review):
        return LifecyclePhase.PRD_HUMAN_APPROVAL

    architecture_skipped = model.approvals.architecture_skipped is not None

    if not architecture_skipped:
        if not _artifact_present(model, STATE_KEY_ARCHITECTURE, artifact_presence=artifact_presence):
            return LifecyclePhase.ARCHITECTURE_DRAFTING
        if not _review_approved(model.architecture_review):
            if model.architecture_review.cleared_by_substantive_drift:
                return LifecyclePhase.ARCHITECTURE_DRAFTING
            return LifecyclePhase.ARCHITECTURE_REVIEW

    return _plan_only_phase(model, artifact_presence=artifact_presence, repo_root=repo_root)


def adopt_prepare_handoff_phase(
    model: TodoState,
    *,
    artifact_presence: _ArtifactPresence | None = None,
    repo_root: str | None = None,
) -> LifecyclePhase:
    """Choose the prepare pointer from existing authoritative state and artifacts."""
    if model.kind in FAST_TRACK_PREPARED_KINDS:
        return LifecyclePhase.PREPARED
    if _non_drift_prepare_blockers(model):
        return LifecyclePhase.BLOCKED
    if model.kind in BUG_DIAGNOSE_KINDS:
        return _diagnose_phase(model, artifact_presence=artifact_presence, repo_root=repo_root)
    if model.kind in PLAN_ONLY_PREPARE_KINDS:
        return _plan_only_phase(model, artifact_presence=artifact_presence, repo_root=repo_root)
    return _feature_phase(model, artifact_presence=artifact_presence, repo_root=repo_root)


def reconcile_lifecycle_phase(
    model: TodoState,
    stage: LifecycleStage,
    *,
    worktree_cwd: str | None = None,
    artifact_presence: _ArtifactPresence | None = None,
) -> LifecyclePhase | None:
    """Return the best-matching phase for an explicit stage-scoped reconciliation."""
    _ = worktree_cwd
    if stage == LifecycleStage.PREPARE:
        return adopt_prepare_handoff_phase(model, artifact_presence=artifact_presence, repo_root=worktree_cwd)

    if model.finalize.status == "ready":
        return LifecyclePhase.FINALIZE_READY
    if model.build_review.verdict == "approve":
        return LifecyclePhase.REVIEW_APPROVED
    if model.build_review.verdict == "changes_requested":
        return LifecyclePhase.REVIEW_CHANGES_REQUESTED
    if model.build_completed_at:
        return LifecyclePhase.BUILD_COMPLETE
    if model.lifecycle_phase == LifecyclePhase.BUILD_STARTED.value:
        return LifecyclePhase.BUILD_STARTED
    if model.lifecycle_phase == LifecyclePhase.PREPARED.value:
        return LifecyclePhase.BUILD_STARTED
    return None


def _move_to(model: TodoState, target: LifecyclePhase) -> LifecyclePhase:
    model.lifecycle_phase = target.value
    return target


def apply_authoritative_signal(
    model: TodoState,
    signal: str,
    *,
    phase: str | None = None,
    worktree_cwd: str | None = None,
) -> LifecyclePhase:
    """Apply one authoritative signal and advance by at most one step."""
    current = require_lifecycle_phase(model.lifecycle_phase, context="apply_authoritative_signal")
    now = _now_iso()

    if signal in {
        "requirements_ready",
        "prd_ready",
        "architecture_ready",
        "plan_ready",
        "prd_approved",
        "architecture_approved",
        "plan_approved",
        "architecture_skipped",
    }:
        return _move_to(model, adopt_prepare_handoff_phase(model))

    if signal == "verdict":
        if phase == "build_review" and current == LifecyclePhase.BUILD_COMPLETE:
            if model.build_review.verdict == "approve":
                return _move_to(model, LifecyclePhase.REVIEW_APPROVED)
            if model.build_review.verdict == "changes_requested":
                model.build_completed_at = ""
                model.build_gate_claim_at = ""
                return _move_to(model, LifecyclePhase.REVIEW_CHANGES_REQUESTED)
        return _move_to(model, adopt_prepare_handoff_phase(model))

    if signal == "build_started" and current == LifecyclePhase.PREPARED:
        model.build_start_base_sha = get_head_commit(worktree_cwd or "")
        model.build_completed_at = ""
        _clear_build_review(model)
        _reset_finalize(model)
        return _move_to(model, LifecyclePhase.BUILD_STARTED)

    if signal == "build_complete" and current in (
        LifecyclePhase.BUILD_STARTED,
        LifecyclePhase.REVIEW_CHANGES_REQUESTED,
    ):
        model.build_completed_at = now
        _reset_finalize(model)
        if current == LifecyclePhase.REVIEW_CHANGES_REQUESTED:
            model.build_review.round += 1
        _clear_build_review(model)
        return _move_to(model, LifecyclePhase.BUILD_COMPLETE)

    if signal == "finalize_ready" and current == LifecyclePhase.REVIEW_APPROVED and model.finalize.status == "ready":
        return _move_to(model, LifecyclePhase.FINALIZE_READY)

    return current


def phase_is_complete(model: TodoState, phase: LifecyclePhase, *, worktree_cwd: str | None = None) -> bool:
    """Return True when authoritative state says ``phase`` is complete."""
    _ = worktree_cwd
    if phase in (LifecyclePhase.DRAFT, LifecyclePhase.PREPARED, LifecyclePhase.BLOCKED):
        return False
    if phase == LifecyclePhase.PRD_DRAFTING:
        return _intent_artifact_exists(model)
    if phase == LifecyclePhase.PRD_HUMAN_APPROVAL:
        return _approval_is_human(model.approvals.prd_approved) or (
            _artifact_exists(model, STATE_KEY_REQUIREMENTS) and _review_approved(model.requirements_review)
        )
    if phase == LifecyclePhase.ARCHITECTURE_DRAFTING:
        return _artifact_exists(model, STATE_KEY_ARCHITECTURE) or model.approvals.architecture_skipped is not None
    if phase == LifecyclePhase.ARCHITECTURE_REVIEW:
        return _review_approved(model.architecture_review)
    if phase == LifecyclePhase.DIAGNOSE:
        return _artifact_exists(model, STATE_KEY_DIAGNOSIS)
    if phase == LifecyclePhase.PLAN_DRAFTING:
        return _artifact_exists(model, STATE_KEY_IMPLEMENTATION_PLAN)
    if phase == LifecyclePhase.PLAN_REVIEW:
        return _review_approved(model.plan_review)
    if phase == LifecyclePhase.BUILD_STARTED:
        return bool(model.build_completed_at)
    if phase == LifecyclePhase.BUILD_COMPLETE:
        return model.build_review.verdict in ("approve", "changes_requested")
    if phase == LifecyclePhase.REVIEW_CHANGES_REQUESTED:
        return False
    if phase == LifecyclePhase.REVIEW_APPROVED:
        return model.finalize.status == "ready"
    if phase == LifecyclePhase.FINALIZE_READY:
        return False
    return False


def invalidate_downstream_on_refine(model: TodoState, refined_artifact: str) -> None:
    """Clear downstream approvals and review verdicts after an artifact rewrite."""
    approvals = model.approvals
    if refined_artifact == ARTIFACT_PRD:
        approvals.prd_approved = ApprovalStamp()
        approvals.architecture_approved = ApprovalStamp()
        approvals.plan_approved = ApprovalStamp()
        approvals.architecture_skipped = None
        _clear_prepare_review(model.architecture_review)
        _clear_prepare_review(model.plan_review)
        for key in (ARTIFACT_PRD, ARTIFACT_ARCHITECTURE, ARTIFACT_IMPLEMENTATION_PLAN):
            approvals.drift_reviewed.pop(key, None)
    elif refined_artifact == ARTIFACT_ARCHITECTURE:
        approvals.architecture_approved = ApprovalStamp()
        approvals.plan_approved = ApprovalStamp()
        _clear_prepare_review(model.architecture_review)
        _clear_prepare_review(model.plan_review)
        for key in (ARTIFACT_ARCHITECTURE, ARTIFACT_IMPLEMENTATION_PLAN):
            approvals.drift_reviewed.pop(key, None)
    elif refined_artifact == ARTIFACT_DIAGNOSIS:
        approvals.plan_approved = ApprovalStamp()
        _clear_prepare_review(model.plan_review)
        for key in (ARTIFACT_DIAGNOSIS, ARTIFACT_IMPLEMENTATION_PLAN):
            approvals.drift_reviewed.pop(key, None)
    elif refined_artifact == ARTIFACT_IMPLEMENTATION_PLAN:
        approvals.plan_approved = ApprovalStamp()
        _clear_prepare_review(model.plan_review)
        approvals.drift_reviewed.pop(ARTIFACT_IMPLEMENTATION_PLAN, None)


def _clear_prepare_target(model: TodoState, target: LifecyclePhase) -> None:
    _reset_dor(model)
    _clear_work_entry_state(model)
    if target == LifecyclePhase.DRAFT:
        model.approvals = type(model.approvals)()
        _clear_prepare_review(model.architecture_review)
        _clear_prepare_review(model.plan_review)
    elif target == LifecyclePhase.PRD_DRAFTING:
        invalidate_downstream_on_refine(model, ARTIFACT_PRD)
    elif target in (LifecyclePhase.ARCHITECTURE_DRAFTING, LifecyclePhase.ARCHITECTURE_REVIEW):
        invalidate_downstream_on_refine(model, ARTIFACT_ARCHITECTURE)
    elif target == LifecyclePhase.DIAGNOSE:
        invalidate_downstream_on_refine(model, ARTIFACT_DIAGNOSIS)
    elif target in (LifecyclePhase.PLAN_DRAFTING, LifecyclePhase.PLAN_REVIEW):
        invalidate_downstream_on_refine(model, ARTIFACT_IMPLEMENTATION_PLAN)


def normalize_mark_phase(model: TodoState, target: LifecyclePhase, *, worktree_cwd: str | None = None) -> None:
    """Clear current/downstream authority and persist ``target`` as the pointer."""
    _ = worktree_cwd
    if is_prepare_lifecycle_phase(target):
        _clear_prepare_target(model, target)
    else:
        if target == LifecyclePhase.BUILD_STARTED:
            model.build_completed_at = ""
            _clear_build_review(model)
            _reset_finalize(model)
            model.build_start_base_sha = ""
        elif target == LifecyclePhase.BUILD_COMPLETE:
            _clear_build_review(model)
            _reset_finalize(model)
        elif target in (LifecyclePhase.REVIEW_CHANGES_REQUESTED, LifecyclePhase.REVIEW_APPROVED):
            _reset_finalize(model)
    model.lifecycle_phase = target.value
