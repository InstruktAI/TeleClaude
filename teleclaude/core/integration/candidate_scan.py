"""Integration candidate discovery — FIFO scan, single-slug verify, stale sweep.

No imports from state_machine.py or step_functions.py (circular-import guard).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR, TodoStatus
from teleclaude.core.integration.git_ops import _run_git
from teleclaude.core.next_machine.create import creative_incomplete_sync
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.workflow_machine.phase_reading import read_phase
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store_sync
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Phase

logger = get_logger(__name__)

_WORKFLOW_STATUSES = (TodoStatus.ACTIVE, TodoStatus.ICEBOX)
_RESERVED_TREE_PREFIX = "_"


@dataclass(frozen=True, order=True)
class CandidateKey:
    """Canonical integration candidate identity."""

    slug: str
    branch: str
    sha: str


class CandidateStateReadError(RuntimeError):
    """Raised when a candidate's persisted state cannot be read.

    Distinct from the legitimate "no state" case (``read_state_sync`` returning
    ``None``, e.g. a removed or not-yet-active todo) — this signals a genuine
    read failure (corrupt state, DB error) that must stop integration visibly
    rather than silently making the affected slug disappear from the queue.
    """

    def __init__(self, slug: str, cause: Exception) -> None:
        super().__init__(f"Failed to read persisted state for {slug!r}: {cause}")
        self.slug = slug


@dataclass(frozen=True)
class ScannedCandidate:
    """A finalize-ready candidate discovered by scanning worktree state files."""

    key: CandidateKey
    ready_at: str
    admitted: bool = False


def candidate_is_held(state: dict[str, StateValue], typed: TodoState, head: str) -> bool:
    """True when the item is explicitly held, or kicked back by evidence a stamp at the current head supersedes.

    An explicit ``hold`` retracts a candidate whatever else is recorded. Substantive-drift evidence belongs to the
    retired review flow: a stamp of the lifecycle machine at the current head is a later, complete judgment of the
    commit, so only a stale evidence of that kind is read for an item that carries no such stamp.
    """
    if bool(state.get("hold")):
        return True
    stamp = typed.workflow.stamp
    if stamp is not None and head and stamp.sha == head:
        return False
    plan_review = state.get("plan_review")
    return isinstance(plan_review, dict) and bool(plan_review.get("cleared_by_substantive_drift"))


def _parked_candidate_closure(cwd: str, parked_slugs: set[str]) -> set[str]:
    """Return parked slugs and every slug that transitively depends on them."""
    excluded = set(parked_slugs)
    frontier = list(parked_slugs)
    store = get_workflow_store_sync(cwd)
    while frontier:
        depends_on = frontier.pop()
        for dependent in store.downstream_dependency_slugs_sync(depends_on):
            if dependent in excluded:
                continue
            excluded.add(dependent)
            frontier.append(dependent)
    return excluded


def _remote_head(cwd: str, branch: str) -> str:
    rc, stdout, _ = _run_git(["ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"], cwd=cwd)
    parts = stdout.split()
    return parts[0] if rc == 0 and parts else ""


def _admitted_candidate(slug: str, typed: TodoState) -> ScannedCandidate | None:
    """The commit the integrator admitted for the item, exactly as admitted.

    An admission lives until the integrator's own terminal lifecycle retires it: delivery, or a park. A later stamp, a
    kickback, a moved head or a main that already contains the commit does not discard it; the integration step
    finishes the bookkeeping for a commit that is already in main.
    """
    admitted = typed.workflow.admitted
    if admitted is None:
        return None
    return ScannedCandidate(
        key=CandidateKey(slug=slug, branch=admitted.branch, sha=admitted.sha), ready_at=admitted.at, admitted=True
    )


def _candidate_from_state(
    cwd: str, slug: str, state: dict[str, StateValue], todos_db: WorkflowStore
) -> ScannedCandidate | None:
    """The candidate an item's canonical phase establishes, or None.

    Readiness is the phase reading (``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``): the item
    reads ``ready`` at a commit that is the current head of its branch on origin, with the creative lane complete. A
    stamp of the lifecycle machine, a carried finalize handoff and a carried review approval at the head all read that
    way; an item that reads any other phase is never a candidate, whatever events exist for it. The commit must not
    already be in main. A commit the integrator admitted stays the candidate until a later stamp supersedes it.
    """
    typed = TodoState.model_validate(state)
    if bool(state.get("hold")):
        return None
    admitted = _admitted_candidate(slug, typed)
    if admitted is not None:
        return admitted
    finalize = state.get("finalize")
    branch_raw = finalize.get("branch", slug) if isinstance(finalize, dict) else slug
    branch = branch_raw if isinstance(branch_raw, str) and branch_raw else slug
    head = _remote_head(cwd, branch)
    if not head or candidate_is_held(state, typed, head):
        return None
    incomplete = creative_incomplete_sync(todos_db, cwd, slug, state)
    reading = read_phase(typed, integration_head=head, creative_incomplete=incomplete)
    if reading.phase is not Phase.READY or not reading.ready_at or reading.ready_sha != head:
        return None
    rc, _, _ = _run_git(["merge-base", "--is-ancestor", head, "HEAD"], cwd=cwd)
    if rc == 0:
        return None
    return ScannedCandidate(key=CandidateKey(slug=slug, branch=branch, sha=head), ready_at=reading.ready_at)


def _scan_finalize_ready_candidates(
    cwd: str,
    *,
    parked_slugs: set[str],
    exclude_slug: str | None = None,
) -> list[ScannedCandidate]:
    """Scan the store's items for the ones whose canonical phase reads ready at the head of their branch.

    The store supplies candidate identities and state. Existing worktree and Git checks remain integrator-owned
    validation of those store candidates. Returns candidates sorted by ``(ready_at, slug)`` for stable FIFO ordering.
    """
    todos_db = get_workflow_store_sync(cwd)
    excluded = _parked_candidate_closure(cwd, parked_slugs)

    trees_dir = Path(cwd) / WORKTREE_DIR
    if not trees_dir.is_dir():
        return []
    snapshot = todos_db.read_todo_projection_snapshot_sync(_WORKFLOW_STATUSES)
    candidates: list[ScannedCandidate] = []

    for item in sorted(snapshot.items, key=lambda candidate: str(candidate.item_id)):
        slug = str(item.item_id)
        if slug.startswith(_RESERVED_TREE_PREFIX) or slug == exclude_slug or slug in excluded:
            continue
        if not (trees_dir / slug).is_dir():
            continue
        try:
            state = todos_db.read_state_sync(slug)
        except Exception as exc:
            raise CandidateStateReadError(slug, exc) from exc
        if state is None:
            continue
        candidate = _candidate_from_state(cwd, slug, state, todos_db)
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(key=lambda c: (not c.admitted, c.ready_at, c.key.slug))
    return candidates


def _verify_slug_ready(cwd: str, slug: str, *, parked_slugs: set[str]) -> ScannedCandidate | None:
    """Check whether a specific slug's canonical phase still reads ready at the head of its branch.

    Same validations as the scanner but targeted to a single slug.
    """
    if slug in _parked_candidate_closure(cwd, parked_slugs):
        return None
    if not (Path(cwd) / WORKTREE_DIR / slug).is_dir():
        return None
    todos_db = get_workflow_store_sync(cwd)
    try:
        state = todos_db.read_state_sync(slug)
    except Exception as exc:
        raise CandidateStateReadError(slug, exc) from exc
    if state is None:
        return None
    return _candidate_from_state(cwd, slug, state, todos_db)


def _sweep_stale_artifacts(cwd: str) -> list[str]:
    """Remove worktrees and branches for slugs already delivered in the DB.

    Returns list of swept slug names. Each step is idempotent — safe to
    call on every IDLE entry without risk of double-cleanup.
    """
    delivered = get_workflow_store_sync(cwd).delivered_slugs_sync()
    if not delivered:
        return []

    trees_dir = Path(cwd) / WORKTREE_DIR
    if not trees_dir.is_dir():
        return []

    swept: list[str] = []
    for entry in sorted(trees_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if entry.name in delivered:
            logger.info("Sweeping stale artifact for delivered slug: %s", entry.name)
            try:
                cleanup_delivered_slug(cwd, entry.name)
            except Exception:
                logger.warning("Stale artifact sweep failed for %s", entry.name, exc_info=True)
            swept.append(entry.name)

    if swept:
        logger.info("Stale artifact sweep cleaned %d slug(s): %s", len(swept), swept)
    return swept


__all__ = [
    "CandidateStateReadError",
    "ScannedCandidate",
    "_scan_finalize_ready_candidates",
    "_sweep_stale_artifacts",
    "_verify_slug_ready",
    "candidate_is_held",
]
