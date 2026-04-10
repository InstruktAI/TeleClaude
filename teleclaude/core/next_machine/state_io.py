"""State I/O — pure read/write operations for work-item state files.

All state read/write, mark operations, review helpers, and phase status checks.
No imports from core.py (circular-import guard).
"""

# pylint: disable=cyclic-import  # State helpers and lifecycle/slug adapters still cross-reference during migration.

from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import (
    DEFAULT_MAX_REVIEW_ROUNDS,
    REVIEW_APPROVE_MARKER,
    FinalizeState,
    ItemPhase,
    PhaseName,
    PhaseStatus,
    PreparePhase,
    StateValue,
    default_state,
)
from teleclaude.core.next_machine.file_io import (
    file_sha256 as _file_sha256,
)
from teleclaude.core.next_machine.file_io import (
    read_text_sync,
    write_text_sync,
)
from teleclaude.project_root import resolve_main_repo_root

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Project root / DB helpers
# ---------------------------------------------------------------------------


def _project_root_from_cwd(cwd: str) -> str:
    """Resolve project root from a path that may be inside a worktree."""
    return str(resolve_main_repo_root(cwd))


_db_cache: dict[str, TodosDb] = {}


def _get_todos_db_sync(cwd: str) -> TodosDb:
    """Return a cached TodosDb for the project owning *cwd*.

    Schema already exists (daemon creates it at startup). Skips initialize_sync
    after first call to avoid repeated DDL write locks on the database.
    """
    from teleclaude.core.todos_db import TodosDb, _new_instance_hook  # pylint: disable=import-outside-toplevel

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

# Nested keys that require deep-merge to preserve sub-key defaults
_DEEP_MERGE_KEYS = frozenset({"requirements_review", "plan_review", "grounding", "artifacts", "audit"})

# Valid prepare sub-phases that accept verdicts via mark-phase
_PREPARE_VERDICT_PHASES = ("requirements_review", "test_spec_review", "plan_review")
_PREPARE_VERDICT_VALUES = ("approve", "needs_work", "needs_decision")

# Valid prepare_phase values for direct phase advancement
_PREPARE_PHASE_VALUES = tuple(p.value for p in PreparePhase)


# ---------------------------------------------------------------------------
# State read/write
# ---------------------------------------------------------------------------


def get_state_path(cwd: str, slug: str) -> Path:
    """Get path to state.yaml in worktree."""
    return Path(cwd) / "todos" / slug / "state.yaml"


def _deep_merge_state(defaults: dict[str, StateValue], persisted: dict[str, StateValue]) -> dict[str, StateValue]:
    """Recursively merge persisted state onto defaults for nested dict keys.

    For keys in _DEEP_MERGE_KEYS: merge sub-dicts recursively so that sub-keys
    introduced in default_state() are added to older persisted state shapes.
    For all other keys: persisted wins outright (shallow update behaviour).
    """
    result = copy.deepcopy(defaults)
    for key, value in persisted.items():
        if key in _DEEP_MERGE_KEYS:
            default_val = result.get(key)
            if isinstance(default_val, dict) and isinstance(value, dict):
                # Recurse one level: merge nested dicts
                merged_nested: dict[str, StateValue] = copy.deepcopy(default_val)
                for nested_key, nested_val in value.items():
                    if isinstance(merged_nested.get(nested_key), dict) and isinstance(nested_val, dict):
                        inner: dict[str, StateValue] = copy.deepcopy(merged_nested[nested_key])  # type: ignore[arg-type]  # pylint: disable=line-too-long
                        inner.update(nested_val)
                        merged_nested[nested_key] = inner
                    else:
                        merged_nested[nested_key] = nested_val
                result[key] = merged_nested
            else:
                result[key] = value
        else:
            result[key] = value
    return result


def _normalize_finalize_state(raw: object) -> FinalizeState:
    finalize: FinalizeState = {"status": "pending"}
    if not isinstance(raw, dict):
        return finalize

    status = raw.get("status")
    if isinstance(status, str) and status in {"pending", "ready", "handed_off"}:
        finalize["status"] = status

    for key in ("branch", "sha", "ready_at", "worker_session_id", "handed_off_at", "handoff_session_id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            finalize[key] = value.strip()
    return finalize


def _migrate_v1_to_v2(state: dict[str, StateValue]) -> dict[str, StateValue]:
    """Migrate a v1 bag-of-fields state dict to v2 format.

    Derives ``current`` from the legacy field combination using precedence:
    finalize → review → build → prepare_phase → fallback.
    Removes legacy top-level fields (build, review, prepare_phase).
    """
    result = dict(state)

    # Derive current from legacy fields (furthest-progressed wins)
    finalize = result.get("finalize")
    finalize_status = finalize.get("status") if isinstance(finalize, dict) else None
    review = result.get("review", "")
    build = result.get("build", "")
    prepare_phase = str(result.get("prepare_phase", "")).strip()

    if finalize_status == "handed_off":
        current = "finalize_handed_off"
    elif finalize_status == "ready":
        current = "finalize_ready"
    elif review == PhaseStatus.APPROVED.value:
        current = "review_approved"
    elif review == PhaseStatus.CHANGES_REQUESTED.value:
        current = "review_changes_requested"
    elif review in (PhaseStatus.PENDING.value, "started") and build == PhaseStatus.COMPLETE.value:
        current = "review_pending"
    elif build == PhaseStatus.COMPLETE.value:
        current = "build_complete"
    elif build == "started":
        current = "build_started"
    elif prepare_phase and prepare_phase in _PREPARE_PHASE_VALUES:
        current = prepare_phase
    else:
        current = "input_assessment"

    result["current"] = current
    result["schema_version"] = 2
    result["history"] = result.get("history", [])

    # Remove legacy fields
    for key in ("build", "review", "prepare_phase"):
        result.pop(key, None)

    return result


def read_phase_state(cwd: str, slug: str) -> dict[str, StateValue]:
    """Read state for a work item from todos.db.

    Returns default state if no state exists in the database.
    V2 blobs are returned directly (self-contained).
    V1 blobs are deep-merged with defaults and migrated to v2.
    """
    db = _get_todos_db_sync(cwd)
    state = db.read_state_sync(slug)

    if state is None:
        return default_state()

    # V2: self-contained, skip deep-merge
    if state.get("schema_version") == 2:
        if "finalize" in state:
            state["finalize"] = _normalize_finalize_state(state.get("finalize"))  # type: ignore[assignment]
        return state

    # V1: deep-merge with defaults, then migrate
    merged = _deep_merge_state(default_state(), state)
    merged["finalize"] = _normalize_finalize_state(state.get("finalize"))  # type: ignore[assignment]

    # Legacy phase migration (coarse-grained pending/in_progress/done)
    if "phase" not in state:
        build = state.get(PhaseName.BUILD.value)
        if isinstance(build, str) and build != PhaseStatus.PENDING.value:
            merged["phase"] = ItemPhase.IN_PROGRESS.value
        else:
            merged["phase"] = ItemPhase.PENDING.value
    elif state.get("phase") == "ready":
        merged["phase"] = ItemPhase.PENDING.value

    return _migrate_v1_to_v2(merged)


def write_phase_state(cwd: str, slug: str, state: dict[str, StateValue]) -> None:
    """Write state to todos.db."""
    db = _get_todos_db_sync(cwd)
    db.write_state_sync(slug, state)


# ---------------------------------------------------------------------------
# Mark operations
# ---------------------------------------------------------------------------


def mark_phase(cwd: str, slug: str, target: str) -> dict[str, StateValue]:
    """Target a lifecycle state, routing through the StateMachine engine.

    Moves to the named target state. On_enter handlers on the state definition
    handle all side effects (review bookkeeping, grounding, finalize validation).

    Args:
        cwd: Worktree or project root directory
        slug: Work item slug
        target: Target state name (e.g. "prepared", "build_complete", "review_approved")

    Returns:
        Updated state dict
    """
    from teleclaude.core.next_machine.slug_resolution import (  # pylint: disable=import-outside-toplevel
        resolve_canonical_project_root,
    )
    from teleclaude.core.next_machine.state_machine import TargetContext  # pylint: disable=import-outside-toplevel
    from teleclaude.core.next_machine.state_mutation import StateWriter  # pylint: disable=import-outside-toplevel
    from teleclaude.core.next_machine.work_lifecycle import (  # pylint: disable=import-outside-toplevel
        build_lifecycle_machine,
    )
    from teleclaude.session_identity import get_session_id  # pylint: disable=import-outside-toplevel

    state = read_phase_state(cwd, slug)
    machine = build_lifecycle_machine()

    project_root = resolve_canonical_project_root(cwd)
    worktree = (
        str(Path(project_root) / WORKTREE_DIR / slug) if (Path(project_root) / WORKTREE_DIR / slug).exists() else cwd
    )
    ctx = TargetContext(
        worktree_path=worktree,
        project_root=project_root,
        slug=slug,
        actor_id=get_session_id() or "mark-phase",
        at=datetime.now(UTC).isoformat(),
    )
    next_state = machine.target(state, target, ctx)
    # Route the post-transition payload through StateWriter so the persistence
    # path shares one validated boundary with prepare_steps/on_enter handlers.
    writer = StateWriter(next_state)
    return writer.commit_sync(_get_todos_db_sync(cwd), slug)


def stamp_verdict(cwd: str, slug: str, phase: str, verdict: str) -> dict[str, StateValue]:
    """Stamp a prepare sub-phase verdict via the typed review boundary.

    Args:
        cwd: Project root directory (not worktree)
        slug: Work item slug
        phase: Prepare sub-phase (requirements_review, plan_review)
        verdict: Verdict value (approve, needs_work)

    Returns:
        Updated state dict
    """
    from teleclaude.core.next_machine.state_mutation import (  # pylint: disable=import-outside-toplevel
        ReviewManager,
        StateWriter,
    )

    if phase not in _PREPARE_VERDICT_PHASES:
        raise ValueError(f"invalid prepare phase '{phase}': must be one of {', '.join(_PREPARE_VERDICT_PHASES)}")
    if verdict not in _PREPARE_VERDICT_VALUES:
        raise ValueError(f"invalid verdict '{verdict}': must be one of {', '.join(_PREPARE_VERDICT_VALUES)}")

    db = _get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    writer = StateWriter(state)
    ReviewManager(writer).stamp_verdict(phase, verdict)
    return writer.commit_sync(db, slug)


# ---------------------------------------------------------------------------
# Review state helpers
# ---------------------------------------------------------------------------


def _review_scope_note(cwd: str, slug: str) -> str:
    """Build an iterative review scope note from state.yaml metadata."""
    state = read_phase_state(cwd, slug)
    review_round_raw = state.get("review_round")
    max_rounds_raw = state.get("max_review_rounds")
    review_round = review_round_raw if isinstance(review_round_raw, int) else 0
    max_rounds = max_rounds_raw if isinstance(max_rounds_raw, int) else DEFAULT_MAX_REVIEW_ROUNDS
    next_round = review_round + 1
    baseline = state.get("review_baseline_commit")
    baseline_sha = baseline if isinstance(baseline, str) else ""
    unresolved = state.get("unresolved_findings")
    unresolved_ids = unresolved if isinstance(unresolved, list) else []

    unresolved_text = ", ".join(str(x) for x in unresolved_ids) if unresolved_ids else "none"
    baseline_text = baseline_sha if baseline_sha else "unset (initial full review)"
    return (
        f"Review iteration: round {next_round}/{max_rounds}. "
        "Round 1 is full-scope. Round 2+ must be incremental: review only commits since "
        f"{baseline_text} plus unresolved IDs [{unresolved_text}]."
    )


def _is_review_round_limit_reached(cwd: str, slug: str) -> tuple[bool, int, int]:
    """Return whether next review round would exceed configured max."""
    state = read_phase_state(cwd, slug)
    review_round_raw = state.get("review_round")
    max_rounds_raw = state.get("max_review_rounds")
    review_round = review_round_raw if isinstance(review_round_raw, int) else 0
    max_rounds = max_rounds_raw if isinstance(max_rounds_raw, int) else DEFAULT_MAX_REVIEW_ROUNDS
    return (review_round + 1) > max_rounds, review_round, max_rounds


def read_breakdown_state(cwd: str, slug: str) -> dict[str, bool | list[str]] | None:
    """Read breakdown state from todos.db for the given slug.

    Returns:
        Breakdown state dict with 'assessed' and 'todos' keys, or None if not present.
    """
    state = read_phase_state(cwd, slug)
    breakdown = state.get("breakdown")
    if breakdown is None or not isinstance(breakdown, dict):
        return None
    # At this point breakdown is dict with bool/list values from json
    return dict(breakdown)  # type: ignore


def write_breakdown_state(cwd: str, slug: str, assessed: bool, todos: list[str]) -> None:
    """Write breakdown state via the typed write boundary.

    Args:
        cwd: Project root directory
        slug: Work item slug
        assessed: Whether breakdown assessment has been performed
        todos: List of todo slugs created from split (empty if no breakdown)
    """
    from teleclaude.core.next_machine.state_mutation import (  # pylint: disable=import-outside-toplevel
        StateWriter,
    )
    from teleclaude.types.todos import BreakdownState  # pylint: disable=import-outside-toplevel

    db = _get_todos_db_sync(cwd)
    state = read_phase_state(cwd, slug)
    writer = StateWriter(state)
    writer.state.breakdown = BreakdownState(assessed=assessed, todos=list(todos))
    writer.commit_sync(db, slug)


# ---------------------------------------------------------------------------
# Phase status checks
# ---------------------------------------------------------------------------


_BUILD_COMPLETE_STATES = frozenset(
    {
        "build_complete",
        "review_pending",
        "review_changes_requested",
        "review_approved",
        "finalize_ready",
        "finalize_handed_off",
    }
)


def is_build_complete(cwd: str, slug: str) -> bool:
    """Check if build phase is complete (current is at or past build_complete)."""
    state = read_phase_state(cwd, slug)
    current = str(state.get("current", ""))
    return current in _BUILD_COMPLETE_STATES


def is_review_approved(cwd: str, slug: str) -> bool:
    """Check if review phase is approved."""
    state = read_phase_state(cwd, slug)
    current = str(state.get("current", ""))
    return current in ("review_approved", "finalize_ready", "finalize_handed_off")


def is_review_changes_requested(cwd: str, slug: str) -> bool:
    """Check if review requested changes."""
    state = read_phase_state(cwd, slug)
    current = str(state.get("current", ""))
    return current == "review_changes_requested"


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


def check_review_status(cwd: str, slug: str) -> str:
    """Check review status for a work item.

    Returns:
        - "missing" if review-findings artifact doesn't exist
        - "approved" if contains "[x] APPROVE"
        - "changes_requested" otherwise
    """
    db = _get_todos_db_sync(cwd)
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        row = conn.execute(
            "SELECT content FROM todo_artifacts WHERE slug = ? AND name = 'review-findings' LIMIT 1",  # guard: raw-sql
            (slug,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return "missing"

    content: str = row[0]
    if REVIEW_APPROVE_MARKER in content:
        return PhaseStatus.APPROVED.value
    return PhaseStatus.CHANGES_REQUESTED.value


# Artifact keys that can be stamped via mark-phase after worker output is verified.
_PREPARE_ARTIFACT_FILES = {
    "requirements": "requirements.md",
    "implementation_plan": "implementation-plan.md",
}
_PREPARE_ARTIFACT_PHASES = (*_PREPARE_ARTIFACT_FILES.keys(), "test_specs")


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
    from teleclaude.core.next_machine.state_mutation import (  # pylint: disable=import-outside-toplevel
        StateWriter,
    )
    from teleclaude.types.todos import ArtifactEntry  # pylint: disable=import-outside-toplevel

    if artifact_key not in _PREPARE_ARTIFACT_PHASES:
        raise ValueError(f"invalid artifact key '{artifact_key}': must be one of {', '.join(_PREPARE_ARTIFACT_PHASES)}")

    artifact_file = _PREPARE_ARTIFACT_FILES.get(artifact_key)
    if artifact_file is not None:
        from teleclaude.core.next_machine.artifacts import (  # pylint: disable=import-outside-toplevel
            record_artifact_produced,
        )

        record_artifact_produced(cwd, slug, artifact_file)
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
    "_file_sha256",
    "_get_todos_db_sync",
    "_is_review_round_limit_reached",
    "_normalize_finalize_state",
    "_project_root_from_cwd",
    "_review_scope_note",
    "check_review_status",
    "get_state_path",
    "has_pending_deferrals",
    "is_bug_todo",
    "is_build_complete",
    "is_prepped_todo",
    "is_review_approved",
    "is_review_changes_requested",
    "mark_phase",
    "read_breakdown_state",
    "read_phase_state",
    "read_text_sync",
    "stamp_artifact",
    "stamp_verdict",
    "write_breakdown_state",
    "write_phase_state",
    "write_text_sync",
]
