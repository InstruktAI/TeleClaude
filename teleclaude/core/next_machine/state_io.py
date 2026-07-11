"""State I/O — pure read/write operations for work-item state files.

All state read/write, review helpers, and phase status checks. No imports from
core.py (circular-import guard).
"""

# pylint: disable=cyclic-import  # State helpers and lifecycle/slug adapters still cross-reference during migration.

from __future__ import annotations

import hashlib as _hl
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import (
    ARTIFACT_ARCHITECTURE,
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_INPUT,
    ARTIFACT_PRD,
    ARTIFACT_QUALITY_CHECKLIST,
    ARTIFACT_REQUIREMENTS,
    ARTIFACT_TASK_PLAN,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
    STATE_KEY_REQUIREMENTS,
    STATE_KEY_TASK_PLAN,
    WORKTREE_DIR,
)
from teleclaude.core.next_machine._types import DEFAULT_MAX_REVIEW_ROUNDS, StateValue, default_state
from teleclaude.core.next_machine.file_io import file_sha256 as _file_sha256
from teleclaude.core.next_machine.file_io import read_text_sync, write_text_sync
from teleclaude.core.next_machine.git_ops import (
    extract_referenced_paths,
    get_head_commit,
    get_origin_main_sha,
    run_git_command,
)
from teleclaude.core.next_machine.kinds import (
    FAST_TRACK_PREPARED_KINDS,
    KIND_BUG,
    KIND_ENTRY_PHASE,
    KIND_FEATURE,
    canonical_kind,
)
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.provenance import clear_artifact_provenance, sync_artifact_provenance_sync_subset
from teleclaude.core.next_machine.state_mutation import ReviewManager, StateWriter
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.project_root import resolve_project_root
from teleclaude.types.todos import BreakdownState, FinalizeModel

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)


def initial_todo_state_for_kind(kind: str | None) -> dict[str, StateValue]:
    """Return the initial persisted state for a newly created todo kind."""
    state = default_state()
    if kind is None:
        state["kind"] = None
        state.pop("lifecycle_phase", None)
        return state

    canonical = canonical_kind(kind)
    state["kind"] = canonical
    entry_phase = KIND_ENTRY_PHASE[canonical]
    state["lifecycle_phase"] = entry_phase.value
    return state


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
    state = read_phase_state(cwd, slug)
    writer = StateWriter(state)
    db = get_todos_db_sync(cwd)
    digest = _sync_artifact_provenance_subset_from_db(cwd, slug, artifact_name, writer, db=db)
    writer.commit_sync(db, slug)

    if produced:
        _emit_prepare_event(
            "domain.software-development.prepare.artifact_produced",
            {"slug": slug, "artifact": artifact_name, "digest": digest},
        )


def sync_artifact_digest(cwd: str, slug: str, artifact_name: str) -> None:
    """Refresh the stored digest for an artifact without stamping completion."""
    _sync_artifact_state(cwd, slug, artifact_name, produced=False)


def _sync_artifact_provenance_subset_from_db(
    cwd: str,
    slug: str,
    artifact_name: str,
    writer: StateWriter,
    *,
    db: object | None = None,
) -> str:
    """Sync provenance fields available from sync callers and return the digest."""
    todos_db = db if db is not None else get_todos_db_sync(cwd)
    digest = _artifact_digest(cwd, slug, artifact_name)
    if not digest:
        clear_artifact_provenance(writer, slug, artifact_name)
        return ""
    # Never downgrade already-complete async provenance. The sync subset clears the
    # snippet anchors and resets async_provenance_complete, which makes
    # upstream-snippet drift fail-safe to `pending`. When full async provenance was
    # already established for this exact digest (the dump route syncs it before the
    # prepared fast-track runs), preserve it as-is.
    state_key = next((key for key, name in _ARTIFACT_STATE_KEYS.items() if name == artifact_name), None)
    if state_key is not None:
        entry = getattr(writer.state.artifacts, state_key)
        if entry.async_provenance_complete and entry.digest == digest:
            return digest
    artifact_body = todos_db.read_artifact_sync(slug, artifact_name)  # type: ignore[attr-defined]
    sync_artifact_provenance_sync_subset(
        writer,
        slug,
        artifact_name,
        repo_root=cwd,
        sha_at_write=get_origin_main_sha(cwd),
        referenced_paths=extract_referenced_paths(artifact_body),
        digest=digest,
    )
    return digest


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Valid prepare sub-phases that accept verdicts
_PREPARE_VERDICT_PHASES = (
    "requirements_review",
    "architecture_review",
    "plan_review",
)
_PREPARE_VERDICT_VALUES = ("approve", "needs_work", "needs_decision")

# Build-review verdict phase and allowed values
_BUILD_VERDICT_PHASE = "build_review"
_BUILD_VERDICT_VALUES = ("approve", "changes_requested")

_ARTIFACT_STATE_KEYS: dict[str, str] = {
    STATE_KEY_INPUT: ARTIFACT_INPUT,
    STATE_KEY_PRD: ARTIFACT_PRD,
    STATE_KEY_REQUIREMENTS: ARTIFACT_REQUIREMENTS,
    STATE_KEY_ARCHITECTURE: ARTIFACT_ARCHITECTURE,
    STATE_KEY_IMPLEMENTATION_PLAN: ARTIFACT_IMPLEMENTATION_PLAN,
    STATE_KEY_TASK_PLAN: ARTIFACT_TASK_PLAN,
}

# Maps a review phase name to the artifact state key it gates.
# Used by stamp_verdict to bind approved_digest and by the satisfaction walk
# to compare review approval against current artifact content.
_REVIEW_TO_ARTIFACT_KEY: dict[str, str] = {
    "requirements_review": STATE_KEY_REQUIREMENTS,
    "architecture_review": STATE_KEY_ARCHITECTURE,
    "plan_review": STATE_KEY_IMPLEMENTATION_PLAN,
}


def read_phase_state(cwd: str, slug: str) -> dict[str, StateValue]:
    """Read state for a work item from todos.db.

    Returns default state if no state exists in the database. Existing rows are
    upcycled by the ``TodosDb`` read path. v2 prepare blobs are persisted as
    v3 on first read so the migration decision is logged exactly once.
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


# ---------------------------------------------------------------------------
# Stamp operations
# ---------------------------------------------------------------------------


def stamp_verdict(cwd: str, slug: str, phase: str, verdict: str) -> dict[str, StateValue]:
    """Stamp a review phase verdict via the typed state boundary.

    Handles both prepare sub-phases (requirements_review, architecture_review,
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
        phase: Review phase key (requirements_review, architecture_review,
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

    project_root = str(resolve_project_root(cwd))
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

- [ ] PRD success criteria implemented according to scope
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

- [ ] PRD success criteria traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
- [ ] Findings written in `review-findings.md`
- [ ] Verdict recorded (APPROVE or REQUEST CHANGES)
- [ ] Requirement-Violation, Critical, and Important issues resolved or explicitly blocked
- [ ] Test coverage and regression risk assessed
- [ ] User-facing verification evidence reviewed
- [ ] Browser-based frontend or web UI changes verified with Playwright during review, or gap recorded as a finding

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in todo list (status: delivered)
- [ ] Worktree cleanup complete
"""


def _has_nontrivial_content(text: str) -> bool:
    """Return whether content has non-heading, non-whitespace lines."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return len(lines) > 0


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
    return row is not None and _has_nontrivial_content(row[0] or "")


async def ensure_quality_checklist(todos_db: TodosDb, slug: str) -> None:
    """Seed the standard quality checklist when its current content is trivial."""
    content = await todos_db.read_artifact(slug, ARTIFACT_QUALITY_CHECKLIST)
    if _has_nontrivial_content(content):
        return
    await todos_db.write_artifact(
        slug,
        ARTIFACT_QUALITY_CHECKLIST,
        _QUALITY_CHECKLIST_TEMPLATE.format(slug=slug),
        updated_by="work.prepared_entry",
    )


def apply_prepared_state(cwd: str, slug: str) -> dict[str, StateValue]:
    """Stamp all authoritative state required to make a todo `prepared`.

    Fast-track path used by ``--plan`` on a change todo to short-circuit the
    full prepare lifecycle.
    Validates that the PRD (or legacy requirements) and implementation-plan artifacts exist and
    that a git HEAD is reachable BEFORE any state is persisted. Only after
    validation succeeds does the function generate the quality-checklist
    artifact when missing, stamp DOR pass, the prepare review verdicts, the
    plan approval stamp, and the canonical `lifecycle_phase = "prepared"`
    commitment.
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
    project_root = str(resolve_project_root(cwd))
    db = get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    kind = state.get("kind")

    has_prd = _has_artifact_content(cwd, slug, ARTIFACT_PRD)
    has_legacy_requirements = _has_artifact_content(cwd, slug, ARTIFACT_REQUIREMENTS)
    if kind == KIND_FEATURE and not (has_prd or has_legacy_requirements):
        raise ValueError(f"Missing prd artifact with content for {slug}")
    if not _has_artifact_content(cwd, slug, ARTIFACT_IMPLEMENTATION_PLAN):
        raise ValueError(f"Missing implementation-plan artifact with content for {slug}")

    rc, _current_sha_raw, _ = run_git_command(["rev-parse", "HEAD"], cwd=project_root)
    if rc != 0:
        raise ValueError(f"git rev-parse HEAD failed (rc={rc}) in {project_root}")

    if not _has_artifact_content(cwd, slug, ARTIFACT_QUALITY_CHECKLIST):
        checklist_content = _QUALITY_CHECKLIST_TEMPLATE.format(slug=slug)
        now_iso = datetime.now(UTC).isoformat()
        digest = _hl.sha256(checklist_content.encode("utf-8")).hexdigest()
        conn = db._sync_conn()  # pylint: disable=protected-access
        try:
            id_row = conn.execute(
                "SELECT id FROM todo WHERE slug = ? AND status != 'delivered' LIMIT 1",  # guard: raw-sql
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

    writer = StateWriter(state)

    review_mgr = ReviewManager(writer)
    if kind != KIND_FEATURE:
        review_mgr.stamp_verdict("requirements_review", "skipped")
    else:
        review_mgr.stamp_verdict("requirements_review", "approve")

    review_mgr.stamp_verdict("plan_review", "approve")

    if input_digest:
        _sync_artifact_provenance_subset_from_db(cwd, slug, ARTIFACT_INPUT, writer, db=db)
    writer.state.lifecycle_phase = "prepared"
    if kind not in FAST_TRACK_PREPARED_KINDS and has_prd:
        _sync_artifact_provenance_subset_from_db(cwd, slug, ARTIFACT_PRD, writer, db=db)
    elif kind not in FAST_TRACK_PREPARED_KINDS and has_legacy_requirements:
        _sync_artifact_provenance_subset_from_db(cwd, slug, ARTIFACT_REQUIREMENTS, writer, db=db)
    _sync_artifact_provenance_subset_from_db(cwd, slug, ARTIFACT_IMPLEMENTATION_PLAN, writer, db=db)

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
        todos: List of child todo slugs created by breakdown (empty if no breakdown)
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
    """Return True when the todo state has kind == KIND_BUG."""
    state = read_phase_state(cwd, slug)
    return state.get("kind") == KIND_BUG


# Artifact keys that can be stamped after worker output is verified.
_PREPARE_ARTIFACT_NAMES = {
    STATE_KEY_PRD: ARTIFACT_PRD,
    STATE_KEY_REQUIREMENTS: ARTIFACT_REQUIREMENTS,
    STATE_KEY_ARCHITECTURE: ARTIFACT_ARCHITECTURE,
    STATE_KEY_IMPLEMENTATION_PLAN: ARTIFACT_IMPLEMENTATION_PLAN,
}


def stamp_artifact(cwd: str, slug: str, artifact_key: str) -> dict[str, StateValue]:
    """Stamp a file-backed prepare artifact as produced via the typed state.

    Records both digest and produced_at and binds upstream digests so the
    satisfaction walk can detect upstream changes.

    Args:
        cwd: Project root directory (not worktree)
        slug: Work item slug
        artifact_key: Artifact state key (e.g. architecture)

    Returns:
        Updated state dict
    """
    if artifact_key not in _PREPARE_ARTIFACT_NAMES:
        raise ValueError(f"invalid artifact key '{artifact_key}': must be one of {', '.join(_PREPARE_ARTIFACT_NAMES)}")
    artifact_name = _PREPARE_ARTIFACT_NAMES[artifact_key]
    _sync_artifact_state(cwd, slug, artifact_name, produced=True)
    return read_phase_state(cwd, slug)


__all__ = [
    "_BUILD_VERDICT_PHASE",
    "_BUILD_VERDICT_VALUES",
    "_file_sha256",
    "_is_review_round_limit_reached",
    "_review_scope_note",
    "apply_prepared_state",
    "ensure_quality_checklist",
    "has_pending_deferrals",
    "is_bug_todo",
    "read_breakdown_state",
    "read_phase_state",
    "read_text_sync",
    "stamp_artifact",
    "stamp_finalize_ready",
    "stamp_verdict",
    "sync_artifact_digest",
    "write_breakdown_state",
    "write_phase_state",
    "write_text_sync",
]
