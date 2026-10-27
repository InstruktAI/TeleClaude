"""Canonical lifecycle helpers.

This module owns lifecycle phase coercion, projection, and the v2 prepare
derivation table. Prepare no longer persists pair identity or grounding state;
it derives progress from artifacts, review verdicts, approval stamps, skip
stamps, and drift-review stamps.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_PRD,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
    STATE_KEY_TASK_PLAN,
)
from teleclaude.core.db import SessionIdentityError, get_session_identity_sync, resolve_session_principal
from teleclaude.core.next_machine.git_ops import (
    DRIFT_COSMETIC,
    DRIFT_FRESH,
    DRIFT_PENDING,
    DRIFT_SUBSTANTIVE,
    ArtifactDriftStatus,
    DependencyStatusReader,
    _parse_iso_datetime,
    derive_age_drift,
    derive_artifact_drift,
    derive_dependency_artifact_drift,
    derive_owned_snippet_drift,
    derive_upstream_artifact_drift,
    derive_upstream_snippet_drift,
    get_head_commit,
)
from teleclaude.core.next_machine.kinds import (
    BUG_DIAGNOSE_KINDS,
    FAST_TRACK_PREPARED_KINDS,
    FEATURE_PREPARE_KINDS,
    KIND_TASK,
    PLAN_ONLY_PREPARE_KINDS,
)
from teleclaude.core.next_machine.provenance import read_dependency_artifact_snapshot
from teleclaude.core.next_machine.review_evidence import (
    REVIEW_EVIDENCE_ARTIFACTS,
    ReviewEvidenceReason,
)
from teleclaude.core.next_machine.review_evidence import (
    build_review_binding_current as _build_review_binding_current,
)
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.session_identity import get_session_id
from teleclaude.types.lifecycle import (
    LEGACY_LIFECYCLE_PHASE_NORMALIZATION,
    LIFECYCLE_PHASE_ORDER,
    PREPARE_LIFECYCLE_PHASES,
    WORK_LIFECYCLE_PHASES,
    DriftClass,
    LifecyclePhase,
)
from teleclaude.types.todo_kind import ALL_DUMP_KINDS, TodoKind
from teleclaude.types.todos import (
    ApprovalStamp,
    ArtifactEntry,
    BuildReviewState,
    FinalizeStatus,
    ReviewVerdictState,
    TodoState,
)

__all__ = [
    "LIFECYCLE_PHASE_ORDER",
    "PREPARE_LIFECYCLE_PHASES",
    "READY_BAND_PHASES",
    "WORK_LIFECYCLE_PHASES",
    "_DRIFT_MATRIX_ARTIFACTS",
    "_DRIFT_REROUTABLE_CLASSES_BY_ARTIFACT",
    "ApprovalGate",
    "DriftResult",
    "LifecyclePhase",
    "adopt_prepare_handoff_phase",
    "apply_authoritative_signal",
    "build_review_binding_current",
    "coerce_lifecycle_phase",
    "collapse_drift",
    "derive_lifecycle_drift",
    "diagnosis_settled_current",
    "effective_hold",
    "is_in_prepare_lane",
    "is_in_work_lane",
    "is_prepare_lifecycle_phase",
    "is_ready_band_eligible",
    "is_ready_for_work",
    "is_settled_ok_phase",
    "is_work_lifecycle_phase",
    "lifecycle_phase_index",
    "pending_approval_gate",
    "plan_review_current",
    "prd_approval_current",
    "prepare_blockers",
    "prepare_review_verdict_from_state",
    "require_lifecycle_phase",
    "reset_finalize",
]

_ArtifactPresence = Mapping[str, bool]
_FEATURE_KINDS = FEATURE_PREPARE_KINDS
_EMPTY_TEXT = ""
_INVALID_WORK_KIND_REASON = "unsupported todo kind"
_PREPARED_SESSION_ID_REQUIRED_ERROR = "prepared transition requires a completing TeleClaude session identity"

# Pre-finalize phases from which a build_review verdict re-derives the phase.
# FINALIZE_READY and later are absent: finalized work is handed to the
# integrator and is never reopened by a later verdict.
_BUILD_REVIEW_VERDICT_PHASES = (
    LifecyclePhase.BUILD_COMPLETE,
    LifecyclePhase.REVIEW_APPROVED,
    LifecyclePhase.REVIEW_CHANGES_REQUESTED,
)
READY_BAND_PHASES: frozenset[LifecyclePhase] = frozenset(
    {
        LifecyclePhase.PREPARED,
        LifecyclePhase.BUILD_STARTED,
        LifecyclePhase.BUILD_COMPLETE,
        LifecyclePhase.REVIEW_CHANGES_REQUESTED,
        LifecyclePhase.REVIEW_APPROVED,
    }
)


class ApprovalGate(StrEnum):
    """A pending human-approval gate within the prepare lane.

    Each member identifies which underlying approval the ``A`` control routes
    to. Membership is derived from current todo state and never stored.
    """

    PRD = "prd"
    CREATIVE_DESIGN_SPEC = "creative_design_spec"
    CREATIVE_ART = "creative_art"
    CREATIVE_VISUALS = "creative_visuals"


# Creative section key -> (gate, flag that, when set, clears the gate).
_CREATIVE_APPROVAL_GATES: tuple[tuple[str, ApprovalGate, str], ...] = (
    ("design_spec", ApprovalGate.CREATIVE_DESIGN_SPEC, "confirmed"),
    ("art", ApprovalGate.CREATIVE_ART, "approved"),
    ("visuals", ApprovalGate.CREATIVE_VISUALS, "approved"),
)


_ALL_DRIFT_CLASSES = (
    DriftClass.CODE,
    DriftClass.UPSTREAM_ARTIFACT,
    DriftClass.OWNED_SNIPPET,
    DriftClass.UPSTREAM_SNIPPET,
    DriftClass.AGE,
)
_IMPLEMENTATION_PLAN_DRIFT_CLASSES = (
    DriftClass.CODE,
    DriftClass.UPSTREAM_ARTIFACT,
    DriftClass.UPSTREAM_SNIPPET,
    DriftClass.DEPENDENCY_ARTIFACT,
    DriftClass.AGE,
)
_DRIFT_TRACKED_ARTIFACTS: tuple[tuple[str, str, tuple[DriftClass, ...]], ...] = (
    (STATE_KEY_PRD, STATE_KEY_PRD, _ALL_DRIFT_CLASSES),
    (STATE_KEY_ARCHITECTURE, STATE_KEY_ARCHITECTURE, _ALL_DRIFT_CLASSES),
    (ARTIFACT_IMPLEMENTATION_PLAN, STATE_KEY_IMPLEMENTATION_PLAN, _IMPLEMENTATION_PLAN_DRIFT_CLASSES),
)
_DRIFT_MATRIX_ARTIFACTS = frozenset(name for name, _, _ in _DRIFT_TRACKED_ARTIFACTS)
_DRIFT_REROUTABLE_CLASSES_BY_ARTIFACT = {
    name: frozenset(applicable_classes) for name, _, applicable_classes in _DRIFT_TRACKED_ARTIFACTS
}
_DRIFT_PRIORITY: tuple[ArtifactDriftStatus, ...] = (
    DRIFT_SUBSTANTIVE,
    DRIFT_PENDING,
    DRIFT_COSMETIC,
    DRIFT_FRESH,
)
DriftResult = dict[str, dict[DriftClass, ArtifactDriftStatus]]


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


def is_ready_for_work(*, kind: TodoKind, lifecycle_phase: str | None) -> tuple[bool, str]:
    """Authoritative gate for entering or resuming the work lane."""
    if kind not in ALL_DUMP_KINDS:
        return False, _INVALID_WORK_KIND_REASON
    if kind == KIND_TASK:
        return False, "task todos are executed by the task lane, not the SDLC work lane"
    phase = coerce_lifecycle_phase(lifecycle_phase)
    if phase is None:
        return False, f"unknown lifecycle_phase {lifecycle_phase!r}"
    if phase not in LIFECYCLE_PHASE_ORDER:
        return False, f"lifecycle_phase {phase.value!r} is outside the SDLC work lane"
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


def is_in_work_lane(phase: LifecyclePhase, *, plan_review_is_current: bool) -> bool:
    """Return whether an active item is past the prepare/work boundary.

    The boundary the lifecycle runner dispatches on: the phase has reached ``PREPARED`` and the plan
    review still binds the plan. A prepared item whose plan review went stale is prepared again.
    ``is_in_prepare_lane`` answers a different question (it counts ``PREPARED`` itself as prepare).
    """
    return plan_review_is_current and lifecycle_phase_index(phase) >= lifecycle_phase_index(LifecyclePhase.PREPARED)


def is_settled_ok_phase(lifecycle_phase: str | None) -> bool:
    """Phase represents a settled positive state used for "ok" rendering."""
    phase = coerce_lifecycle_phase(lifecycle_phase)
    return phase in (LifecyclePhase.PREPARED, LifecyclePhase.REVIEW_APPROVED, LifecyclePhase.FINALIZE_READY)


def _read_creative_state(todo_state: TodoState | Mapping[str, object]) -> Mapping[str, object]:
    raw: object = todo_state.creative if isinstance(todo_state, TodoState) else todo_state.get("creative")
    return raw if isinstance(raw, Mapping) else {}


def pending_approval_gate(todo_state: TodoState | Mapping[str, object]) -> ApprovalGate | None:
    """Return the pending human-approval gate for a todo, if any.

    Consults only the gate-bearing state — the lifecycle phase (PRD human
    approval) and the creative sections (design-spec / art / visuals awaiting
    their flag). It never reads ``hold`` or ``active_runner``: approval and
    hold are independent controls with no precedence between them.
    """
    if isinstance(todo_state, TodoState):
        phase = coerce_lifecycle_phase(todo_state.lifecycle_phase)
    else:
        phase = coerce_lifecycle_phase(todo_state.get("lifecycle_phase"))

    if phase == LifecyclePhase.PRD_HUMAN_APPROVAL:
        if not isinstance(todo_state, TodoState) or not prd_approval_current(todo_state):
            return ApprovalGate.PRD

    creative = _read_creative_state(todo_state)
    for section, gate, flag in _CREATIVE_APPROVAL_GATES:
        section_state = creative.get(section)
        if isinstance(section_state, Mapping) and section_state.get(flag) is not True:
            return gate
    return None


def effective_hold(*, hold: bool) -> bool:
    """Return whether a stored hold flag currently acts as the dispatch brake.

    Hold is durable operator intent, independent of kind, lifecycle phase, and
    autostart policy. It is pure over the stored flag so the runner, projection,
    and UI all observe the same brake.
    """
    return bool(hold)


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


def _artifact_digest(model: TodoState, key: str) -> str:
    entry = cast(ArtifactEntry, getattr(model.artifacts, key))
    return entry.digest


def _artifact_present(model: TodoState, key: str, *, artifact_presence: _ArtifactPresence | None = None) -> bool:
    if artifact_presence is not None and key in artifact_presence:
        return artifact_presence[key]
    return _artifact_exists(model, key)


def _intent_artifact_exists(model: TodoState) -> bool:
    return _artifact_exists(model, STATE_KEY_PRD)


def _intent_artifact_present(
    model: TodoState,
    *,
    artifact_presence: _ArtifactPresence | None = None,
) -> bool:
    return _artifact_present(model, STATE_KEY_PRD, artifact_presence=artifact_presence)


def _session_principal(session_id: str) -> str:
    if session_id.startswith("human:"):
        return session_id
    session = get_session_identity_sync(str(MAIN_DB_PATH), session_id)
    if session is None:
        return ""
    try:
        principal, _role = resolve_session_principal(session)
    except SessionIdentityError:
        return ""
    return principal


def _approval_is_human(stamp: ApprovalStamp) -> bool:
    if not stamp.approved:
        return False
    if not stamp.caller_session_id:
        return False
    return _session_principal(stamp.caller_session_id).startswith("human:")


def diagnosis_settled_current(stamp: ApprovalStamp, current_digest: str) -> bool:
    """Return True when the bug lane's settlement stamp still matches the diagnosis.

    Unlike the PRD gate, this stamp is never human-gated — the driving prepare
    session that settles a diagnosis is an agent. Currency is digest-bound: a
    stamp binds to the artifact's digest at settlement time, and any later
    revision (including the field's absence) leaves it not current, returning
    the phase to DIAGNOSE.
    """
    return stamp.approved and bool(stamp.approved_digest) and stamp.approved_digest == current_digest


def _pending_substantive_prd_drift(model: TodoState) -> bool:
    """Return True when an unresolved substantive upstream PRD drift supersedes the approval.

    Scoped to the **upstream-artifact** (input) drift class: only an intent-level
    input change re-opens the human gate. A substantive verdict driven by the PRD's
    downstream evidence (code/snippets/deps) leaves the input digest unchanged, so
    ``derive_upstream_artifact_drift`` derives fresh and the gate stays advanced. The
    drift wins over a legacy approval that carries no ``approved_at`` or no drift
    timestamp; otherwise it wins only when stamped after the approval — a re-approval
    that post-dates the drift resolves it.
    """
    if derive_upstream_artifact_drift(model, ARTIFACT_PRD) != DRIFT_SUBSTANTIVE:
        return False
    approved_at = model.approvals.prd_approved.approved_at
    if not approved_at:
        return True
    drift = model.approvals.drift_reviewed.get(ARTIFACT_PRD)
    if drift is None or not drift.stamped_at:
        return True
    return _parse_iso_datetime(drift.stamped_at) > _parse_iso_datetime(approved_at)


def _approval_current(stamp: ApprovalStamp, current_digest: str, *, pending_substantive_drift: bool = False) -> bool:
    """Return True when a human approval still matches the approved PRD content.

    The digest binds the human approval to the PRD content that was approved.
    Divergence re-opens the approval gate; an empty digest preserves legacy
    approval state written before the digest field existed. A pending substantive
    upstream drift re-opens the gate regardless of digest, so an intent-level
    change re-derives and re-approves the PRD rather than skipping ahead.
    """
    if not _approval_is_human(stamp):
        return False
    if pending_substantive_drift:
        return False
    if not stamp.approved_digest:
        return True
    return stamp.approved_digest == current_digest


def prd_approval_current(model: TodoState) -> bool:
    """Return whether the persisted PRD approval remains current for ``model``."""
    return _approval_current(
        model.approvals.prd_approved,
        _artifact_digest(model, STATE_KEY_PRD),
        pending_substantive_drift=_pending_substantive_prd_drift(model),
    )


def _review_current(review: ReviewVerdictState, current_target_digest: str, current_report_digest: str) -> bool:
    """Return whether an approving prepare verdict binds both current digests."""
    return (
        review.verdict == "approve"
        and bool(review.reviewed_target_digest)
        and bool(review.review_report_digest)
        and review.reviewed_target_digest == current_target_digest
        and review.review_report_digest == current_report_digest
    )


def build_review_binding_current(
    build_review: BuildReviewState,
    worktree_cwd: str,
    current_report_digest: str,
) -> ReviewEvidenceReason:
    """Classify whether a build-review verdict still binds todo work and its report."""
    return _build_review_binding_current(build_review, worktree_cwd, current_report_digest)


def plan_review_current(state: TodoState | Mapping[str, object]) -> bool:
    """Return whether raw-state callers can prove the plan review is current.

    Prepare phase derivation owns the stricter report-artifact binding in
    ``_review_current``. Runner, manual-start, and dependency callers only
    receive durable state, so this projection deliberately validates the
    approving verdict, non-empty review evidence, and current plan target.
    """
    try:
        model = state if isinstance(state, TodoState) else TodoState.model_validate(state)
    except ValueError:
        return False
    current_plan_digest = model.artifacts.implementation_plan.digest
    review = model.plan_review
    return (
        bool(current_plan_digest)
        and review.verdict == "approve"
        and bool(review.reviewed_target_digest)
        and bool(review.review_report_digest)
        and review.reviewed_target_digest == current_plan_digest
    )


def _current_report_digest(review_phase: str, report_digests: Mapping[str, str] | None) -> str:
    if report_digests is None:
        return ""
    report_name = REVIEW_EVIDENCE_ARTIFACTS[review_phase].report_artifact_name
    return report_digests.get(report_name, "")


def _clear_build_review(model: TodoState) -> None:
    model.build_review.verdict = ""
    model.build_review.reviewed_at = ""
    model.build_review.dispatch_head = ""
    model.build_review.reviewed_target_digest = ""
    model.build_review.review_report_digest = ""
    model.build_review.caller_session_id = ""


def _reset_finalize(model: TodoState) -> None:
    model.finalize.status = FinalizeStatus.PENDING
    model.finalize.ready_at = ""


def reset_finalize(model: TodoState) -> None:
    """Clear the lifecycle-owned finalize readiness projection."""
    _reset_finalize(model)


async def derive_lifecycle_drift(
    slug: str,
    model: TodoState,
    *,
    repo_root: str | None = None,
    todos_db: DependencyStatusReader,
    snippet_digest_fn: Callable[[str], str],
    writer: object,
) -> DriftResult:
    """Return per-artifact, per-class drift for every present tracked artifact."""
    _ = writer
    drift: DriftResult = {}
    for artifact_name, state_key, applicable_classes in _DRIFT_TRACKED_ARTIFACTS:
        entry = getattr(model.artifacts, state_key)
        if not entry.digest and not entry.produced_at:
            continue
        class_drift: dict[DriftClass, ArtifactDriftStatus] = {}
        for class_name in applicable_classes:
            if class_name == DriftClass.CODE:
                class_drift[class_name] = derive_artifact_drift(
                    entry,
                    model.approvals.drift_reviewed.get(artifact_name),
                    repo_root or "",
                )
            elif class_name == DriftClass.UPSTREAM_ARTIFACT:
                class_drift[class_name] = derive_upstream_artifact_drift(model, artifact_name)
            elif class_name == DriftClass.OWNED_SNIPPET:
                class_drift[class_name] = derive_owned_snippet_drift(
                    model,
                    artifact_name,
                    snippet_digest_fn=snippet_digest_fn,
                )
            elif class_name == DriftClass.UPSTREAM_SNIPPET:
                class_drift[class_name] = derive_upstream_snippet_drift(
                    model,
                    artifact_name,
                    snippet_digest_fn=snippet_digest_fn,
                )
            elif class_name == DriftClass.DEPENDENCY_ARTIFACT:
                if entry.dependency_artifact_digests:
                    dependency_snapshot = await read_dependency_artifact_snapshot(todos_db, slug)
                    class_drift[class_name] = derive_dependency_artifact_drift(model, dependency_snapshot)
                else:
                    class_drift[class_name] = DRIFT_FRESH
            elif class_name == DriftClass.AGE:
                class_drift[class_name] = derive_age_drift(
                    model,
                    artifact_name,
                    age_window_seconds=None,
                    drift_reviewed_stamp=model.approvals.drift_reviewed.get(artifact_name),
                )
        drift[artifact_name] = class_drift
    return drift


def collapse_drift(
    result: DriftResult,
) -> dict[str, ArtifactDriftStatus]:
    """Collapse per-class drift to per-artifact status by priority."""
    collapsed: dict[str, ArtifactDriftStatus] = {}
    for artifact_name, class_statuses in result.items():
        for status in _DRIFT_PRIORITY:
            if status in class_statuses.values():
                collapsed[artifact_name] = status
                break
    return collapsed


def prepare_blockers(
    model: TodoState, *, repo_root: str | None = None, artifact_write_timestamps: Mapping[str, str]
) -> list[str]:
    """Return deterministic prepare blockers for advisory payloads and phase derivation."""
    _ = repo_root
    return _non_drift_prepare_blockers(model, artifact_write_timestamps=artifact_write_timestamps)


def _non_drift_prepare_blockers(model: TodoState, *, artifact_write_timestamps: Mapping[str, str]) -> list[str]:
    blockers: list[str] = []
    blockers.extend(_missing_upstream_blockers(model))
    blockers.extend(_review_remediation_blockers(model, artifact_write_timestamps=artifact_write_timestamps))
    blockers.extend(_upcycle_blockers(model))
    return blockers


def _missing_upstream_blockers(model: TodoState) -> list[str]:
    """Return blockers for artifacts whose required upstream artifact is absent."""
    blockers: list[str] = []
    if _artifact_exists(model, STATE_KEY_ARCHITECTURE) and not _intent_artifact_exists(model):
        blockers.append("architecture artifact is present but required upstream prd intent is missing")
    if (
        model.kind in _FEATURE_KINDS
        and _artifact_exists(model, STATE_KEY_IMPLEMENTATION_PLAN)
        and not _intent_artifact_exists(model)
    ):
        blockers.append("implementation-plan artifact is present but required upstream prd intent is missing")
    return blockers


def _is_review_remediation_pending(verdict: str, *, artifact_written_at: str, reviewed_at: str) -> bool:
    if verdict not in ("changes_requested", "needs_work"):
        return False
    return not artifact_written_at or bool(reviewed_at and artifact_written_at <= reviewed_at)


def _review_remediation_blockers(model: TodoState, *, artifact_write_timestamps: Mapping[str, str]) -> list[str]:
    blockers: list[str] = []
    review_pairs = (
        (STATE_KEY_PRD, model.prd_review),
        (STATE_KEY_ARCHITECTURE, model.architecture_review),
        (STATE_KEY_IMPLEMENTATION_PLAN, model.plan_review),
    )
    for artifact_key, review in review_pairs:
        if _is_review_remediation_pending(
            review.verdict,
            artifact_written_at=artifact_write_timestamps.get(artifact_key, ""),
            reviewed_at=review.reviewed_at,
        ):
            blockers.append(f"{artifact_key} review requested changes with no newer artifact write")
    return blockers


def prepare_review_verdict_from_state(
    state: Mapping[str, object], *, artifact_write_timestamps: Mapping[str, str]
) -> str | None:
    """Return the review-remediation verdict pending on this raw state, or None.

    This is a review-remediation *detector*: it reports the PRD/architecture/plan
    review verdict that is awaiting remediation (the common BLOCKED cause), and is
    intentionally silent about the other BLOCKED causes. It does NOT itself assert
    the todo is BLOCKED — callers guard on LifecyclePhase.BLOCKED before rendering.
    Recency is read from ``artifact_write_timestamps`` — each artifact's durable
    stored-write timestamp, supplied by the caller from the artifact record itself
    — never from state's own provenance-sync timestamp, which records when a sync
    routine last ran rather than when the artifact was actually written.
    """
    for artifact_key, review_key in (
        (STATE_KEY_PRD, "prd_review"),
        (STATE_KEY_ARCHITECTURE, "architecture_review"),
        (STATE_KEY_IMPLEMENTATION_PLAN, "plan_review"),
    ):
        review = state.get(review_key)
        if not isinstance(review, Mapping):
            continue
        verdict = review.get("verdict", "")
        reviewed_at = review.get("reviewed_at", "")
        if isinstance(verdict, str) and _is_review_remediation_pending(
            verdict,
            artifact_written_at=artifact_write_timestamps.get(artifact_key, ""),
            reviewed_at=reviewed_at if isinstance(reviewed_at, str) else "",
        ):
            return verdict
    return None


def _upcycle_blockers(model: TodoState) -> list[str]:
    if model.schema_version < 9:
        return ["todo state could not be upcycled to schema_version 9"]
    return []


def _plan_only_phase(
    model: TodoState,
    *,
    artifact_presence: _ArtifactPresence | None,
    repo_root: str | None,
    report_digests: Mapping[str, str] | None,
    artifact_write_timestamps: Mapping[str, str],
) -> LifecyclePhase:
    if not _artifact_present(model, STATE_KEY_IMPLEMENTATION_PLAN, artifact_presence=artifact_presence):
        return LifecyclePhase.PLAN_DRAFTING
    if model.artifacts.implementation_plan.seeded:
        return LifecyclePhase.PLAN_DRAFTING
    if not _review_current(
        model.plan_review,
        _artifact_digest(model, STATE_KEY_IMPLEMENTATION_PLAN),
        _current_report_digest("plan_review", report_digests),
    ):
        if model.plan_review.cleared_by_substantive_drift:
            return LifecyclePhase.PLAN_DRAFTING
        return LifecyclePhase.PLAN_REVIEW
    if prepare_blockers(model, repo_root=repo_root, artifact_write_timestamps=artifact_write_timestamps):
        return LifecyclePhase.BLOCKED
    return LifecyclePhase.PREPARED


def _task_phase(model: TodoState, *, artifact_presence: _ArtifactPresence | None) -> LifecyclePhase:
    if _artifact_present(model, STATE_KEY_TASK_PLAN, artifact_presence=artifact_presence):
        return LifecyclePhase.PREPARED
    return LifecyclePhase.TASK_PLAN_DRAFTING


def _diagnose_phase(
    model: TodoState,
    *,
    artifact_presence: _ArtifactPresence | None,
    repo_root: str | None,
    report_digests: Mapping[str, str] | None,
    artifact_write_timestamps: Mapping[str, str],
) -> LifecyclePhase:
    if not _artifact_present(model, STATE_KEY_DIAGNOSIS, artifact_presence=artifact_presence):
        return LifecyclePhase.DIAGNOSE
    if not diagnosis_settled_current(model.approvals.diagnosis_settled, _artifact_digest(model, STATE_KEY_DIAGNOSIS)):
        return LifecyclePhase.DIAGNOSE
    return _plan_only_phase(
        model,
        artifact_presence=artifact_presence,
        repo_root=repo_root,
        report_digests=report_digests,
        artifact_write_timestamps=artifact_write_timestamps,
    )


def _feature_phase(
    model: TodoState,
    *,
    artifact_presence: _ArtifactPresence | None,
    repo_root: str | None,
    report_digests: Mapping[str, str] | None,
    artifact_write_timestamps: Mapping[str, str],
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
    if not has_prd:
        return LifecyclePhase.PRD_DRAFTING
    if not _review_current(
        model.prd_review, _artifact_digest(model, STATE_KEY_PRD), _current_report_digest("prd_review", report_digests)
    ):
        return LifecyclePhase.PRD_REVIEW
    if not prd_approval_current(model):
        return LifecyclePhase.PRD_HUMAN_APPROVAL

    architecture_skipped = model.approvals.architecture_skipped is not None

    if not architecture_skipped:
        if not _artifact_present(model, STATE_KEY_ARCHITECTURE, artifact_presence=artifact_presence):
            return LifecyclePhase.ARCHITECTURE_DRAFTING
        if not _review_current(
            model.architecture_review,
            _artifact_digest(model, STATE_KEY_ARCHITECTURE),
            _current_report_digest("architecture_review", report_digests),
        ):
            if model.architecture_review.cleared_by_substantive_drift:
                return LifecyclePhase.ARCHITECTURE_DRAFTING
            return LifecyclePhase.ARCHITECTURE_REVIEW

    return _plan_only_phase(
        model,
        artifact_presence=artifact_presence,
        repo_root=repo_root,
        report_digests=report_digests,
        artifact_write_timestamps=artifact_write_timestamps,
    )


def adopt_prepare_handoff_phase(
    model: TodoState,
    *,
    artifact_presence: _ArtifactPresence | None = None,
    repo_root: str | None = None,
    report_digests: Mapping[str, str],
    artifact_write_timestamps: Mapping[str, str],
    prepared_session_id: str | None = None,
    prepared_withheld: Callable[[], bool] | None = None,
) -> LifecyclePhase:
    """Choose the prepare pointer from existing authoritative state and artifacts.

    ``prepared_withheld`` is consulted only when the derivation would move the
    stored phase into ``PREPARED``. When it answers True the transition does not
    happen: the current phase is returned and no ``PREPARED`` provenance is stamped.

    A todo already in the work lane keeps its phase when the derivation reaches
    ``PREPARED``: still-valid preparation evidence never returns work in flight
    to the start of the work lane. Invalidated preparation still derives its
    earlier prepare phase.
    """
    if model.kind == KIND_TASK:
        target = _task_phase(model, artifact_presence=artifact_presence)
    elif model.kind in FAST_TRACK_PREPARED_KINDS:
        target = LifecyclePhase.PREPARED
    elif _non_drift_prepare_blockers(model, artifact_write_timestamps=artifact_write_timestamps):
        target = LifecyclePhase.BLOCKED
    elif model.kind in BUG_DIAGNOSE_KINDS:
        target = _diagnose_phase(
            model,
            artifact_presence=artifact_presence,
            repo_root=repo_root,
            report_digests=report_digests,
            artifact_write_timestamps=artifact_write_timestamps,
        )
    elif model.kind in PLAN_ONLY_PREPARE_KINDS:
        target = _plan_only_phase(
            model,
            artifact_presence=artifact_presence,
            repo_root=repo_root,
            report_digests=report_digests,
            artifact_write_timestamps=artifact_write_timestamps,
        )
    else:
        target = _feature_phase(
            model,
            artifact_presence=artifact_presence,
            repo_root=repo_root,
            report_digests=report_digests,
            artifact_write_timestamps=artifact_write_timestamps,
        )
    if target is LifecyclePhase.PREPARED and is_work_lifecycle_phase(model.lifecycle_phase):
        return model.lifecycle_phase
    if target is LifecyclePhase.PREPARED and model.lifecycle_phase is not LifecyclePhase.PREPARED:
        if prepared_withheld is not None and prepared_withheld():
            return model.lifecycle_phase
        completing_session_id = prepared_session_id or get_session_id()
        if not completing_session_id:
            raise ValueError(_PREPARED_SESSION_ID_REQUIRED_ERROR)
        model.prepared_session_id = completing_session_id
    return target


def _move_to(model: TodoState, target: LifecyclePhase) -> LifecyclePhase:
    model.lifecycle_phase = target
    return target


def apply_authoritative_signal(
    model: TodoState,
    signal: str,
    *,
    phase: str | None = None,
    worktree_cwd: str | None = None,
    artifact_write_timestamps: Mapping[str, str],
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
        "task_approved",
    }:
        return _move_to(
            model,
            adopt_prepare_handoff_phase(model, report_digests={}, artifact_write_timestamps=artifact_write_timestamps),
        )

    if signal == "verdict":
        if phase == "build_review" and current in _BUILD_REVIEW_VERDICT_PHASES:
            if model.build_review.verdict == "approve":
                return _move_to(model, LifecyclePhase.REVIEW_APPROVED)
            if model.build_review.verdict == "changes_requested":
                model.build_completed_at = ""
                model.build_gate_claim_at = ""
                return _move_to(model, LifecyclePhase.REVIEW_CHANGES_REQUESTED)
        return _move_to(
            model,
            adopt_prepare_handoff_phase(model, report_digests={}, artifact_write_timestamps=artifact_write_timestamps),
        )

    if signal == "build_started" and current == LifecyclePhase.PREPARED:
        model.build_start_base_sha = get_head_commit(worktree_cwd or "")
        if not model.build_plan_digest:
            model.build_plan_digest = model.artifacts.implementation_plan.digest
        model.build_completed_at = ""
        model.build_gate_claim_at = _EMPTY_TEXT
        _clear_build_review(model)
        _reset_finalize(model)
        return _move_to(model, LifecyclePhase.BUILD_STARTED)

    if signal == "build_complete" and current in (
        LifecyclePhase.BUILD_STARTED,
        LifecyclePhase.REVIEW_CHANGES_REQUESTED,
        LifecyclePhase.REVIEW_APPROVED,
    ):
        model.build_plan_digest = model.artifacts.implementation_plan.digest
        model.build_completed_at = now
        _reset_finalize(model)
        _clear_build_review(model)
        return _move_to(model, LifecyclePhase.BUILD_COMPLETE)

    if signal == "delivery_evidence":
        model.phase = "delivered"
        model.integration_phase = "delivered"
        model.active_runner = None
        model.manually_started = False
        return _move_to(model, LifecyclePhase.DELIVERED)

    if (
        signal == "finalize_ready"
        and current == LifecyclePhase.REVIEW_APPROVED
        and model.finalize.status is FinalizeStatus.READY
    ):
        return _move_to(model, LifecyclePhase.FINALIZE_READY)

    return current
