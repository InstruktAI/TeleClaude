"""State I/O — pure read/write operations for work-item state files.

All state read/write, review helpers, and phase status checks. No imports from
core.py (circular-import guard).
"""

# pylint: disable=cyclic-import  # State helpers and lifecycle/slug adapters still cross-reference during migration.

from __future__ import annotations

import hashlib as _hl
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import (
    DEFAULT_MAX_REVIEW_ROUNDS,
    FinalizeState,
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
    get_ref_commit,
    get_remote_branch_head,
    has_uncommitted_changes,
    run_git_command,
)
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    apply_authoritative_signal,
    normalize_mark_phase,
    phase_is_complete,
)
from teleclaude.core.next_machine.phase_derivation import (
    _has_build_commits_beyond_main,
)
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.state_mutation import (
    GroundingManager,
    ReviewManager,
    StateWriter,
)
from teleclaude.core.todos_db import TodosDb, _new_instance_hook
from teleclaude.project_root import resolve_main_repo_root
from teleclaude.types.todos import ArtifactEntry, BreakdownState, DorState, FinalizeModel, TodoState

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Project root / DB helpers
# ---------------------------------------------------------------------------


def _artifact_digest(cwd: str, slug: str, artifact_name: str) -> str:
    """Read artifact digest from todos.db."""
    db = _get_todos_db_sync(cwd)
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
    entry["stale"] = False
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


def _project_root_from_cwd(cwd: str) -> str:
    """Resolve project root from a path that may be inside a worktree."""
    return str(resolve_main_repo_root(cwd))


_db_cache: dict[str, TodosDb] = {}


def _get_todos_db_sync(cwd: str) -> TodosDb:
    """Return a cached TodosDb for the project owning *cwd*.

    Schema already exists (daemon creates it at startup). Skips initialize_sync
    after first call to avoid repeated DDL write locks on the database.
    """
    project_root = _project_root_from_cwd(cwd)
    cached = _db_cache.get(project_root)
    if cached is not None:
        return cached

    db_path = str(Path(project_root) / ".teleclaude" / "todos.db")
    db = TodosDb(db_path)
    db.initialize_sync()
    if _new_instance_hook is not None:
        _new_instance_hook(db, project_root)
    _db_cache[project_root] = db
    return db


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Valid prepare sub-phases that accept verdicts
_PREPARE_VERDICT_PHASES = ("requirements_review", "test_spec_review", "plan_review")
_PREPARE_VERDICT_VALUES = ("approve", "needs_work", "needs_decision")

# Build-review verdict phase and allowed values
_BUILD_VERDICT_PHASE = "build_review"
_BUILD_VERDICT_VALUES = ("approve", "changes_requested")


# ---------------------------------------------------------------------------
# Schema migrator registry
# ---------------------------------------------------------------------------

# Migrators translate legacy persisted state to the current v1 shape. Empty by
# default: when a stale schema_version is encountered and no migrator is
# registered, ``read_phase_state`` wipes the row and writes a fresh
# ``TodoState.defaults()`` so the next-machine loop derives phase from the
# remaining primitives (artifacts, git commits, DOR stamps).
_SCHEMA_MIGRATORS: dict[int, Callable[[dict[str, StateValue]], dict[str, StateValue]]] = {}


# ---------------------------------------------------------------------------
# State read/write
# ---------------------------------------------------------------------------


def _normalize_finalize_state(raw: object) -> FinalizeState:
    finalize: FinalizeState = {"status": "pending"}
    if not isinstance(raw, dict):
        return finalize

    status = raw.get("status")
    if isinstance(status, str) and status in {"pending", "ready", "handed_off"}:
        finalize["status"] = status

    for key in ("branch", "sha", "ready_at", "handed_off_at"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            finalize[key] = value.strip()
    return finalize


def read_phase_state(cwd: str, slug: str) -> dict[str, StateValue]:
    """Read state for a work item from todos.db.

    Returns default state if no state exists in the database. Schema v1 blobs
    are returned as-is. Any other ``schema_version`` is routed through the
    migrator registry; if no migrator matches, the row is reset to a fresh
    v1 default and rewritten. Artifacts and roadmap rows are untouched.
    """
    db = _get_todos_db_sync(cwd)
    raw = db.read_state_sync(slug)
    if raw is None:
        return default_state()

    version_raw = raw.get("schema_version")
    version = version_raw if isinstance(version_raw, int) else 0

    if version == 1:
        if "finalize" in raw:
            raw["finalize"] = _normalize_finalize_state(raw.get("finalize"))  # type: ignore[assignment]
        return raw

    migrator = _SCHEMA_MIGRATORS.get(version)
    if migrator is not None:
        migrated = migrator(raw)
        db.write_state_sync(slug, migrated)
        return migrated

    logger.warning("schema_reset slug=%s from_version=%s", slug, version)
    fresh = TodoState.defaults().model_dump()
    db.write_state_sync(slug, fresh)
    return fresh


def write_phase_state(cwd: str, slug: str, state: dict[str, StateValue]) -> None:
    """Write state to todos.db."""
    db = _get_todos_db_sync(cwd)
    db.write_state_sync(slug, state)


def validate_mark_phase_preconditions(
    state: dict[str, StateValue],
    phase: str,
    worktree_cwd: str | None,
) -> str | None:
    """Return an error string when the target lifecycle phase cannot become current."""
    try:
        target = LifecyclePhase(phase)
    except ValueError:
        return f"Unknown lifecycle phase: {phase}"

    model = TodoState.model_validate(state)
    return _validate_mark_phase_target(model, target, worktree_cwd=worktree_cwd)


def _phase_complete(model: TodoState, current: LifecyclePhase, *, worktree_cwd: str | None) -> bool:
    return phase_is_complete(model, current, worktree_cwd=worktree_cwd)


def _has_artifact_digest(model: TodoState, key: str) -> bool:
    entry = getattr(model.artifacts, key, None)
    if not isinstance(entry, ArtifactEntry):
        return False
    return bool(entry.digest)


def _validate_prepare_mark_phase(model: TodoState, target: LifecyclePhase, *, worktree_cwd: str | None) -> str | None:
    if target in (LifecyclePhase.INPUT_ASSESSMENT, LifecyclePhase.TRIANGULATION):
        return None
    if target == LifecyclePhase.REQUIREMENTS_REVIEW and not _has_artifact_digest(model, "input"):
        return "Cannot set requirements_review: requirements have not been produced"
    if target == LifecyclePhase.TEST_SPEC_BUILD and model.requirements_review.verdict not in ("approve", "skipped"):
        return "Cannot set test_spec_build: requirements_review is not complete"
    if target == LifecyclePhase.TEST_SPEC_REVIEW and not bool(model.artifacts.test_specs.produced_at):
        return "Cannot set test_spec_review: test specs have not been produced"
    if target == LifecyclePhase.PLAN_DRAFTING and model.test_spec_review.verdict not in ("approve", "skipped"):
        return "Cannot set plan_drafting: test_spec_review is not complete"
    if target == LifecyclePhase.PLAN_REVIEW and not _has_artifact_digest(model, "implementation_plan"):
        return "Cannot set plan_review: implementation plan has not been produced"
    if target == LifecyclePhase.GATE and model.plan_review.verdict not in ("approve", "skipped"):
        return "Cannot set gate: plan_review is not complete"
    if target in (LifecyclePhase.GROUNDING_CHECK, LifecyclePhase.RE_GROUNDING) and not (
        model.dor is not None and model.dor.status == "pass"
    ):
        return f"Cannot set {target.value}: gate is not complete"
    if target == LifecyclePhase.PREPARED and not model.grounding.valid:
        return "Cannot set prepared: grounding_check is not complete"
    return None


def _validate_work_mark_phase(model: TodoState, target: LifecyclePhase, *, worktree_cwd: str | None) -> str | None:
    if target == LifecyclePhase.BUILD_STARTED:
        if model.lifecycle_phase != LifecyclePhase.PREPARED.value and not _phase_complete(
            model, LifecyclePhase.GROUNDING_CHECK, worktree_cwd=worktree_cwd
        ):
            return "Cannot set build_started: prepared prerequisites are not satisfied"
        return None
    if target == LifecyclePhase.BUILD_COMPLETE:
        if (
            not model.build_completed_at
            and worktree_cwd is not None
            and not _has_build_commits_beyond_main(worktree_cwd)
        ):
            return f"Cannot set build_complete: no commits beyond main in {worktree_cwd}"
        return None
    if target == LifecyclePhase.REVIEW_CHANGES_REQUESTED and model.build_review.verdict != "changes_requested":
        return (
            "Cannot set review_changes_requested: "
            f"build_review.verdict must be 'changes_requested', got '{model.build_review.verdict}'"
        )
    if target == LifecyclePhase.REVIEW_APPROVED and model.build_review.verdict != "approve":
        return f"Cannot set review_approved: build_review.verdict must be 'approve', got '{model.build_review.verdict}'"
    if target == LifecyclePhase.FINALIZE_READY and model.finalize.status != "ready":
        return f"Cannot set finalize_ready: finalize.status must be 'ready', got '{model.finalize.status}'"
    if target == LifecyclePhase.HANDED_OFF and model.finalize.status != "handed_off":
        return f"Cannot set handed_off: finalize.status must be 'handed_off', got '{model.finalize.status}'"
    return None


def _validate_mark_phase_target(
    model: TodoState,
    target: LifecyclePhase,
    *,
    worktree_cwd: str | None,
) -> str | None:
    if target == LifecyclePhase.PREPARED or target in (
        LifecyclePhase.INPUT_ASSESSMENT,
        LifecyclePhase.TRIANGULATION,
        LifecyclePhase.REQUIREMENTS_REVIEW,
        LifecyclePhase.TEST_SPEC_BUILD,
        LifecyclePhase.TEST_SPEC_REVIEW,
        LifecyclePhase.PLAN_DRAFTING,
        LifecyclePhase.PLAN_REVIEW,
        LifecyclePhase.GATE,
        LifecyclePhase.GROUNDING_CHECK,
        LifecyclePhase.RE_GROUNDING,
    ):
        return _validate_prepare_mark_phase(model, target, worktree_cwd=worktree_cwd)
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
    worktree_cwd = str(Path(cwd) / WORKTREE_DIR / slug)
    wt = worktree_cwd if Path(worktree_cwd).exists() else None
    error = validate_mark_phase_preconditions(raw_state, phase, wt)
    if error:
        raise ValueError(error)
    writer = StateWriter(raw_state)
    normalize_mark_phase(writer.state, LifecyclePhase(phase), worktree_cwd=wt)
    payload = writer.to_dict()
    write_phase_state(cwd, slug, payload)
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

    For build_review: when the stored ``baseline_commit`` is empty (first
    stamp), it is initialized from the current worktree HEAD so round 2+
    re-review dispatch can scope the diff to commits since the last verdict.

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
        db = _get_todos_db_sync(cwd)
        state = read_phase_state(cwd, slug)
        writer = StateWriter(state)
        build_review = writer.state.build_review
        build_review.verdict = verdict
        build_review.reviewed_at = datetime.now(UTC).isoformat()
        if not build_review.baseline_commit:
            project_root = _project_root_from_cwd(cwd)
            worktree_path = str(Path(project_root) / WORKTREE_DIR / slug)
            head = get_head_commit(worktree_path)
            if head:
                build_review.baseline_commit = head
        apply_authoritative_signal(writer.state, "verdict", phase=phase)
        return writer.commit_sync(db, slug)

    if phase not in _PREPARE_VERDICT_PHASES:
        raise ValueError(
            f"invalid review phase '{phase}': must be one of "
            f"{', '.join((*_PREPARE_VERDICT_PHASES, _BUILD_VERDICT_PHASE))}"
        )
    if verdict not in _PREPARE_VERDICT_VALUES:
        raise ValueError(f"invalid verdict '{verdict}': must be one of {', '.join(_PREPARE_VERDICT_VALUES)}")

    db = _get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    writer = StateWriter(state)
    ReviewManager(writer).stamp_verdict(phase, verdict)
    apply_authoritative_signal(writer.state, "verdict", phase=phase)
    return writer.commit_sync(db, slug)


def stamp_finalize_ready(cwd: str, slug: str) -> dict[str, StateValue]:
    """Stamp finalize state for integration handoff.

    The worktree must exist, have no uncommitted changes, and the worktree HEAD,
    local branch ref, and remote branch ref must all resolve to the same commit.
    On success, writes a :class:`FinalizeModel` with ``status="ready"``.

    The caller session identity is not stored here — it flows directly from
    the API route's ``CallerIdentity`` into the event payload.

    Args:
        cwd: Project root directory (not worktree)
        slug: Work item slug

    Returns:
        Updated state dict

    Raises:
        RuntimeError: when any validation step fails.
    """
    project_root = _project_root_from_cwd(cwd)
    worktree_path = Path(project_root) / WORKTREE_DIR / slug
    if not worktree_path.exists():
        raise RuntimeError(f"finalize_ready: worktree not found at {worktree_path}")
    if has_uncommitted_changes(project_root, slug):
        raise RuntimeError(
            f"finalize_ready: worktree {WORKTREE_DIR}/{slug} has uncommitted changes — commit before finalizing"
        )

    worktree_head = get_head_commit(str(worktree_path))
    branch_head = get_ref_commit(project_root, slug)
    if not worktree_head or not branch_head or worktree_head != branch_head:
        raise RuntimeError(
            f"finalize_ready: worktree HEAD ({worktree_head!r}) does not match branch ref {slug!r} ({branch_head!r})"
        )

    remote_head = get_remote_branch_head(project_root, slug)
    if not remote_head or remote_head != branch_head:
        raise RuntimeError(
            f"finalize_ready: remote branch {slug!r} ({remote_head!r}) "
            f"does not match local branch ({branch_head!r}) — push first"
        )

    db = _get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    writer = StateWriter(state)
    now = datetime.now(UTC).isoformat()
    writer.state.finalize = FinalizeModel(
        status="ready",
        branch=slug,
        sha=branch_head,
        ready_at=now,
        handed_off_at="",
    )
    apply_authoritative_signal(writer.state, "finalize_ready")
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
    db = _get_todos_db_sync(cwd)
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
    """Stamp all primitives required for ``derive_prepare_phase`` to return PREPARED.

    Fast-track path used by ``telec todo mark-ready``, ``telec todo from-main``, and
    prepped ``telec todo dump`` to short-circuit the full prepare lifecycle. Validates
    that requirements and implementation-plan artifacts exist and that a git HEAD is
    reachable BEFORE any state is persisted. Only after validation succeeds does the
    function generate the quality-checklist artifact when missing, stamp DOR pass,
    the current git HEAD as the grounding baseline, the prepare review verdicts
    (requirements is stamped ``skipped`` for prepped todos — there is no
    requirements artifact to review), and the authoritative ``prepare_phase =
    "prepared"`` commitment. Validation failures raise and no partial state is
    written, so callers see the error and the todo stays in its prior phase.

    Args:
        cwd: Project root directory (not worktree)
        slug: Work item slug

    Returns:
        Updated state dict

    Raises:
        ValueError: when a required artifact is missing or git HEAD cannot be read.
    """
    # pylint: disable=too-many-locals,too-many-statements
    project_root = _project_root_from_cwd(cwd)
    db = _get_todos_db_sync(cwd)
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
    writer.state.prepare_phase = ""
    writer.state.work_phase = ""
    if kind not in ("prepped", "bug"):
        writer.state.artifacts.requirements.digest = _artifact_digest(cwd, slug, "requirements")
        writer.state.artifacts.requirements.produced_at = now_iso
    if kind != "bug":
        writer.state.artifacts.implementation_plan.digest = _artifact_digest(cwd, slug, "implementation-plan")
        writer.state.artifacts.implementation_plan.produced_at = now_iso

    return writer.commit_sync(db, slug)


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
    db = _get_todos_db_sync(cwd)
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

    db = _get_todos_db_sync(cwd)
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
        return read_phase_state(cwd, slug)

    db = _get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    writer = StateWriter(state)
    entry = getattr(writer.state.artifacts, artifact_key, None)
    if not isinstance(entry, ArtifactEntry):
        raise ValueError(f"unknown artifact phase '{artifact_key}'")
    entry.produced_at = datetime.now(UTC).isoformat()
    entry.stale = False
    return writer.commit_sync(db, slug)


__all__ = [
    "_BUILD_VERDICT_PHASE",
    "_BUILD_VERDICT_VALUES",
    "_file_sha256",
    "_get_todos_db_sync",
    "_is_review_round_limit_reached",
    "_normalize_finalize_state",
    "_project_root_from_cwd",
    "_review_scope_note",
    "apply_prepared_state",
    "has_pending_deferrals",
    "is_bug_todo",
    "is_prepped_todo",
    "mark_phase_state",
    "read_breakdown_state",
    "read_phase_state",
    "read_text_sync",
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
