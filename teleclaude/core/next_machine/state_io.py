"""State I/O — pure read/write operations for work-item state files.

All state read/write, review helpers, and phase status checks. No imports from
core.py (circular-import guard).
"""

# pylint: disable=cyclic-import  # State helpers and lifecycle/slug adapters still cross-reference during migration.

from __future__ import annotations

import hashlib as _hl
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import (
    DEFAULT_MAX_REVIEW_ROUNDS,
    StateValue,
    default_state,
)
from teleclaude.core.next_machine.artifacts import artifact_name_to_state_key
from teleclaude.core.next_machine.file_io import (
    file_sha256 as _file_sha256,
)
from teleclaude.core.next_machine.file_io import (
    read_text_sync,
    write_text_sync,
)
from teleclaude.core.next_machine.git_ops import (
    get_head_commit,
    has_build_commits_beyond_main,
    run_git_command,
)
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    LifecycleStage,
    infer_lifecycle_stage,
    normalize_mark_phase,
    phase_is_complete,
    reconcile_lifecycle_phase,
    require_lifecycle_phase,
)
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.state_mutation import (
    GroundingManager,
    ReviewManager,
    StateWriter,
)
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.project_root import resolve_state_root
from teleclaude.types.todos import ArtifactEntry, BreakdownState, DorState, FinalizeModel, TodoState

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Project root / DB helpers
# ---------------------------------------------------------------------------


def _artifact_digest(cwd: str, slug: str, artifact_name: str) -> str:
    """Read artifact digest from todos.db."""
    db = get_todos_db_sync(cwd)
    conn = db._sync_conn()
    try:
        row = conn.execute(
            "SELECT digest FROM todo_artifacts WHERE slug = ? AND name = ? LIMIT 1",  # guard: raw-sql
            (slug, artifact_name),
        ).fetchone()
        return row[0] if row else ""
    finally:
        conn.close()


def _sync_artifact_state(cwd: str, slug: str, artifact_name: str, *, produced: bool) -> None:
    """Refresh artifact digest in state and optionally mark it as produced."""
    key = artifact_name_to_state_key(artifact_name)
    digest = _artifact_digest(cwd, slug, artifact_name)

    state = read_phase_state(cwd, slug)
    artifacts = state.get("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
    entry = artifacts.get(key, {})
    if not isinstance(entry, dict):
        entry = {}
    entry["digest"] = digest
    if produced:
        entry["produced_at"] = datetime.now(UTC).isoformat()
    artifacts[key] = entry
    state["artifacts"] = artifacts
    write_phase_state(cwd, slug, state)

    if produced:
        _emit_prepare_event(
            "domain.software-development.prepare.artifact_produced",
            {"slug": slug, "artifact": artifact_name, "digest": digest},
        )


def sync_artifact_digest(cwd: str, slug: str, artifact_name: str) -> None:
    """Refresh the stored digest for an artifact without stamping completion."""
    _sync_artifact_state(cwd, slug, artifact_name, produced=False)


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Valid prepare sub-phases that accept verdicts
_REQUIREMENTS_HUMAN_APPROVAL_PHASE = "requirements_human_approval"
_PREPARE_VERDICT_PHASES = (
    "requirements_review",
    _REQUIREMENTS_HUMAN_APPROVAL_PHASE,
    "test_spec_review",
    "plan_review",
)
_PREPARE_VERDICT_VALUES = ("approve", "needs_work", "needs_decision")

# Build-review verdict phase and allowed values
_BUILD_VERDICT_PHASE = "build_review"
_BUILD_VERDICT_VALUES = ("approve", "changes_requested")

_RECONCILE_ARTIFACT_NAMES: dict[str, str] = {
    "input": "input",
    "requirements": "requirements",
    "test_specs": "test-specs",
    "implementation_plan": "implementation-plan",
}

# Maps a review phase name to the artifact state key it gates.
# Used by stamp_verdict to bind approved_digest and by the satisfaction walk
# to compare review approval against current artifact content.
_REVIEW_TO_ARTIFACT_KEY: dict[str, str] = {
    "requirements_review": "requirements",
    "test_spec_review": "test_specs",
    "plan_review": "implementation_plan",
}

# For each artifact that is built from upstream artifacts, lists the upstream
# state keys whose digests must be captured at stamp time. Used by stamp_artifact
# to bind upstream_digests so the satisfaction walk can detect upstream changes.
_ARTIFACT_UPSTREAMS: dict[str, tuple[str, ...]] = {
    "test_specs": ("requirements",),
    "implementation_plan": ("requirements", "test_specs"),
}


def read_phase_state(cwd: str, slug: str) -> dict[str, StateValue]:
    """Read state for a work item from todos.db.

    Returns default state if no state exists in the database. Existing rows are
    upcycled in memory by the ``TodosDb`` read path and are never rewritten as
    a side-effect of reading.
    """
    db = get_todos_db_sync(cwd)
    raw = db.read_state_sync(slug)
    if raw is None:
        return default_state()
    return raw


def write_phase_state(cwd: str, slug: str, state: dict[str, StateValue]) -> None:
    """Write state to todos.db."""
    db = get_todos_db_sync(cwd)
    db.write_state_sync(slug, state)


def _read_artifact_presence(cwd: str, slug: str) -> dict[str, bool]:
    """Return current DB artifact presence for lifecycle validation/reconciliation."""
    db = get_todos_db_sync(cwd)
    conn = db._sync_conn()
    try:
        rows = conn.execute(
            "SELECT name FROM todo_artifacts WHERE slug = ?",  # guard: raw-sql
            (slug,),
        ).fetchall()
    except sqlite3.Error:
        logger.warning("Failed to read artifact presence for lifecycle reconciliation", slug=slug, cwd=cwd)
        raise
    finally:
        conn.close()

    names = {str(row[0]) for row in rows}
    return {state_key: artifact_name in names for state_key, artifact_name in _RECONCILE_ARTIFACT_NAMES.items()}


def _sync_reconcile_artifacts(cwd: str, slug: str, writer: StateWriter) -> None:
    """Align state-model provenance with blob reality. Bootstrap-only — never overwrites
    recorded provenance once the production path has captured it."""
    now = datetime.now(UTC).isoformat()
    for state_key, artifact_name in _RECONCILE_ARTIFACT_NAMES.items():
        entry = getattr(writer.state.artifacts, state_key)
        entry.digest = _artifact_digest(cwd, slug, artifact_name)
        if not entry.digest:
            entry.produced_at = ""
            continue
        if not entry.produced_at:
            entry.produced_at = now
        upstream_keys = _ARTIFACT_UPSTREAMS.get(state_key, ())
        if upstream_keys and not entry.upstream_digests:
            entry.upstream_digests = {k: getattr(writer.state.artifacts, k).digest for k in upstream_keys}


def validate_mark_phase_preconditions(
    state: dict[str, StateValue],
    phase: str,
    worktree_cwd: str | None,
    artifact_presence: dict[str, bool] | None = None,
) -> str | None:
    """Return an error string when the target lifecycle phase cannot become current."""
    try:
        target = LifecyclePhase(phase)
    except ValueError:
        return f"Unknown lifecycle phase: {phase}"

    model = TodoState.model_validate(state)
    return _validate_mark_phase_target(
        model,
        target,
        worktree_cwd=worktree_cwd,
        artifact_presence=artifact_presence,
    )


def _has_artifact_digest(
    model: TodoState,
    key: str,
    *,
    artifact_presence: dict[str, bool] | None = None,
) -> bool:
    if artifact_presence is not None and key in artifact_presence:
        return artifact_presence[key]
    entry = getattr(model.artifacts, key, None)
    if not isinstance(entry, ArtifactEntry):
        return False
    return bool(entry.digest)


def _validate_prepare_mark_phase(
    model: TodoState,
    target: LifecyclePhase,
    *,
    worktree_cwd: str | None,
    artifact_presence: dict[str, bool] | None,
) -> str | None:
    if target in (LifecyclePhase.DRAFT, LifecyclePhase.INPUT_ASSESSMENT, LifecyclePhase.TRIANGULATION):
        return None
    if target == LifecyclePhase.REQUIREMENTS_REVIEW:
        missing: list[str] = []
        if not _has_artifact_digest(model, "input", artifact_presence=artifact_presence):
            missing.append("input artifact")
        if not _has_artifact_digest(model, "requirements", artifact_presence=artifact_presence):
            missing.append("requirements artifact")
        if missing:
            return f"Cannot mark {target.value}: missing {' and '.join(missing)}"
        return None
    if target == LifecyclePhase.REQUIREMENTS_HUMAN_APPROVAL:
        if not _has_artifact_digest(model, "requirements", artifact_presence=artifact_presence):
            return f"Cannot mark {target.value}: missing requirements artifact"
        if model.requirements_review.verdict != "approve":
            return f"Cannot mark {target.value}: missing approved requirements review"
        return None
    if target == LifecyclePhase.TEST_SPEC_BUILD and model.requirements_review.verdict not in ("approve", "skipped"):
        if not _has_artifact_digest(model, "requirements", artifact_presence=artifact_presence):
            return f"Cannot mark {target.value}: missing requirements artifact"
        return f"Cannot mark {target.value}: missing approved requirements review"
    if (
        target == LifecyclePhase.TEST_SPEC_BUILD
        and model.requirements_review.verdict == "approve"
        and not model.artifacts.requirements.approved
    ):
        return f"Cannot mark {target.value}: missing human requirements approval"
    if target == LifecyclePhase.TEST_SPEC_REVIEW and not _has_artifact_digest(
        model, "test_specs", artifact_presence=artifact_presence
    ):
        return f"Cannot mark {target.value}: missing test specs artifact"
    if target == LifecyclePhase.PLAN_DRAFTING and model.test_spec_review.verdict not in ("approve", "skipped"):
        return f"Cannot mark {target.value}: missing approved test specs review"
    if target == LifecyclePhase.PLAN_REVIEW and not _has_artifact_digest(
        model, "implementation_plan", artifact_presence=artifact_presence
    ):
        return f"Cannot mark {target.value}: missing implementation-plan artifact"
    if target == LifecyclePhase.GATE and model.plan_review.verdict not in ("approve", "skipped"):
        return f"Cannot mark {target.value}: missing approved plan review"
    if target in (LifecyclePhase.GROUNDING_CHECK, LifecyclePhase.RE_GROUNDING) and model.plan_review.verdict not in (
        "approve",
        "skipped",
    ):
        return f"Cannot mark {target.value}: missing approved plan review"
    if target == LifecyclePhase.PREPARED and not model.grounding.valid:
        return f"Cannot mark {target.value}: missing valid grounding state"
    return None


def _validate_work_mark_phase(model: TodoState, target: LifecyclePhase, *, worktree_cwd: str | None) -> str | None:
    if target == LifecyclePhase.BUILD_STARTED:
        if model.lifecycle_phase != LifecyclePhase.PREPARED.value and not phase_is_complete(
            model, LifecyclePhase.GROUNDING_CHECK, worktree_cwd=worktree_cwd
        ):
            return f"Cannot mark {target.value}: missing valid grounding state"
        return None
    if target == LifecyclePhase.BUILD_COMPLETE:
        if (
            not model.build_completed_at
            and worktree_cwd is not None
            and not has_build_commits_beyond_main(worktree_cwd)
        ):
            return f"Cannot mark {target.value}: missing commits beyond main in {worktree_cwd}"
        return None
    if target == LifecyclePhase.REVIEW_CHANGES_REQUESTED and model.build_review.verdict != "changes_requested":
        return f"Cannot mark {target.value}: missing build review verdict 'changes_requested'"
    if target == LifecyclePhase.REVIEW_APPROVED and model.build_review.verdict != "approve":
        return f"Cannot mark {target.value}: missing build review verdict 'approve'"
    if target == LifecyclePhase.FINALIZE_READY and model.finalize.status != "ready":
        return f"Cannot mark {target.value}: missing finalize ready state"
    if target == LifecyclePhase.HANDED_OFF and model.finalize.status != "handed_off":
        return f"Cannot mark {target.value}: missing handed-off finalize state"
    return None


def _validate_mark_phase_target(
    model: TodoState,
    target: LifecyclePhase,
    *,
    worktree_cwd: str | None,
    artifact_presence: dict[str, bool] | None,
) -> str | None:
    if target == LifecyclePhase.PREPARED or target in (
        LifecyclePhase.DRAFT,
        LifecyclePhase.INPUT_ASSESSMENT,
        LifecyclePhase.TRIANGULATION,
        LifecyclePhase.REQUIREMENTS_REVIEW,
        LifecyclePhase.REQUIREMENTS_HUMAN_APPROVAL,
        LifecyclePhase.TEST_SPEC_BUILD,
        LifecyclePhase.TEST_SPEC_REVIEW,
        LifecyclePhase.PLAN_DRAFTING,
        LifecyclePhase.PLAN_REVIEW,
        LifecyclePhase.GATE,
        LifecyclePhase.GROUNDING_CHECK,
        LifecyclePhase.RE_GROUNDING,
    ):
        return _validate_prepare_mark_phase(
            model,
            target,
            worktree_cwd=worktree_cwd,
            artifact_presence=artifact_presence,
        )
    return _validate_work_mark_phase(model, target, worktree_cwd=worktree_cwd)


def validate_work_phase_preconditions(
    state: dict[str, StateValue],
    phase: str,
    worktree_cwd: str | None,
) -> str | None:
    """Compatibility wrapper for older callers/tests."""
    return validate_mark_phase_preconditions(state, phase, worktree_cwd)


def mark_phase_state(cwd: str, slug: str, phase: str) -> dict[str, StateValue]:
    """Validate and persist an authoritative lifecycle phase override."""
    raw_state = dict(read_phase_state(cwd, slug))
    prior_phase = str(raw_state.get("lifecycle_phase", ""))
    worktree_cwd = str(Path(cwd) / WORKTREE_DIR / slug)
    wt = worktree_cwd if Path(worktree_cwd).exists() else None
    artifact_presence = _read_artifact_presence(cwd, slug)
    error = validate_mark_phase_preconditions(raw_state, phase, wt, artifact_presence)
    if error:
        raise ValueError(error)
    writer = StateWriter(raw_state)
    _sync_reconcile_artifacts(cwd, slug, writer)
    normalize_mark_phase(writer.state, LifecyclePhase(phase), worktree_cwd=wt)
    payload = writer.to_dict()
    write_phase_state(cwd, slug, payload)
    logger.info(
        "todo phase override persisted",
        slug=slug,
        prior_phase=prior_phase,
        target_phase=phase,
        resulting_phase=str(payload.get("lifecycle_phase", "")),
        cwd=cwd,
    )
    return payload


def reconcile_phase_state(cwd: str, slug: str, stage: str | None = None) -> dict[str, StateValue]:
    """Explicitly realign the machine pointer to the best phase within one stage."""
    raw_state = dict(read_phase_state(cwd, slug))
    writer = StateWriter(raw_state)
    current = require_lifecycle_phase(writer.state.lifecycle_phase, context=f"reconcile_phase_state({slug})")

    if stage is None:
        stage_value = infer_lifecycle_stage(current)
    else:
        try:
            stage_value = LifecycleStage(stage)
        except ValueError as exc:
            raise ValueError(f"Unknown stage: {stage}") from exc

    worktree_cwd = str(Path(cwd) / WORKTREE_DIR / slug)
    wt = worktree_cwd if Path(worktree_cwd).exists() else None
    artifact_presence = _read_artifact_presence(cwd, slug)
    _sync_reconcile_artifacts(cwd, slug, writer)
    target = reconcile_lifecycle_phase(
        writer.state,
        stage_value,
        worktree_cwd=wt,
        artifact_presence=artifact_presence,
    )
    if target is None:
        raise ValueError(f"No valid {stage_value.value} phase matches the current todo state")

    writer.state.lifecycle_phase = target.value
    payload = writer.to_dict()
    write_phase_state(cwd, slug, payload)
    logger.info(
        "todo phase reconciled",
        slug=slug,
        requested_stage=stage_value.value,
        prior_phase=current.value,
        resulting_phase=target.value,
        cwd=cwd,
    )
    return payload


# ---------------------------------------------------------------------------
# Stamp operations
# ---------------------------------------------------------------------------


def stamp_verdict(cwd: str, slug: str, phase: str, verdict: str) -> dict[str, StateValue]:
    """Stamp a review phase verdict via the typed state boundary.

    Handles both prepare sub-phases (requirements_review, test_spec_review,
    plan_review) via :class:`ReviewManager`, and the work build_review phase
    via direct mutation on :class:`BuildReviewState` (which is not a
    ``ReviewVerdictState`` and has no audit entry).

    Per the stamp/machine boundary rule, this stamp records the verdict only.
    The corresponding lifecycle signal fires from the prepare or work state
    machine on its next dispatch when it observes the recorded verdict.
    For build_review specifically, the work machine derives ``baseline_commit``
    from the current worktree HEAD when consuming a verdict that has no
    baseline yet, so re-review rounds can scope their diff.

    Args:
        cwd: Project root directory (not worktree)
        slug: Work item slug
        phase: Review phase key (requirements_review, test_spec_review,
            plan_review, or build_review)
        verdict: Verdict value — prepare phases accept approve/needs_work/
            needs_decision; build_review accepts approve/changes_requested

    Returns:
        Updated state dict
    """
    if phase == _BUILD_VERDICT_PHASE:
        if verdict not in _BUILD_VERDICT_VALUES:
            raise ValueError(
                f"invalid build_review verdict '{verdict}': must be one of {', '.join(_BUILD_VERDICT_VALUES)}"
            )
        db = get_todos_db_sync(cwd)
        state = read_phase_state(cwd, slug)
        writer = StateWriter(state)
        build_review = writer.state.build_review
        build_review.verdict = verdict
        build_review.reviewed_at = datetime.now(UTC).isoformat()
        payload = writer.commit_sync(db, slug)
        logger.info(
            "todo verdict stamped",
            slug=slug,
            phase=phase,
            verdict=verdict,
            resulting_phase=str(payload.get("lifecycle_phase", "")),
            cwd=cwd,
        )
        return payload

    if phase not in _PREPARE_VERDICT_PHASES:
        raise ValueError(
            f"invalid review phase '{phase}': must be one of "
            f"{', '.join((*_PREPARE_VERDICT_PHASES, _BUILD_VERDICT_PHASE))}"
        )
    if verdict not in _PREPARE_VERDICT_VALUES:
        raise ValueError(f"invalid verdict '{verdict}': must be one of {', '.join(_PREPARE_VERDICT_VALUES)}")

    db = get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    writer = StateWriter(state)
    if phase == _REQUIREMENTS_HUMAN_APPROVAL_PHASE:
        writer.state.artifacts.requirements.approved = verdict == "approve"
        payload = writer.commit_sync(db, slug)
        logger.info(
            "todo verdict stamped",
            slug=slug,
            phase=phase,
            verdict=verdict,
            resulting_phase=str(payload.get("lifecycle_phase", "")),
            cwd=cwd,
        )
        return payload
    ReviewManager(writer).stamp_verdict(phase, verdict)
    if verdict == "approve":
        artifact_key = _REVIEW_TO_ARTIFACT_KEY.get(phase)
        if artifact_key is not None:
            artifact_entry = getattr(writer.state.artifacts, artifact_key)
            review = writer.verdict_target(phase)
            review.approved_digest = artifact_entry.digest
    payload = writer.commit_sync(db, slug)
    logger.info(
        "todo verdict stamped",
        slug=slug,
        phase=phase,
        verdict=verdict,
        resulting_phase=str(payload.get("lifecycle_phase", "")),
        cwd=cwd,
    )
    return payload


def stamp_finalize_ready(cwd: str, slug: str, caller_session_id: str = "") -> dict[str, StateValue]:
    """Record the worker's claim that the worktree is finalize-ready.

    Writes a :class:`FinalizeModel` with ``status="ready"``, the current
    worktree HEAD as the candidate SHA, and the caller's session ID so the
    later integration trigger event carries the worker's identity. Triple-ref
    validation (worktree HEAD == local branch ref == remote ref) and the
    lifecycle event emission happen in the work state machine when it
    observes the claim.

    The caller session identity is required: it becomes the
    ``worker_session_id`` field on the eventual ``todo_finalize_ready`` event,
    which the integration trigger cartridge uses to attribute the spawn.
    Empty caller identity would propagate an unattributable event downstream.
    """
    if not caller_session_id:
        raise RuntimeError(
            f"finalize_ready stamp for {slug} requires a non-empty caller session ID; "
            "the integration trigger event needs an attributable worker_session_id."
        )

    project_root = str(resolve_state_root(cwd))
    worktree_path = Path(project_root) / WORKTREE_DIR / slug
    head_sha = get_head_commit(str(worktree_path)) if worktree_path.exists() else ""

    db = get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    writer = StateWriter(state)
    now = datetime.now(UTC).isoformat()
    writer.state.finalize = FinalizeModel(
        status="ready",
        branch=slug,
        sha=head_sha,
        ready_at=now,
        handed_off_at="",
        worker_session_id=caller_session_id,
    )
    return writer.commit_sync(db, slug)


_QUALITY_CHECKLIST_TEMPLATE = """\
# Quality Checklist: {slug}

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [ ] Requirements implemented according to scope
- [ ] Implementation-plan task checkboxes all `[x]`
- [ ] Tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [ ] No silent deferrals in implementation plan
- [ ] Code committed
- [ ] User-facing verification evidence recorded
- [ ] Browser-based frontend or web UI changes smoke-tested with Playwright
- [ ] Working tree clean
- [ ] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
- [ ] Findings written in `review-findings.md`
- [ ] Verdict recorded (APPROVE or REQUEST CHANGES)
- [ ] Critical issues resolved or explicitly blocked
- [ ] Test coverage and regression risk assessed
- [ ] User-facing verification evidence reviewed
- [ ] Browser-based frontend or web UI changes verified with Playwright during review, or gap recorded as a finding

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in roadmap (status: delivered)
- [ ] Worktree cleanup complete
"""


def _has_artifact_content(cwd: str, slug: str, artifact_name: str) -> bool:
    """Return True when the DB artifact has non-trivial content beyond whitespace/headings."""
    db = get_todos_db_sync(cwd)
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        row = conn.execute(
            "SELECT content FROM todo_artifacts WHERE slug = ? AND name = ? LIMIT 1",  # guard: raw-sql
            (slug, artifact_name),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return False
    text: str = row[0] or ""
    lines = [ln for ln in text.strip().splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return len(lines) > 0


def apply_prepared_state(cwd: str, slug: str) -> dict[str, StateValue]:
    """Stamp all authoritative state required to make a todo `prepared`.

    Fast-track path used by prepped ``telec todo dump`` to short-circuit
    the full prepare lifecycle.
    Validates that requirements and implementation-plan artifacts exist and
    that a git HEAD is reachable BEFORE any state is persisted. Only after
    validation succeeds does the function generate the quality-checklist
    artifact when missing, stamp DOR pass, the current git HEAD as the
    grounding baseline, the prepare review verdicts (requirements is stamped
    ``skipped`` for prepped todos — there is no requirements artifact to
    review), and the canonical `lifecycle_phase = "prepared"` commitment.
    Validation failures raise and no partial state is written, so callers see
    the error and the todo stays in its prior phase.

    Args:
        cwd: Project root directory (not worktree)
        slug: Work item slug

    Returns:
        Updated state dict

    Raises:
        ValueError: when a required artifact is missing or git HEAD cannot be read.
    """
    # pylint: disable=too-many-locals,too-many-statements
    project_root = str(resolve_state_root(cwd))
    db = get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    kind = state.get("kind")

    if kind not in ("prepped", "bug") and not _has_artifact_content(cwd, slug, "requirements"):
        raise ValueError(f"Missing requirements artifact with content for {slug}")
    if kind != "bug" and not _has_artifact_content(cwd, slug, "implementation-plan"):
        raise ValueError(f"Missing implementation-plan artifact with content for {slug}")

    rc, current_sha_raw, _ = run_git_command(["rev-parse", "HEAD"], cwd=project_root)
    if rc != 0 or not current_sha_raw.strip():
        msg = f"git rev-parse HEAD failed (rc={rc}) in {project_root} — cannot establish grounding baseline"
        raise ValueError(msg)
    current_sha = current_sha_raw.strip()

    if not _has_artifact_content(cwd, slug, "quality-checklist"):
        checklist_content = _QUALITY_CHECKLIST_TEMPLATE.format(slug=slug)
        now_iso = datetime.now(UTC).isoformat()
        digest = _hl.sha256(checklist_content.encode("utf-8")).hexdigest()
        conn = db._sync_conn()  # pylint: disable=protected-access
        try:
            id_row = conn.execute(
                "SELECT id FROM roadmap WHERE slug = ? AND status != 'delivered' LIMIT 1",  # guard: raw-sql
                (slug,),
            ).fetchone()
            row_id = id_row[0] if id_row else slug
            conn.execute(
                "INSERT INTO todo_artifacts "  # guard: raw-sql
                "(id, slug, name, content, digest, updated_by, updated_at) "
                "VALUES (?, ?, 'quality-checklist', ?, ?, 'apply_prepared_state', ?) "
                "ON CONFLICT(id, name) DO UPDATE SET "
                "content = excluded.content, digest = excluded.digest, "
                "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
                (row_id, slug, checklist_content, digest, now_iso),
            )
            conn.commit()
        finally:
            conn.close()

    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        input_row = conn.execute(
            "SELECT digest FROM todo_artifacts WHERE slug = ? AND name = 'input' LIMIT 1",  # guard: raw-sql
            (slug,),
        ).fetchone()
    finally:
        conn.close()
    input_digest = input_row[0] if input_row and input_row[0] else ""

    now_iso = datetime.now(UTC).isoformat()
    writer = StateWriter(state)
    if kind != "bug":
        writer.state.dor = DorState(
            last_assessed_at=now_iso,
            score=8,
            status="pass",
            schema_version=1,
            blockers=[],
        )

    review_mgr = ReviewManager(writer)
    if kind in ("prepped", "bug"):
        review_mgr.stamp_verdict("requirements_review", "skipped")
    else:
        review_mgr.stamp_verdict("requirements_review", "approve")

    if kind in ("bug", "prepped"):
        # Bugs and prepped todos bypass test specs entirely
        review_mgr.stamp_verdict("test_spec_review", "skipped")
        writer.state.artifacts.test_specs.produced_at = now_iso
    if kind == "bug":
        review_mgr.stamp_verdict("plan_review", "skipped")
    else:
        review_mgr.stamp_verdict("plan_review", "approve")

    GroundingManager(writer).refresh(current_sha=current_sha)
    if input_digest:
        writer.state.artifacts.input.digest = input_digest
        writer.grounding.input_digest = input_digest
    writer.state.lifecycle_phase = "prepared"
    if kind not in ("prepped", "bug"):
        writer.state.artifacts.requirements.digest = _artifact_digest(cwd, slug, "requirements")
        writer.state.artifacts.requirements.produced_at = now_iso
    if kind != "bug":
        writer.state.artifacts.implementation_plan.digest = _artifact_digest(cwd, slug, "implementation-plan")
        writer.state.artifacts.implementation_plan.produced_at = now_iso

    payload = writer.commit_sync(db, slug)
    logger.info(
        "todo prepared fast-track applied",
        slug=slug,
        kind=str(kind or ""),
        resulting_phase=str(payload.get("lifecycle_phase", "")),
        cwd=cwd,
    )
    return payload


# ---------------------------------------------------------------------------
# Review state helpers
# ---------------------------------------------------------------------------


def _review_scope_note(cwd: str, slug: str) -> str:
    """Build an iterative review scope note from build_review state.

    Used by the work-review step handler when dispatching re-review messages
    to a live reviewer session. Reads the ``build_review`` substructure on v1
    state; earlier schemas are reset on read.
    """
    state = read_phase_state(cwd, slug)
    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    round_raw = build_review.get("round")
    review_round = round_raw if isinstance(round_raw, int) else 0
    next_round = review_round + 1
    baseline = build_review.get("baseline_commit")
    baseline_sha = baseline if isinstance(baseline, str) else ""
    if next_round == 1:
        target_text = baseline_sha if baseline_sha else "current HEAD"
        return (
            f"Review iteration: round 1/{DEFAULT_MAX_REVIEW_ROUNDS}. "
            f"Round 1 is full-scope. Review the current worktree state at {target_text}."
        )
    baseline_text = baseline_sha if baseline_sha else "unset"
    return (
        f"Review iteration: round {next_round}/{DEFAULT_MAX_REVIEW_ROUNDS}. "
        "Round 2+ must be incremental: review only commits since "
        f"{baseline_text}."
    )


def _is_review_round_limit_reached(cwd: str, slug: str) -> tuple[bool, int, int]:
    """Return whether next review round would exceed the hard cap."""
    state = read_phase_state(cwd, slug)
    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    round_raw = build_review.get("round")
    review_round = round_raw if isinstance(round_raw, int) else 0
    return (review_round + 1) > DEFAULT_MAX_REVIEW_ROUNDS, review_round, DEFAULT_MAX_REVIEW_ROUNDS


def read_breakdown_state(cwd: str, slug: str) -> dict[str, bool | list[str]] | None:
    """Read breakdown state from todos.db for the given slug.

    Returns:
        Breakdown state dict with 'assessed' and 'todos' keys, or None if not present.
    """
    state = read_phase_state(cwd, slug)
    breakdown = state.get("breakdown")
    if breakdown is None or not isinstance(breakdown, dict):
        return None
    result: dict[str, bool | list[str]] = {}
    for key, value in breakdown.items():
        if isinstance(value, bool):
            result[key] = value
        elif isinstance(value, list):
            result[key] = [str(item) for item in value]
    return result


def write_breakdown_state(cwd: str, slug: str, assessed: bool, todos: list[str]) -> None:
    """Write breakdown state via the typed write boundary.

    Args:
        cwd: Project root directory
        slug: Work item slug
        assessed: Whether breakdown assessment has been performed
        todos: List of todo slugs created from split (empty if no breakdown)
    """
    db = get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    writer = StateWriter(state)
    writer.state.breakdown = BreakdownState(assessed=assessed, todos=list(todos))
    writer.commit_sync(db, slug)


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def has_pending_deferrals(cwd: str, slug: str) -> bool:
    """Check if there are pending deferrals.

    Returns true if deferrals artifact exists in DB AND state.deferrals_processed is NOT true.
    """
    state = read_phase_state(cwd, slug)
    if state.get("deferrals_processed") is True:
        return False

    db = get_todos_db_sync(cwd)
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        row = conn.execute(
            "SELECT 1 FROM todo_artifacts WHERE slug = ? AND name = 'deferrals' LIMIT 1",  # guard: raw-sql
            (slug,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def is_bug_todo(cwd: str, slug: str) -> bool:
    """Check if a todo is a bug (kind='bug' in state.yaml)."""
    state = read_phase_state(cwd, slug)
    return state.get("kind") == "bug"


def is_prepped_todo(cwd: str, slug: str) -> bool:
    """Check if a todo entered the lifecycle pre-prepared (kind='prepped').

    Prepped todos were born with a complete implementation plan and skipped the
    prepare phase entirely. They have no requirements artifact — the plan is the
    sole spec.
    """
    state = read_phase_state(cwd, slug)
    return state.get("kind") == "prepped"


# Artifact keys that can be stamped after worker output is verified.
_PREPARE_ARTIFACT_NAMES = {
    "requirements": "requirements",
    "implementation_plan": "implementation-plan",
}
_PREPARE_ARTIFACT_PHASES = (*_PREPARE_ARTIFACT_NAMES.keys(), "test_specs")


def stamp_artifact(cwd: str, slug: str, artifact_key: str) -> dict[str, StateValue]:
    """Stamp an artifact as produced via the typed artifacts state.

    File-backed artifacts record both digest and produced_at. Directory-backed
    artifacts (currently test_specs) record produced_at only.

    Args:
        cwd: Project root directory (not worktree)
        slug: Work item slug
        artifact_key: Artifact state key (e.g. test_specs)

    Returns:
        Updated state dict
    """
    if artifact_key not in _PREPARE_ARTIFACT_PHASES:
        raise ValueError(f"invalid artifact key '{artifact_key}': must be one of {', '.join(_PREPARE_ARTIFACT_PHASES)}")

    artifact_name = _PREPARE_ARTIFACT_NAMES.get(artifact_key)
    if artifact_name is not None:
        _sync_artifact_state(cwd, slug, artifact_name, produced=True)
        _capture_upstream_digests(cwd, slug, artifact_key)
        return read_phase_state(cwd, slug)

    db = get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    writer = StateWriter(state)
    entry = getattr(writer.state.artifacts, artifact_key, None)
    if not isinstance(entry, ArtifactEntry):
        raise ValueError(f"unknown artifact phase '{artifact_key}'")
    entry.produced_at = datetime.now(UTC).isoformat()
    if artifact_key == "test_specs":
        # Sync digest from the test-specs DB artifact when one exists. Workers may
        # write a manifest of spec files to the test-specs artifact; the digest
        # then gates test_spec_review approval. When no manifest is written, the
        # digest stays empty and review approval binds to no specific content.
        specs_digest = _artifact_digest(cwd, slug, "test-specs")
        if specs_digest:
            entry.digest = specs_digest
    upstream_keys = _ARTIFACT_UPSTREAMS.get(artifact_key, ())
    if upstream_keys:
        entry.upstream_digests = {
            upstream_key: getattr(writer.state.artifacts, upstream_key).digest for upstream_key in upstream_keys
        }
    return writer.commit_sync(db, slug)


def _capture_upstream_digests(cwd: str, slug: str, artifact_key: str) -> None:
    """Record current upstream digests on a freshly stamped artifact entry."""
    upstream_keys = _ARTIFACT_UPSTREAMS.get(artifact_key, ())
    if not upstream_keys:
        return
    db = get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    writer = StateWriter(state)
    entry = getattr(writer.state.artifacts, artifact_key, None)
    if not isinstance(entry, ArtifactEntry):
        return
    entry.upstream_digests = {
        upstream_key: getattr(writer.state.artifacts, upstream_key).digest for upstream_key in upstream_keys
    }
    writer.commit_sync(db, slug)


__all__ = [
    "_BUILD_VERDICT_PHASE",
    "_BUILD_VERDICT_VALUES",
    "_file_sha256",
    "_is_review_round_limit_reached",
    "_review_scope_note",
    "apply_prepared_state",
    "has_pending_deferrals",
    "is_bug_todo",
    "is_prepped_todo",
    "mark_phase_state",
    "read_breakdown_state",
    "read_phase_state",
    "read_text_sync",
    "reconcile_phase_state",
    "stamp_artifact",
    "stamp_finalize_ready",
    "stamp_verdict",
    "sync_artifact_digest",
    "validate_mark_phase_preconditions",
    "validate_work_phase_preconditions",
    "write_breakdown_state",
    "write_phase_state",
    "write_text_sync",
]
