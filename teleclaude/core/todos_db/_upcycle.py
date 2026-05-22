"""Pure upcycle helpers for persisted todo state blobs."""

from __future__ import annotations

from typing import cast

from teleclaude.core.next_machine.kinds import FAST_TRACK_PREPARED_KINDS, KIND_DRAFT, KIND_FEATURE, KIND_TODO
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState

LATEST_TODO_STATE_SCHEMA_VERSION = 4
_V0_SCHEMA_VERSION = 0
_V1_SCHEMA_VERSION = 1
_V2_SCHEMA_VERSION = 2
_V3_SCHEMA_VERSION = 3
_LEGACY_HANDED_OFF_PHASE = "handed_off"

_LEGACY_CURRENT_TO_LIFECYCLE: dict[str, str] = {
    "draft": LifecyclePhase.DRAFT.value,
    "pending": LifecyclePhase.PRD_DRAFTING.value,
    "input_assessment": LifecyclePhase.PRD_DRAFTING.value,
    "triangulation": LifecyclePhase.PRD_DRAFTING.value,
    "requirements_review": LifecyclePhase.PRD_DRAFTING.value,
    "requirements_human_approval": LifecyclePhase.PRD_DRAFTING.value,
    "test_spec_build": LifecyclePhase.ARCHITECTURE_REVIEW.value,
    "test_spec_review": LifecyclePhase.ARCHITECTURE_REVIEW.value,
    "plan_drafting": LifecyclePhase.PLAN_DRAFTING.value,
    "plan_review": LifecyclePhase.PLAN_DRAFTING.value,
    "gate": LifecyclePhase.PREPARED.value,
    "grounding_check": LifecyclePhase.PREPARED.value,
    "re_grounding": LifecyclePhase.PREPARED.value,
    "prepared": LifecyclePhase.PREPARED.value,
    "build": LifecyclePhase.BUILD_STARTED.value,
    "build_started": LifecyclePhase.BUILD_STARTED.value,
    "build_complete": LifecyclePhase.BUILD_COMPLETE.value,
    "review_changes_requested": LifecyclePhase.REVIEW_CHANGES_REQUESTED.value,
    "review_approved": LifecyclePhase.REVIEW_APPROVED.value,
    "finalize_ready": LifecyclePhase.FINALIZE_READY.value,
    "finalize_handed_off": LifecyclePhase.FINALIZE_READY.value,
    _LEGACY_HANDED_OFF_PHASE: LifecyclePhase.FINALIZE_READY.value,
    "delivered": LifecyclePhase.FINALIZE_READY.value,
}

_V2_TO_V3_PHASE: dict[str, str] = {
    "draft": LifecyclePhase.DRAFT.value,
    "input_assessment": LifecyclePhase.DRAFT.value,
    "triangulation": LifecyclePhase.DRAFT.value,
    "requirements_review": LifecyclePhase.PRD_DRAFTING.value,
    "requirements_human_approval": LifecyclePhase.PRD_DRAFTING.value,
    "test_spec_build": LifecyclePhase.ARCHITECTURE_REVIEW.value,
    "test_spec_review": LifecyclePhase.ARCHITECTURE_REVIEW.value,
    "plan_drafting": LifecyclePhase.PLAN_DRAFTING.value,
    "plan_review": LifecyclePhase.PLAN_DRAFTING.value,
    "gate": LifecyclePhase.PREPARED.value,
    "grounding_check": LifecyclePhase.PREPARED.value,
    "re_grounding": LifecyclePhase.PREPARED.value,
    "prepared": LifecyclePhase.PREPARED.value,
    "build_started": LifecyclePhase.BUILD_STARTED.value,
    "build_complete": LifecyclePhase.BUILD_COMPLETE.value,
    "review_changes_requested": LifecyclePhase.REVIEW_CHANGES_REQUESTED.value,
    "review_approved": LifecyclePhase.REVIEW_APPROVED.value,
    "finalize_ready": LifecyclePhase.FINALIZE_READY.value,
    _LEGACY_HANDED_OFF_PHASE: LifecyclePhase.FINALIZE_READY.value,
}


def _dict(raw: dict[str, StateValue], key: str) -> dict[str, StateValue]:
    value = raw.get(key)
    return value if isinstance(value, dict) else {}


def _text(raw: dict[str, StateValue], key: str) -> str:
    value = raw.get(key)
    return value if isinstance(value, str) else ""


def _artifact_produced(raw: dict[str, StateValue], artifact_key: str) -> bool:
    artifacts = _dict(raw, "artifacts")
    artifact = artifacts.get(artifact_key)
    return isinstance(artifact, dict) and isinstance(artifact.get("produced_at"), str) and bool(artifact["produced_at"])


def _review_verdict(raw: dict[str, StateValue], review_key: str) -> str:
    review = _dict(raw, review_key)
    verdict = review.get("verdict")
    return verdict if isinstance(verdict, str) else ""


def _infer_v1_lifecycle_phase(raw: dict[str, StateValue]) -> str:
    kind = _text(raw, "kind")
    if kind == KIND_DRAFT:
        return LifecyclePhase.DRAFT.value

    lifecycle = _text(raw, "lifecycle_phase")
    if lifecycle:
        return lifecycle

    for legacy_key in ("work_phase", "prepare_phase"):
        legacy_phase = _text(raw, legacy_key)
        if legacy_phase and (legacy_phase in LifecyclePhase._value2member_map_ or legacy_phase in _V2_TO_V3_PHASE):
            return legacy_phase

    phase = _text(raw, "phase")
    finalize = _dict(raw, "finalize")
    finalize_status = finalize.get("status") if isinstance(finalize.get("status"), str) else ""
    build_review_verdict = _review_verdict(raw, "build_review")
    dor = _dict(raw, "dor")
    dor_status = dor.get("status") if isinstance(dor.get("status"), str) else ""
    grounding = _dict(raw, "grounding")
    grounding_valid = grounding.get("valid") is True
    build_completed_at = _text(raw, "build_completed_at")

    if finalize_status == _LEGACY_HANDED_OFF_PHASE or phase in {"delivered", "done"}:
        return LifecyclePhase.FINALIZE_READY.value
    if finalize_status == "ready":
        return LifecyclePhase.FINALIZE_READY.value
    if build_review_verdict == "approve":
        return LifecyclePhase.REVIEW_APPROVED.value
    if build_review_verdict == "changes_requested":
        return LifecyclePhase.REVIEW_CHANGES_REQUESTED.value
    if build_completed_at:
        return LifecyclePhase.BUILD_COMPLETE.value
    if kind in FAST_TRACK_PREPARED_KINDS:
        return LifecyclePhase.PREPARED.value
    if grounding_valid:
        return LifecyclePhase.PREPARED.value
    if dor_status == "pass":
        return "grounding_check"
    if _review_verdict(raw, "plan_review") in {"approve", "skipped"}:
        return "gate"
    if _artifact_produced(raw, "implementation_plan"):
        return LifecyclePhase.PLAN_REVIEW.value
    if _review_verdict(raw, "requirements_review") in {"approve", "skipped"}:
        return LifecyclePhase.PLAN_DRAFTING.value
    if _artifact_produced(raw, "requirements"):
        return "requirements_review"
    if phase == "in_progress":
        return "triangulation"
    return "input_assessment"


def _normalize_finalize(raw: object) -> dict[str, StateValue]:
    finalize: dict[str, StateValue] = {"status": "pending"}
    if not isinstance(raw, dict):
        return finalize

    status = raw.get("status")
    if status == _LEGACY_HANDED_OFF_PHASE:
        finalize["status"] = "ready"
    elif isinstance(status, str) and status in {"pending", "ready"}:
        finalize["status"] = status

    for key in ("branch", "sha", "ready_at", "worker_session_id"):
        value = raw.get(key)
        if isinstance(value, str):
            finalize[key] = value.strip()
    return finalize


def _normalize_finalize_ready_contract(raw: dict[str, StateValue]) -> dict[str, StateValue]:
    migrated = dict(raw)
    old_phase = _text(migrated, "lifecycle_phase")
    finalize_raw = migrated.get("finalize")
    legacy_finalize_handed_off = (
        isinstance(finalize_raw, dict) and finalize_raw.get("status") == _LEGACY_HANDED_OFF_PHASE
    )

    finalize = _normalize_finalize(finalize_raw)
    if old_phase == _LEGACY_HANDED_OFF_PHASE or legacy_finalize_handed_off:
        migrated["lifecycle_phase"] = LifecyclePhase.FINALIZE_READY.value
        finalize["status"] = "ready"
    migrated["finalize"] = finalize
    return migrated


def _detect_schema_version(raw: dict[str, StateValue]) -> int:
    if "current" in raw and "lifecycle_phase" not in raw:
        return _V0_SCHEMA_VERSION
    version = raw.get("schema_version")
    if isinstance(version, int):
        return version
    return _V1_SCHEMA_VERSION


def _upcycle_v0_to_v1(raw: dict[str, StateValue]) -> dict[str, StateValue]:
    migrated = dict(raw)
    current = migrated.pop("current", None)
    if "lifecycle_phase" not in migrated and isinstance(current, str):
        mapped = _LEGACY_CURRENT_TO_LIFECYCLE.get(current)
        if mapped:
            migrated["lifecycle_phase"] = mapped
    migrated["schema_version"] = _V1_SCHEMA_VERSION
    return migrated


def _upcycle_v1_to_v2(raw: dict[str, StateValue]) -> dict[str, StateValue]:
    migrated = dict(raw)
    migrated["schema_version"] = _V2_SCHEMA_VERSION

    migrated["lifecycle_phase"] = _infer_v1_lifecycle_phase(migrated)

    if "finalize" in migrated:
        migrated["finalize"] = _normalize_finalize(migrated.get("finalize"))

    # Legacy sub-phase overrides are no longer persisted in v2.
    migrated.pop("prepare_phase", None)
    migrated.pop("work_phase", None)
    return migrated


def _upcycle_v2_to_v3(raw: dict[str, StateValue]) -> dict[str, StateValue]:
    migrated = dict(raw)
    old_phase = _text(migrated, "lifecycle_phase")
    migrated["lifecycle_phase"] = _V2_TO_V3_PHASE.get(
        old_phase, old_phase if old_phase in LifecyclePhase._value2member_map_ else LifecyclePhase.DRAFT.value
    )
    migrated.pop("prepare_pair", None)
    migrated.pop("grounding", None)
    migrated.setdefault("approvals", {})
    if migrated.get("kind") == KIND_TODO:
        migrated["kind"] = KIND_FEATURE
    migrated["schema_version"] = _V3_SCHEMA_VERSION
    return migrated


def _upcycle_v3_to_v4(raw: dict[str, StateValue]) -> dict[str, StateValue]:
    migrated = _normalize_finalize_ready_contract(raw)
    migrated["schema_version"] = LATEST_TODO_STATE_SCHEMA_VERSION
    return migrated


def _upcycle_to_latest(raw: dict[str, StateValue]) -> dict[str, StateValue]:
    migrated = dict(raw)
    version = _detect_schema_version(migrated)

    if version > LATEST_TODO_STATE_SCHEMA_VERSION:
        msg = f"todo state schema_version {version} is newer than supported latest {LATEST_TODO_STATE_SCHEMA_VERSION}"
        raise ValueError(msg)

    while version < LATEST_TODO_STATE_SCHEMA_VERSION:
        if version == _V0_SCHEMA_VERSION:
            migrated = _upcycle_v0_to_v1(migrated)
        elif version == _V1_SCHEMA_VERSION:
            migrated = _upcycle_v1_to_v2(migrated)
        elif version == _V2_SCHEMA_VERSION:
            migrated = _upcycle_v2_to_v3(migrated)
        elif version == _V3_SCHEMA_VERSION:
            migrated = _upcycle_v3_to_v4(migrated)
        else:
            msg = f"no upcycler registered for todo state schema_version {version}"
            raise ValueError(msg)
        version = _detect_schema_version(migrated)

    if "lifecycle_phase" not in migrated:
        msg = f"todo state schema v{LATEST_TODO_STATE_SCHEMA_VERSION} is missing required lifecycle_phase"
        raise ValueError(msg)
    return migrated


def upcycle_state_dict(raw: dict[str, StateValue]) -> dict[str, StateValue]:
    """Return the latest state shape without mutating persisted storage."""
    latest = _upcycle_to_latest(raw)
    model = TodoState.model_validate(latest)
    return cast(dict[str, StateValue], model.model_dump(exclude_none=True))


def canonicalize_state_for_storage(raw: dict[str, StateValue]) -> dict[str, StateValue]:
    """Return the validated latest state shape to persist."""
    return upcycle_state_dict(raw)


__all__ = [
    "LATEST_TODO_STATE_SCHEMA_VERSION",
    "_detect_schema_version",
    "canonicalize_state_for_storage",
    "upcycle_state_dict",
]
