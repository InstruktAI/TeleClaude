"""State I/O — pure read/write operations for work-item state files.

All state read/write, mark operations, review helpers, and phase status checks.
Git primitives needed internally by mark operations are co-located here.
No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import copy
import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import (
    DEFAULT_MAX_REVIEW_ROUNDS,
    DEFAULT_STATE,
    FINDING_ID_PATTERN,
    REVIEW_APPROVE_MARKER,
    FinalizeState,
    ItemPhase,
    PhaseName,
    PhaseStatus,
    PreparePhase,
    StateValue,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def read_text_sync(path: Path) -> str:
    """Read text from a file in a typed sync wrapper."""
    return path.read_text(encoding="utf-8")


def write_text_sync(path: Path, content: str) -> None:
    """Write text to a file in a typed sync wrapper."""
    path.write_text(content, encoding="utf-8")


def _file_sha256(path: Path) -> str:
    """Return sha256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Git primitives (needed by mark operations below)
# ---------------------------------------------------------------------------


def _get_head_commit(cwd: str) -> str:
    """Return HEAD commit hash for cwd, or empty string when unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return ""
    return result.stdout.strip()


def _get_ref_commit(cwd: str, ref: str) -> str:
    """Return commit hash for a git ref in cwd, or empty string when unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", ref],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return ""
    return result.stdout.strip()


def _get_remote_branch_head(cwd: str, branch: str) -> str:
    """Return origin/<branch> HEAD commit, or empty string when unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "ls-remote", "origin", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return ""
    parts = result.stdout.strip().split()
    return parts[0] if parts else ""


def _run_git_prepare(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Nested keys that require deep-merge to preserve sub-key defaults from v2 schema
_DEEP_MERGE_KEYS = frozenset({"requirements_review", "plan_review", "grounding", "artifacts", "audit"})

# Valid prepare sub-phases that accept verdicts via mark-phase
_PREPARE_VERDICT_PHASES = ("requirements_review", "test_spec_review", "plan_review")
_PREPARE_VERDICT_VALUES = ("approve", "needs_work", "needs_decision")

# Valid prepare_phase values for direct phase advancement
_PREPARE_PHASE_VALUES = tuple(p.value for p in PreparePhase)


# ---------------------------------------------------------------------------
# Finding ID helpers
# ---------------------------------------------------------------------------


def _extract_finding_ids(cwd: str, slug: str) -> list[str]:
    """Extract stable finding IDs (e.g. R1-F1) from review-findings.md."""
    review_path = Path(cwd) / "todos" / slug / "review-findings.md"
    if not review_path.exists():
        return []
    content = read_text_sync(review_path)
    seen: list[str] = []
    for match in FINDING_ID_PATTERN.findall(content):
        if match not in seen:
            seen.append(match)
    return seen


# ---------------------------------------------------------------------------
# State read/write
# ---------------------------------------------------------------------------


def get_state_path(cwd: str, slug: str) -> Path:
    """Get path to state.yaml in worktree."""
    return Path(cwd) / "todos" / slug / "state.yaml"


def _deep_merge_state(defaults: dict[str, StateValue], persisted: dict[str, StateValue]) -> dict[str, StateValue]:
    """Recursively merge persisted state onto defaults for nested dict keys.

    For keys in _DEEP_MERGE_KEYS: merge sub-dicts recursively so that sub-keys
    introduced in v2 DEFAULT_STATE are added to older persisted state shapes.
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
                        inner: dict[str, StateValue] = copy.deepcopy(merged_nested[nested_key])  # type: ignore[arg-type]
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


def _get_finalize_state(state: dict[str, StateValue]) -> FinalizeState:
    return _normalize_finalize_state(state.get("finalize"))


def read_phase_state(cwd: str, slug: str) -> dict[str, StateValue]:
    """Read state.yaml from worktree (falls back to state.json for backward compat).

    Returns default state if file doesn't exist.
    Migrates missing 'phase' field from existing build/dor state.
    Performs deep-merge for nested dict keys so v2 sub-key defaults are always present.
    """
    state_path = get_state_path(cwd, slug)
    # Backward compat: try state.json if state.yaml doesn't exist
    if not state_path.exists():
        legacy_path = state_path.with_name("state.json")
        if legacy_path.exists():
            state_path = legacy_path

    if not state_path.exists():
        return copy.deepcopy(DEFAULT_STATE)

    content = read_text_sync(state_path)
    raw_state = yaml.safe_load(content)
    if raw_state is None:
        state: dict[str, StateValue] = {}
    elif isinstance(raw_state, dict):
        state = raw_state
    else:
        logger.warning("Ignoring non-mapping phase state for %s/%s", cwd, slug)
        state = {}
    # Deep-merge: preserves v2 nested sub-key defaults that are absent in older persisted state
    merged = _deep_merge_state(copy.deepcopy(DEFAULT_STATE), state)
    merged["finalize"] = _normalize_finalize_state(state.get("finalize"))  # type: ignore[assignment]

    # Migration: derive phase from existing fields when missing from persisted state
    if "phase" not in state:
        build = state.get(PhaseName.BUILD.value)
        if isinstance(build, str) and build != PhaseStatus.PENDING.value:
            merged["phase"] = ItemPhase.IN_PROGRESS.value
        else:
            merged["phase"] = ItemPhase.PENDING.value
    elif state.get("phase") == "ready":
        # Migration: normalize persisted "ready" phase to "pending" (readiness is now derived from dor.score)
        merged["phase"] = ItemPhase.PENDING.value

    return merged


def write_phase_state(cwd: str, slug: str, state: dict[str, StateValue]) -> None:
    """Write state.yaml."""
    state_path = get_state_path(cwd, slug)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(state, default_flow_style=False, sort_keys=False)
    write_text_sync(state_path, content)


# ---------------------------------------------------------------------------
# Mark operations
# ---------------------------------------------------------------------------


def mark_phase(cwd: str, slug: str, phase: str, status: str) -> dict[str, StateValue]:
    """Mark a phase with a status.

    Args:
        cwd: Worktree directory (not main repo)
        slug: Work item slug
        phase: Phase to update (build, review)
        status: New status (pending, complete, approved, changes_requested)

    Returns:
        Updated state dict
    """
    state = read_phase_state(cwd, slug)
    state[phase] = status
    if phase == PhaseName.REVIEW.value:
        review_round = state.get("review_round")
        current_round = review_round if isinstance(review_round, int) else 0
        unresolved = state.get("unresolved_findings")
        unresolved_ids = list(unresolved) if isinstance(unresolved, list) else []
        resolved = state.get("resolved_findings")
        resolved_ids = list(resolved) if isinstance(resolved, list) else []

        if status in (PhaseStatus.CHANGES_REQUESTED.value, PhaseStatus.APPROVED.value):
            state["review_round"] = current_round + 1
            head_sha = _get_head_commit(cwd)
            if head_sha:
                state["review_baseline_commit"] = head_sha

        if status == PhaseStatus.CHANGES_REQUESTED.value:
            findings_ids = _extract_finding_ids(cwd, slug)
            state["unresolved_findings"] = findings_ids  # type: ignore[assignment]
            # Keep resolved IDs stable and de-duplicated
            state["resolved_findings"] = list(dict.fromkeys(str(i) for i in resolved_ids))
        elif status == PhaseStatus.APPROVED.value:
            merged = list(dict.fromkeys([*(str(i) for i in resolved_ids), *(str(i) for i in unresolved_ids)]))
            state["resolved_findings"] = merged  # type: ignore[assignment]
            state["unresolved_findings"] = []
    write_phase_state(cwd, slug, state)
    return state


def mark_prepare_verdict(cwd: str, slug: str, phase: str, verdict: str) -> dict[str, StateValue]:
    """Mark a prepare sub-phase verdict in state.yaml.

    Args:
        cwd: Project root directory (not worktree)
        slug: Work item slug
        phase: Prepare sub-phase (requirements_review, plan_review)
        verdict: Verdict value (approve, needs_work)

    Returns:
        Updated state dict
    """
    if phase not in _PREPARE_VERDICT_PHASES:
        raise ValueError(f"invalid prepare phase '{phase}': must be one of {', '.join(_PREPARE_VERDICT_PHASES)}")
    if verdict not in _PREPARE_VERDICT_VALUES:
        raise ValueError(f"invalid verdict '{verdict}': must be one of {', '.join(_PREPARE_VERDICT_VALUES)}")

    state = read_phase_state(cwd, slug)
    review_dict = state.get(phase)
    if not isinstance(review_dict, dict):
        review_dict = {}
    review_dict["verdict"] = verdict
    state[phase] = review_dict
    write_phase_state(cwd, slug, state)
    return state


def mark_prepare_phase(cwd: str, slug: str, status: str) -> dict[str, StateValue]:
    """Set prepare_phase directly in state.yaml.

    When advancing to 'prepared', also stamps grounding as valid with the
    current HEAD sha and input digest so the work state machine accepts it.

    Args:
        cwd: Project root directory (not worktree)
        slug: Work item slug
        status: PreparePhase value (e.g. prepared, gate, plan_review)

    Returns:
        Updated state dict
    """
    if status not in _PREPARE_PHASE_VALUES:
        raise ValueError(f"invalid prepare_phase '{status}': must be one of {', '.join(_PREPARE_PHASE_VALUES)}")

    state = read_phase_state(cwd, slug)
    state["prepare_phase"] = status

    if status == PreparePhase.PREPARED.value:
        grounding = state.get("grounding", {})
        grounding_dict = {**DEFAULT_STATE["grounding"], **(grounding if isinstance(grounding, dict) else {})}  # type: ignore
        rc, current_sha, _ = _run_git_prepare(["rev-parse", "HEAD"], cwd=cwd)
        if rc == 0 and current_sha.strip():
            grounding_dict["base_sha"] = current_sha.strip()
        input_path = Path(cwd) / "todos" / slug / "input.md"
        if input_path.exists():
            grounding_dict["input_digest"] = hashlib.sha256(input_path.read_bytes()).hexdigest()
        grounding_dict["valid"] = True
        grounding_dict["last_grounded_at"] = datetime.now(UTC).isoformat()
        grounding_dict["invalidation_reason"] = ""
        grounding_dict["changed_paths"] = []
        state["grounding"] = grounding_dict

    write_phase_state(cwd, slug, state)
    return state


def mark_finalize_ready(cwd: str, slug: str, worker_session_id: str = "") -> dict[str, StateValue]:
    """Record durable finalize readiness after finalizer prepare succeeds.

    The orchestrator owns this write after verifying the worker reported
    FINALIZE_READY. The record becomes the single source of truth consumed by
    the subsequent slug-specific `telec todo work {slug}` handoff step.
    """
    from teleclaude.core.next_machine.git_ops import has_uncommitted_changes  # lazy: avoids circular dep

    worktree_cwd = str(Path(cwd) / WORKTREE_DIR / slug)
    if not Path(worktree_cwd).exists():
        raise ValueError(f"worktree not found at {worktree_cwd}")
    if has_uncommitted_changes(cwd, slug):
        raise ValueError(f"worktree {WORKTREE_DIR}/{slug} has uncommitted changes")

    worktree_head = _get_head_commit(worktree_cwd)
    branch_head = _get_ref_commit(cwd, slug)
    if not worktree_head or not branch_head:
        raise ValueError(f"unable to resolve finalized branch head for {slug}")
    if worktree_head != branch_head:
        raise ValueError(
            f"branch {slug} does not match worktree HEAD after finalize prepare "
            f"(branch={branch_head or '<missing>'}, worktree={worktree_head or '<missing>'})"
        )

    remote_head = _get_remote_branch_head(cwd, slug)
    if not remote_head:
        raise ValueError(f"origin/{slug} is missing — push the finalized branch before marking ready")
    if remote_head != branch_head:
        raise ValueError(
            f"origin/{slug} is at {remote_head}, expected finalized head {branch_head}; "
            "push the latest branch head before marking ready"
        )

    state = read_phase_state(worktree_cwd, slug)
    finalize = _get_finalize_state(state)
    if finalize.get("status") == "handed_off" and finalize.get("sha") == branch_head:
        return state
    if finalize.get("status") == "ready" and finalize.get("sha") == branch_head:
        return state

    state["finalize"] = {
        "status": "ready",
        "branch": slug,
        "sha": branch_head,
        "ready_at": datetime.now(UTC).isoformat(),
        "worker_session_id": worker_session_id.strip(),
    }
    write_phase_state(worktree_cwd, slug, state)
    return state


def _mark_finalize_handed_off(
    worktree_cwd: str,
    slug: str,
    *,
    handoff_session_id: str,
) -> dict[str, StateValue]:
    state = read_phase_state(worktree_cwd, slug)
    finalize = _get_finalize_state(state)
    if finalize.get("status") != "ready":
        raise ValueError(f"finalize state for {slug} is not ready")

    state["finalize"] = {
        **finalize,  # type: ignore[dict-item]
        "status": "handed_off",
        "handoff_session_id": handoff_session_id,
        "handed_off_at": datetime.now(UTC).isoformat(),
    }
    write_phase_state(worktree_cwd, slug, state)
    return state


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
    """Read breakdown state from todos/{slug}/state.yaml.

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
    """Write breakdown state.

    Args:
        cwd: Project root directory
        slug: Work item slug
        assessed: Whether breakdown assessment has been performed
        todos: List of todo slugs created from split (empty if no breakdown)
    """
    state = read_phase_state(cwd, slug)
    state["breakdown"] = {"assessed": assessed, "todos": todos}  # type: ignore[dict-item]
    write_phase_state(cwd, slug, state)


# ---------------------------------------------------------------------------
# Phase status checks
# ---------------------------------------------------------------------------


def is_build_complete(cwd: str, slug: str) -> bool:
    """Check if build phase is complete."""
    state = read_phase_state(cwd, slug)
    build = state.get(PhaseName.BUILD.value)
    return isinstance(build, str) and build == PhaseStatus.COMPLETE.value


def is_review_approved(cwd: str, slug: str) -> bool:
    """Check if review phase is approved."""
    state = read_phase_state(cwd, slug)
    review = state.get(PhaseName.REVIEW.value)
    return isinstance(review, str) and review == PhaseStatus.APPROVED.value


def is_review_changes_requested(cwd: str, slug: str) -> bool:
    """Check if review requested changes."""
    state = read_phase_state(cwd, slug)
    review = state.get(PhaseName.REVIEW.value)
    return isinstance(review, str) and review == PhaseStatus.CHANGES_REQUESTED.value


def has_pending_deferrals(cwd: str, slug: str) -> bool:
    """Check if there are pending deferrals.

    Returns true if deferrals.md exists AND state.yaml.deferrals_processed is NOT true.
    """
    deferrals_path = Path(cwd) / "todos" / slug / "deferrals.md"
    if not deferrals_path.exists():
        return False

    state = read_phase_state(cwd, slug)
    return state.get("deferrals_processed") is not True


def is_bug_todo(cwd: str, slug: str) -> bool:
    """Check if a todo is a bug (kind='bug' in state.yaml)."""
    state = read_phase_state(cwd, slug)
    return state.get("kind") == "bug"


def check_review_status(cwd: str, slug: str) -> str:
    """Check review status for a work item.

    Returns:
        - "missing" if review-findings.md doesn't exist
        - "approved" if contains "[x] APPROVE"
        - "changes_requested" otherwise
    """
    review_path = Path(cwd) / "todos" / slug / "review-findings.md"
    if not review_path.exists():
        return "missing"

    content = read_text_sync(review_path)
    if REVIEW_APPROVE_MARKER in content:
        return PhaseStatus.APPROVED.value
    return PhaseStatus.CHANGES_REQUESTED.value


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
- [ ] Demo validated (`telec todo demo validate {slug}` exits 0, or exception noted)
- [ ] Working tree clean
- [ ] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
- [ ] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
- [ ] Findings written in `review-findings.md`
- [ ] Verdict recorded (APPROVE or REQUEST CHANGES)
- [ ] Critical issues resolved or explicitly blocked
"""


def mark_ready(cwd: str, slug: str) -> tuple[bool, str]:
    """Fast-track a todo to work-ready state, bypassing the full prepare lifecycle.

    Sets all state.yaml fields required by the work state machine entry checks:
    - phase: pending, build: pending
    - dor.score >= 8, dor.status: pass
    - prepare_phase: prepared, grounding.valid: true
    - requirements_review.verdict: approve, plan_review.verdict: approve

    Requires requirements.md and implementation-plan.md to already exist with real
    content. Generates quality-checklist.md if missing (always the same template).
    Does NOT attempt to derive artifacts from input.md — that's a separate concern.

    Returns:
        (success, message) tuple.
    """
    todo_dir = Path(cwd) / "todos" / slug
    if not todo_dir.exists():
        return False, f"Todo directory not found: todos/{slug}/"

    # --- Validate required artifacts ---
    input_path = todo_dir / "input.md"
    requirements_path = todo_dir / "requirements.md"
    plan_path = todo_dir / "implementation-plan.md"
    checklist_path = todo_dir / "quality-checklist.md"

    if not requirements_path.exists() or not _has_content(requirements_path):
        return False, f"Missing requirements.md with content in todos/{slug}/"

    if not plan_path.exists() or not _has_content(plan_path):
        return False, f"Missing implementation-plan.md with content in todos/{slug}/"

    # Quality checklist can be generated — it's always the same template
    if not checklist_path.exists() or not _has_content(checklist_path):
        checklist_path.write_text(
            _QUALITY_CHECKLIST_TEMPLATE.format(slug=slug),
            encoding="utf-8",
        )

    # --- State update ---
    now_iso = datetime.now(UTC).isoformat()
    state = read_phase_state(cwd, slug)

    state["phase"] = ItemPhase.PENDING.value
    state["build"] = PhaseStatus.PENDING.value
    state["review"] = PhaseStatus.PENDING.value
    state["prepare_phase"] = PreparePhase.PREPARED.value

    # DOR
    state["dor"] = {
        "last_assessed_at": now_iso,
        "score": 8,
        "status": "pass",
        "schema_version": 1,
        "blockers": [],
        "actions_taken": {
            "requirements_updated": False,
            "implementation_plan_updated": False,
        },
    }

    # Review verdicts
    state["requirements_review"] = {
        "verdict": "approve",
        "reviewed_at": now_iso,
        "findings_count": 0,
    }
    state["plan_review"] = {
        "verdict": "approve",
        "reviewed_at": now_iso,
        "findings_count": 0,
    }

    # Grounding
    rc, current_sha, _ = _run_git_prepare(["rev-parse", "HEAD"], cwd=cwd)
    grounding: dict[str, StateValue] = {
        **DEFAULT_STATE["grounding"],  # type: ignore[dict-item]
        "valid": True,
        "last_grounded_at": now_iso,
        "invalidation_reason": "",
        "changed_paths": [],
    }
    if rc == 0 and current_sha.strip():
        grounding["base_sha"] = current_sha.strip()
    if input_path.exists():
        grounding["input_digest"] = hashlib.sha256(input_path.read_bytes()).hexdigest()
    state["grounding"] = grounding

    write_phase_state(cwd, slug, state)

    return True, f"✓ {slug} fast-tracked to work-ready (DOR 8, prepared, grounded)"


def _has_content(path: Path) -> bool:
    """Check if a file has non-trivial content (beyond whitespace and headings)."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8").strip()
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return len(lines) > 0


__all__ = [
    "_file_sha256",
    "_is_review_round_limit_reached",
    "_mark_finalize_handed_off",
    "_review_scope_note",
    "check_review_status",
    "get_state_path",
    "has_pending_deferrals",
    "is_bug_todo",
    "is_build_complete",
    "is_review_approved",
    "is_review_changes_requested",
    "mark_finalize_ready",
    "mark_phase",
    "mark_prepare_phase",
    "mark_prepare_verdict",
    "mark_ready",
    "read_breakdown_state",
    "read_phase_state",
    "read_text_sync",
    "write_breakdown_state",
    "write_phase_state",
    "write_text_sync",
]
