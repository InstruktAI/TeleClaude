"""State I/O — pure read/write operations for work-item state files.

All state read/write, review helpers, and phase status checks. No imports from
core.py (circular-import guard).
"""

# pylint: disable=cyclic-import  # State helpers and lifecycle/slug adapters still cross-reference during migration.

from __future__ import annotations

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
)
from teleclaude.core.next_machine.kinds import (
    KIND_BUG,
    KIND_ENTRY_PHASE,
    canonical_kind,
)
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.provenance import clear_artifact_provenance, sync_artifact_provenance_sync_subset
from teleclaude.core.next_machine.review_evidence import (
    BUILD_REVIEW_PHASE,
    PREPARE_REVIEW_PHASES,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
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
_PREPARE_VERDICT_PHASES = PREPARE_REVIEW_PHASES
_PREPARE_VERDICT_VALUES = ("approve", "needs_work", "needs_decision")

# Build-review verdict phase and allowed values
_BUILD_VERDICT_PHASE = BUILD_REVIEW_PHASE
_BUILD_VERDICT_VALUES = ("approve", "changes_requested")

_ARTIFACT_STATE_KEYS: dict[str, str] = {
    STATE_KEY_INPUT: ARTIFACT_INPUT,
    STATE_KEY_PRD: ARTIFACT_PRD,
    STATE_KEY_REQUIREMENTS: ARTIFACT_REQUIREMENTS,
    STATE_KEY_ARCHITECTURE: ARTIFACT_ARCHITECTURE,
    STATE_KEY_IMPLEMENTATION_PLAN: ARTIFACT_IMPLEMENTATION_PLAN,
    STATE_KEY_TASK_PLAN: ARTIFACT_TASK_PLAN,
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
    "ensure_quality_checklist",
    "has_pending_deferrals",
    "is_bug_todo",
    "read_breakdown_state",
    "read_phase_state",
    "read_text_sync",
    "stamp_artifact",
    "stamp_finalize_ready",
    "sync_artifact_digest",
    "write_breakdown_state",
    "write_phase_state",
    "write_text_sync",
]
