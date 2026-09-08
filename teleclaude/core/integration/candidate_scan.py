"""Integration candidate discovery — FIFO scan, single-slug verify, stale sweep.

No imports from state_machine.py or step_functions.py (circular-import guard).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.integration.git_ops import _run_git
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.types.state_value import StateValue

logger = get_logger(__name__)

_DOWNSTREAM_DEPENDENCIES_SQL = "SELECT slug FROM todo_deps WHERE depends_on = ?"
_ACTIVE_TODO_SLUGS_SQL = "SELECT slug FROM todo WHERE status = 'active'"
_GIT_LOG_SPAN_ARGS = ("log", "--no-merges", "-z", "--format=%H\x1f%s")
_GIT_DIFF_TREE_NAME_ONLY_ARGS = ("diff-tree", "--no-commit-id", "--name-only", "-r", "-z")
_GIT_RANGE_SEPARATOR = ".."
_SPAN_RECORD_SEPARATOR = "\0"
_SPAN_FIELD_SEPARATOR = "\x1f"
_CONVENTIONAL_COMMIT_HEADER_RE = re.compile(r"^\w+(?:\(([^)]+)\))?!?:\s")


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


class CandidateCleanlinessInspectionError(RuntimeError):
    """Raised when a candidate span's ownership cannot be mechanically inspected.

    Distinct from a foreign or ambiguous verdict — this signals that the
    inspection itself could not be performed (missing or invalid plan
    metadata, an unreadable Git range) so integration stops visibly rather
    than defaulting to a clean, foreign, or ambiguous outcome.
    """


class CandidateCleanlinessOutcome(StrEnum):
    """Closed outcome vocabulary for a candidate span-ownership inspection."""

    CLEAN = "clean"
    FOREIGN = "foreign"
    AMBIGUOUS = "ambiguous"


class CandidateSpanReasonToken(StrEnum):
    """Closed vocabulary for why a span commit resolved foreign or ambiguous."""

    FOREIGN_SCOPE = "foreign_scope"
    AMBIGUOUS_HEADER = "ambiguous_header"
    AMBIGUOUS_PATH = "ambiguous_path"


class AmbiguityEvidence(NamedTuple):
    """Mechanical evidence for the span commit that decided a foreign or ambiguous outcome."""

    commit_sha: str
    reason_token: str


@dataclass(frozen=True)
class CandidateCleanlinessResult:
    """Mechanical span-ownership verdict for one candidate, ready to park or continue."""

    outcome: CandidateCleanlinessOutcome
    evidence: AmbiguityEvidence | None  # None only when outcome is CLEAN


@dataclass(frozen=True)
class _SpanCommit:
    """One non-merge commit in a candidate's span, with its parsed header and touched paths."""

    sha: str
    scope: str | None
    touched_paths: frozenset[str]


def _parse_conventional_scope(subject: str) -> str | None:
    """Return the parenthesized scope of a conventional-commit header, or None."""
    match = _CONVENTIONAL_COMMIT_HEADER_RE.match(subject)
    if not match:
        return None
    return match.group(1)


def _active_todo_slugs(cwd: str) -> frozenset[str]:
    """Return every slug currently registered with status='active'."""
    conn = get_todos_db_sync(cwd)._sync_conn()
    try:
        rows = conn.execute(_ACTIVE_TODO_SLUGS_SQL).fetchall()  # guard: raw-sql
        return frozenset(row[0] for row in rows if isinstance(row[0], str))
    finally:
        conn.close()


def _referenced_paths_or_raise(cwd: str, slug: str) -> frozenset[str]:
    """Return the candidate's frozen implementation-plan referenced-paths contract.

    Missing or invalid metadata is an explicit inspection failure — never an
    empty-path fallback that would silently make every touched path look
    unattributed.
    """
    try:
        state = get_todos_db_sync(cwd).read_state_sync(slug)
    except Exception as exc:
        raise CandidateStateReadError(slug, exc) from exc
    if state is None:
        raise CandidateCleanlinessInspectionError(f"No persisted state for candidate {slug!r}")
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        raise CandidateCleanlinessInspectionError(f"Candidate {slug!r} state has no artifacts metadata")
    plan = artifacts.get("implementation_plan")
    if not isinstance(plan, dict):
        raise CandidateCleanlinessInspectionError(f"Candidate {slug!r} has no implementation_plan artifact metadata")
    referenced_paths = plan.get("referenced_paths")
    if not isinstance(referenced_paths, list) or not all(isinstance(p, str) for p in referenced_paths):
        raise CandidateCleanlinessInspectionError(
            f"Candidate {slug!r} implementation_plan.referenced_paths is missing or invalid"
        )
    str_paths: list[str] = [path for path in referenced_paths if isinstance(path, str)]
    return frozenset(str_paths)


def _enumerate_span_commits(cwd: str, sha: str) -> list[_SpanCommit]:
    """Return every non-merge commit in ``origin/main..sha``, with its scope and touched paths."""
    log_rc, log_stdout, log_stderr = _run_git([*_GIT_LOG_SPAN_ARGS, f"origin/main{_GIT_RANGE_SEPARATOR}{sha}"], cwd=cwd)
    if log_rc != 0:
        raise CandidateCleanlinessInspectionError(f"git log span read failed for {sha}: {log_stderr.strip()}")

    commits: list[_SpanCommit] = []
    for record in log_stdout.split(_SPAN_RECORD_SEPARATOR):
        if not record:
            continue
        try:
            commit_sha, subject = record.split(_SPAN_FIELD_SEPARATOR, 1)
        except ValueError as exc:
            raise CandidateCleanlinessInspectionError(
                f"Malformed git log record in span for {sha}: {record!r}"
            ) from exc

        paths_rc, paths_stdout, paths_stderr = _run_git([*_GIT_DIFF_TREE_NAME_ONLY_ARGS, commit_sha], cwd=cwd)
        if paths_rc != 0:
            raise CandidateCleanlinessInspectionError(
                f"git diff-tree path read failed for {commit_sha}: {paths_stderr.strip()}"
            )
        touched_paths = frozenset(p for p in paths_stdout.split(_SPAN_RECORD_SEPARATOR) if p)
        commits.append(
            _SpanCommit(sha=commit_sha, scope=_parse_conventional_scope(subject), touched_paths=touched_paths)
        )
    return commits


def _classify_span_commit(
    commit: _SpanCommit,
    *,
    candidate_slug: str,
    active_slugs: frozenset[str],
    referenced_paths: frozenset[str],
) -> tuple[CandidateCleanlinessOutcome, CandidateSpanReasonToken | None]:
    """Classify one span commit against the exact ownership predicates.

    A scope naming another active slug is the only foreign evidence: a commit
    carries its own slug scope, so genuine cross-slug work arrives labelled. A
    scope equal to the candidate's own slug is clean whatever paths it touches,
    because a module the build extracted is the slug's own work. An unattributed
    header is ambiguous, and a touched path outside the frozen referenced-paths
    contract sharpens that ambiguity's reason without ever creating it.
    """
    if commit.scope is not None and commit.scope != candidate_slug and commit.scope in active_slugs:
        return CandidateCleanlinessOutcome.FOREIGN, CandidateSpanReasonToken.FOREIGN_SCOPE
    if commit.scope == candidate_slug:
        return CandidateCleanlinessOutcome.CLEAN, None
    if any(path not in referenced_paths for path in commit.touched_paths):
        return CandidateCleanlinessOutcome.AMBIGUOUS, CandidateSpanReasonToken.AMBIGUOUS_PATH
    return CandidateCleanlinessOutcome.AMBIGUOUS, CandidateSpanReasonToken.AMBIGUOUS_HEADER


def _inspect_candidate_cleanliness(cwd: str, key: CandidateKey) -> CandidateCleanlinessResult:
    """Mechanically inspect a candidate's span for exact foreign or ambiguous ownership.

    Foreign outranks ambiguous when both appear in one span: the first foreign
    commit encountered decides the result. Absent any foreign commit, the
    first ambiguous commit decides. A span with neither is clean.
    """
    referenced_paths = _referenced_paths_or_raise(cwd, key.slug)
    active_slugs = _active_todo_slugs(cwd)
    commits = _enumerate_span_commits(cwd, key.sha)

    ambiguous_evidence: AmbiguityEvidence | None = None
    for commit in commits:
        outcome, reason_token = _classify_span_commit(
            commit, candidate_slug=key.slug, active_slugs=active_slugs, referenced_paths=referenced_paths
        )
        if outcome is CandidateCleanlinessOutcome.FOREIGN:
            assert reason_token is not None
            return CandidateCleanlinessResult(
                outcome=CandidateCleanlinessOutcome.FOREIGN,
                evidence=AmbiguityEvidence(commit_sha=commit.sha, reason_token=reason_token.value),
            )
        if outcome is CandidateCleanlinessOutcome.AMBIGUOUS and ambiguous_evidence is None:
            assert reason_token is not None
            ambiguous_evidence = AmbiguityEvidence(commit_sha=commit.sha, reason_token=reason_token.value)

    if ambiguous_evidence is not None:
        return CandidateCleanlinessResult(outcome=CandidateCleanlinessOutcome.AMBIGUOUS, evidence=ambiguous_evidence)
    return CandidateCleanlinessResult(outcome=CandidateCleanlinessOutcome.CLEAN, evidence=None)


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


def _parked_candidate_closure(cwd: str, parked_slugs: set[str]) -> set[str]:
    """Return parked slugs and every slug that transitively depends on them."""
    excluded = set(parked_slugs)
    frontier = list(parked_slugs)
    conn = get_todos_db_sync(cwd)._sync_conn()
    try:
        while frontier:
            depends_on = frontier.pop()
            rows = conn.execute(_DOWNSTREAM_DEPENDENCIES_SQL, (depends_on,)).fetchall()  # guard: raw-sql
            for row in rows:
                dependent = row[0]
                if not isinstance(dependent, str) or dependent in excluded:
                    continue
                excluded.add(dependent)
                frontier.append(dependent)
    finally:
        conn.close()
    return excluded


def _scan_finalize_ready_candidates(
    cwd: str,
    *,
    parked_slugs: set[str],
    exclude_slug: str | None = None,
) -> list[ScannedCandidate]:
    """Scan worktree todo states for finalize-ready candidates.

    Iterates ``trees/`` subdirectories (skipping ``_integration``), reads each
    worktree's state from todos.db and returns candidates whose
    ``finalize.status`` is ``"ready"``.

    Each candidate is validated: branch must exist on origin and SHA must not
    already be an ancestor of main.

    Returns candidates sorted by ``(ready_at, slug)`` for stable FIFO ordering.
    """
    todos_db = get_todos_db_sync(cwd)
    excluded = _parked_candidate_closure(cwd, parked_slugs)

    trees_dir = Path(cwd) / WORKTREE_DIR
    if not trees_dir.is_dir():
        return []

    candidates: list[ScannedCandidate] = []

    for entry in sorted(trees_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        slug = entry.name
        if slug == exclude_slug or slug in excluded:
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


def _verify_slug_ready(cwd: str, slug: str, *, parked_slugs: set[str]) -> ScannedCandidate | None:
    """Check if a specific slug's persisted todos.db state shows finalize-ready.

    Same validations as the scanner but targeted to a single slug.
    """
    if slug in _parked_candidate_closure(cwd, parked_slugs):
        return None

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


def _stamp_integration_started(cwd: str, slug: str) -> None:
    """Stamp integration_phase='started' on an active slug's todo state.

    Best-effort: failures are logged but do not block the integration flow.
    Only called at candidate dequeue when the slug is still active.
    The 'delivered' stamp is handled by deliver_sync.
    """
    try:
        todos_db = get_todos_db_sync(cwd)
        state = todos_db.read_state_sync(slug)
        if state is None:
            return
        state["integration_phase"] = "started"
        todos_db.write_state_sync(slug, state)
    except Exception as exc:
        logger.warning("_stamp_integration_started failed for %s: %s", slug, exc)


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
    "AmbiguityEvidence",
    "CandidateCleanlinessInspectionError",
    "CandidateCleanlinessOutcome",
    "CandidateCleanlinessResult",
    "CandidateStateReadError",
    "ScannedCandidate",
    "_inspect_candidate_cleanliness",
    "_scan_finalize_ready_candidates",
    "_stamp_integration_started",
    "_sweep_stale_artifacts",
    "_verify_slug_ready",
]
