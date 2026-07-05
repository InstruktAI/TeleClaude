"""Integration candidate discovery — FIFO scan, single-slug verify, stale sweep.

No imports from state_machine.py or step_functions.py (circular-import guard).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.integration.git_ops import _run_git
from teleclaude.core.integration.readiness_projection import CandidateKey
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.types.state_value import StateValue

logger = get_logger(__name__)


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


def _is_held_or_kicked_back(state: dict[str, StateValue]) -> bool:
    """True when persisted state shows the candidate held or kicked back.

    A human ``--kickback``/``--hold`` stamp is meant to retract a candidate from
    the integration pool, but leaves ``finalize.status`` at ``"ready"`` — these
    are the real signals that must additionally gate eligibility (exact
    ``TodoState`` field paths: ``hold: bool``,
    ``plan_review.cleared_by_substantive_drift: bool``).
    """
    if bool(state.get("hold")):
        return True
    plan_review = state.get("plan_review")
    return isinstance(plan_review, dict) and bool(plan_review.get("cleared_by_substantive_drift"))


def _scan_finalize_ready_candidates(cwd: str, *, exclude_slug: str | None = None) -> list[ScannedCandidate]:
    """Scan worktree todo states for finalize-ready candidates.

    Iterates ``trees/`` subdirectories (skipping ``_integration``), reads each
    worktree's state from todos.db and returns candidates whose
    ``finalize.status`` is ``"ready"``.

    Each candidate is validated: branch must exist on origin and SHA must not
    already be an ancestor of main.

    Returns candidates sorted by ``(ready_at, slug)`` for stable FIFO ordering.
    """
    todos_db = get_todos_db_sync(cwd)

    trees_dir = Path(cwd) / WORKTREE_DIR
    if not trees_dir.is_dir():
        return []

    candidates: list[ScannedCandidate] = []

    for entry in sorted(trees_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        slug = entry.name
        if slug == exclude_slug:
            continue

        try:
            state = todos_db.read_state_sync(slug)
        except Exception as exc:
            raise CandidateStateReadError(slug, exc) from exc
        if state is None:
            continue

        finalize = state.get("finalize", {})
        if not isinstance(finalize, dict):
            continue

        status = finalize.get("status")

        if status != "ready":
            continue

        if _is_held_or_kicked_back(state):
            continue

        branch_raw = finalize.get("branch", slug)
        sha_raw = finalize.get("sha", "")
        ready_at_raw = finalize.get("ready_at", "")
        if not isinstance(branch_raw, str) or not isinstance(sha_raw, str) or not isinstance(ready_at_raw, str):
            continue
        branch, sha, ready_at = branch_raw, sha_raw, ready_at_raw
        if not sha or not ready_at:
            continue

        # Verify branch exists on origin
        rc, _, _ = _run_git(["ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"], cwd=cwd)
        if rc != 0:
            continue

        # Verify SHA not already ancestor of main
        rc, _, _ = _run_git(["merge-base", "--is-ancestor", sha, "HEAD"], cwd=cwd)
        if rc == 0:
            continue

        candidates.append(
            ScannedCandidate(
                key=CandidateKey(slug=slug, branch=branch, sha=sha),
                ready_at=ready_at,
            )
        )

    candidates.sort(key=lambda c: (c.ready_at, c.key.slug))
    return candidates


def _verify_slug_ready(cwd: str, slug: str) -> ScannedCandidate | None:
    """Check if a specific slug's persisted todos.db state shows finalize-ready.

    Same validations as the scanner but targeted to a single slug.
    """
    worktree_dir = Path(cwd) / WORKTREE_DIR / slug
    if not worktree_dir.is_dir():
        return None

    todos_db = get_todos_db_sync(cwd)
    try:
        state = todos_db.read_state_sync(slug)
    except Exception as exc:
        raise CandidateStateReadError(slug, exc) from exc
    if state is None:
        return None

    finalize = state.get("finalize", {})
    if not isinstance(finalize, dict):
        return None

    status = finalize.get("status")

    if status != "ready":
        return None

    if _is_held_or_kicked_back(state):
        return None

    branch_raw = finalize.get("branch", slug)
    sha_raw = finalize.get("sha", "")
    ready_at_raw = finalize.get("ready_at", "")
    if not isinstance(branch_raw, str) or not isinstance(sha_raw, str) or not isinstance(ready_at_raw, str):
        return None
    branch, sha, ready_at = branch_raw, sha_raw, ready_at_raw
    if not sha or not ready_at:
        return None

    # Verify branch exists on origin
    rc, _, _ = _run_git(["ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"], cwd=cwd)
    if rc != 0:
        return None

    # Verify SHA not already ancestor of main
    rc, _, _ = _run_git(["merge-base", "--is-ancestor", sha, "HEAD"], cwd=cwd)
    if rc == 0:
        return None

    return ScannedCandidate(
        key=CandidateKey(slug=slug, branch=branch, sha=sha),
        ready_at=ready_at,
    )


def _sweep_stale_artifacts(cwd: str) -> list[str]:
    """Remove worktrees and branches for slugs already delivered in the DB.

    Returns list of swept slug names. Each step is idempotent — safe to
    call on every IDLE entry without risk of double-cleanup.
    """
    todos_db = get_todos_db_sync(cwd)
    conn = todos_db._sync_conn()
    try:
        rows = conn.execute(
            "SELECT slug FROM todo WHERE status = 'delivered'",  # guard: raw-sql
        ).fetchall()
        delivered = {row[0] for row in rows}
    finally:
        conn.close()
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
]
