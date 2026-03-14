"""Integration step functions — git helpers, phase helpers, step implementations.

No imports from state_machine.py (circular-import guard).
Instruction formatters live in formatters.py.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.integration.checkpoint import (
    IntegrationCheckpoint,
    IntegrationPhase,
    _now_iso,
    _write_checkpoint,
)
from teleclaude.core.integration.formatters import (
    _format_commit_decision,
    _format_conflict_decision,
    _format_error,
    _format_lease_busy,
    _format_pull_blocked,
    _format_push_rejected,
    _format_queue_empty,
)
from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.readiness_projection import CandidateKey

logger = get_logger(__name__)

# Thread-local storage for event loop reference (used in fire-and-forget async emission)
_tls = threading.local()

_INTEGRATION_LEASE_KEY = "integration/main"
_INTEGRATION_LEASE_TTL_SECONDS = 120
_NEXT_INTEGRATE_PHASE_LOG = "NEXT_INTEGRATE_PHASE"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run_git(
    args: list[str], *, cwd: str, timeout: float = 30
) -> tuple[int, str, str]:
    """Run a git command; return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.warning("git %s timed out after %.0fs", " ".join(args[:2]), timeout)
        return 1, "", f"timeout after {timeout}s"


def _get_head_sha(cwd: str) -> str | None:
    rc, stdout, _ = _run_git(["rev-parse", "HEAD"], cwd=cwd)
    return stdout.strip() if rc == 0 and stdout.strip() else None


def _get_remote_main_sha(cwd: str) -> str | None:
    rc, stdout, _ = _run_git(["ls-remote", "origin", "refs/heads/main"], cwd=cwd)
    if rc != 0 or not stdout.strip():
        return None
    parts = stdout.strip().split()
    return parts[0] if parts else None


def _git_dir(cwd: str) -> Path | None:
    """Return the actual .git directory, handling worktree indirection."""
    rc, stdout, _ = _run_git(["rev-parse", "--git-dir"], cwd=cwd)
    if rc != 0:
        return None
    git_dir = Path(stdout.strip())
    if not git_dir.is_absolute():
        git_dir = Path(cwd) / git_dir
    return git_dir


def _merge_head_exists(cwd: str) -> bool:
    gd = _git_dir(cwd)
    return gd is not None and (gd / "MERGE_HEAD").exists()


def _get_conflicted_files(cwd: str) -> list[str]:
    rc, stdout, _ = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=cwd)
    if rc != 0:
        return []
    return [f.strip() for f in stdout.splitlines() if f.strip()]


def _get_diff_stats(cwd: str) -> str:
    rc, stdout, _ = _run_git(["diff", "--cached", "--stat"], cwd=cwd)
    return stdout.strip() if rc == 0 else ""


def _get_branch_log(cwd: str, branch: str, *, base_ref: str = "main") -> str:
    rc, stdout, _ = _run_git(["log", f"{base_ref}..{branch}", "--oneline", "--no-decorate"], cwd=cwd)
    return stdout.strip() if rc == 0 else ""


def _read_file_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------


def _get_candidate_key(checkpoint: IntegrationCheckpoint) -> CandidateKey | None:
    if checkpoint.candidate_slug and checkpoint.candidate_branch and checkpoint.candidate_sha:
        return CandidateKey(
            slug=checkpoint.candidate_slug,
            branch=checkpoint.candidate_branch,
            sha=checkpoint.candidate_sha,
        )
    return None


def _integration_worktree_path(cwd: str) -> Path:
    """Compute the persistent integration worktree path."""
    return Path(cwd) / WORKTREE_DIR / "_integration"


def _ensure_integration_worktree(cwd: str) -> tuple[Path, str]:
    """Ensure persistent integration worktree exists and is synced to origin/main.

    Returns (worktree_path, error_message). Error is empty on success.
    """
    integration_wt = _integration_worktree_path(cwd)

    if not integration_wt.exists():
        rc, _, stderr = _run_git(["fetch", "origin", "main"], cwd=cwd)
        if rc != 0:
            return integration_wt, f"git fetch origin main failed:\n{stderr.strip()}"
        rc, _, stderr = _run_git(
            ["worktree", "add", str(integration_wt), "origin/main", "--detach"], cwd=cwd
        )
        if rc != 0:
            return integration_wt, f"git worktree add (integration) failed:\n{stderr.strip()}"

    # Skip reset if there's an active merge or squash state — preserves
    # conflict resolutions and in-progress squash merges on re-entry.
    wt_str = str(integration_wt)
    if _merge_head_exists(wt_str):
        return integration_wt, ""
    gd = _git_dir(wt_str)
    if gd is None:
        # Cannot determine git directory — skip reset to avoid destroying
        # potential in-progress squash merge state.
        return integration_wt, ""
    if (gd / "SQUASH_MSG").exists():
        return integration_wt, ""

    # Sync to latest origin/main
    rc, _, stderr = _run_git(["fetch", "origin"], cwd=wt_str)
    if rc != 0:
        return integration_wt, f"git fetch origin failed in integration worktree:\n{stderr.strip()}"
    rc, _, stderr = _run_git(["reset", "--hard", "origin/main"], cwd=wt_str)
    if rc != 0:
        return integration_wt, f"git reset to origin/main failed in integration worktree:\n{stderr.strip()}"

    return integration_wt, ""


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


# guard: loose-dict-func - lifecycle event payload shape varies per event type
async def _bridge_emit(
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Dispatch lifecycle event to the appropriate integration_bridge helper."""
    # Lazy import to avoid circular dependency at module load time
    from teleclaude.core import integration_bridge as bridge

    try:
        if event_type == "integration.started":
            await bridge.emit_integration_started(
                slug=payload.get("slug", ""),
                session_id=payload.get("session_id", ""),
                queue_depth=int(payload.get("queue_depth", 0)),
            )
        elif event_type == "integration.candidate.delivered":
            await bridge.emit_integration_candidate_delivered(
                slug=payload.get("slug", ""),
                branch=payload.get("branch", ""),
                merge_commit_sha=payload.get("merge_commit_sha", ""),
            )
        elif event_type == "integration.candidate.blocked":
            await bridge.emit_integration_candidate_blocked(
                slug=payload.get("slug", ""),
                branch=payload.get("branch", ""),
                sha=payload.get("sha", ""),
                reason=payload.get("reason", ""),
            )
        # Other event types are observability-only; logged below, not wired to bridge
    except Exception:
        pass  # Never block integration on event emission failure


# guard: loose-dict-func - lifecycle event payload shape varies per event type
def _emit_lifecycle_event(
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Fire-and-forget lifecycle event emission via bridge (threadsafe)."""
    logger.info("INTEGRATION_LIFECYCLE_EVENT type=%s payload=%s", event_type, payload)
    loop: asyncio.AbstractEventLoop | None = getattr(_tls, "loop", None)
    if loop is None or not loop.is_running():
        return
    try:
        asyncio.run_coroutine_threadsafe(_bridge_emit(event_type, payload), loop)
    except Exception:
        pass  # Never block integration on event emission failure


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScannedCandidate:
    """A finalize-ready candidate discovered by scanning worktree state files."""

    key: CandidateKey
    ready_at: str


def _scan_finalize_ready_candidates(
    cwd: str, *, exclude_slug: str | None = None
) -> list[ScannedCandidate]:
    """Scan worktree state.yaml files for finalize-ready candidates.

    Iterates ``trees/`` subdirectories (skipping ``_integration``), reads each
    worktree's ``state.yaml`` via ``read_phase_state``, and returns candidates
    whose ``finalize.status`` is ``"ready"`` — or ``"handed_off"`` with a stale
    ``handed_off_at`` older than the lease TTL (crash recovery).

    Each candidate is validated: branch must exist on origin and SHA must not
    already be an ancestor of main.

    Returns candidates sorted by ``(ready_at, slug)`` for stable FIFO ordering.
    """
    from teleclaude.core.next_machine.state_io import read_phase_state

    trees_dir = Path(cwd) / WORKTREE_DIR
    if not trees_dir.is_dir():
        return []

    candidates: list[ScannedCandidate] = []
    now = datetime.now(tz=UTC)

    for entry in sorted(trees_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        slug = entry.name
        if slug == exclude_slug:
            continue

        try:
            state = read_phase_state(str(entry), slug)
        except Exception:
            continue

        finalize = state.get("finalize", {})
        if not isinstance(finalize, dict):
            continue

        status = finalize.get("status")

        if status == "handed_off":
            handed_off_at = finalize.get("handed_off_at", "")
            if not handed_off_at:
                continue
            try:
                handoff_time = datetime.fromisoformat(handed_off_at)
                if (now - handoff_time).total_seconds() < _INTEGRATION_LEASE_TTL_SECONDS:
                    continue  # Fresh handoff — not yet recoverable
            except (ValueError, TypeError):
                continue
        elif status != "ready":
            continue

        branch = finalize.get("branch", slug)
        sha = finalize.get("sha", "")
        ready_at = finalize.get("ready_at", "")
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

        candidates.append(ScannedCandidate(
            key=CandidateKey(slug=slug, branch=branch, sha=sha),
            ready_at=ready_at,
        ))

    candidates.sort(key=lambda c: (c.ready_at, c.key.slug))
    return candidates


def _verify_slug_ready(cwd: str, slug: str) -> ScannedCandidate | None:
    """Check if a specific slug's worktree state.yaml shows finalize-ready.

    Same validations as the scanner but targeted to a single slug.
    """
    from teleclaude.core.next_machine.state_io import read_phase_state

    worktree_dir = Path(cwd) / WORKTREE_DIR / slug
    if not worktree_dir.is_dir():
        return None

    try:
        state = read_phase_state(str(worktree_dir), slug)
    except Exception:
        return None

    finalize = state.get("finalize", {})
    if not isinstance(finalize, dict):
        return None

    status = finalize.get("status")

    if status == "handed_off":
        handed_off_at = finalize.get("handed_off_at", "")
        if not handed_off_at:
            return None
        try:
            handoff_time = datetime.fromisoformat(handed_off_at)
            if (datetime.now(tz=UTC) - handoff_time).total_seconds() < _INTEGRATION_LEASE_TTL_SECONDS:
                return None
        except (ValueError, TypeError):
            return None
    elif status != "ready":
        return None

    branch = finalize.get("branch", slug)
    sha = finalize.get("sha", "")
    ready_at = finalize.get("ready_at", "")
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


def _step_idle(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    lease_store: IntegrationLeaseStore,
    session_id: str,
    slug: str | None,
    cwd: str,
    started: float,
) -> tuple[bool, str]:
    """IDLE: scan worktree state files for finalize-ready candidates, acquire lease, proceed to merge."""
    exclude = checkpoint.candidate_slug

    if slug is not None:
        candidate = _verify_slug_ready(cwd, slug)
        candidates = [candidate] if candidate else []
    else:
        candidates = _scan_finalize_ready_candidates(cwd, exclude_slug=exclude)

    if not candidates:
        elapsed_ms = int((perf_counter() - started) * 1000)
        _try_release_lease(lease_store, session_id, checkpoint.lease_token)
        return False, _format_queue_empty(checkpoint.items_processed, checkpoint.items_blocked, elapsed_ms)

    # Acquire lease
    acquire_result = lease_store.acquire(
        key=_INTEGRATION_LEASE_KEY,
        owner_session_id=session_id,
        ttl_seconds=_INTEGRATION_LEASE_TTL_SECONDS,
    )
    if acquire_result.status != "acquired" or not acquire_result.lease:
        holder_id = acquire_result.holder.owner_session_id if acquire_result.holder else "unknown"
        return False, _format_lease_busy(holder_id)

    lease_token = acquire_result.lease.lease_token
    key = candidates[0].key
    now = _now_iso()
    checkpoint.phase = IntegrationPhase.CANDIDATE_DEQUEUED.value
    checkpoint.candidate_slug = key.slug
    checkpoint.candidate_branch = key.branch
    checkpoint.candidate_sha = key.sha
    checkpoint.lease_token = lease_token
    checkpoint.started_at = now
    _write_checkpoint(checkpoint_path, checkpoint)
    _mirror_integration_phase(cwd, key.slug, IntegrationPhase.CANDIDATE_DEQUEUED.value)

    logger.info("%s slug=%s phase=CANDIDATE_DEQUEUED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
    _emit_lifecycle_event(
        "integration.started", {"slug": key.slug, "session_id": session_id, "queue_depth": len(candidates)}
    )
    _emit_lifecycle_event("integration.candidate.dequeued", {"slug": key.slug, "branch": key.branch, "sha": key.sha})

    # Go straight to merge — worktree isolation + push rejection handle concurrency
    return True, ""  # loop into CANDIDATE_DEQUEUED → _do_merge


def _do_merge(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    key: CandidateKey,
    cwd: str,
) -> tuple[bool, str]:
    """Set up integration worktree, squash merge candidate. Write MERGE_CLEAN or MERGE_CONFLICTED."""
    # Ensure persistent integration worktree exists and is synced to origin/main
    integration_wt, err = _ensure_integration_worktree(cwd)
    if err:
        return False, _format_error("INTEGRATION_WORKTREE_FAILED", err)
    wt = str(integration_wt)

    # Record pre-merge HEAD for commit detection (in integration worktree)
    pre_merge_head = _get_head_sha(wt)
    checkpoint.pre_merge_head = pre_merge_head

    # Guard: skip candidates already merged to main (stale re-queue after restart)
    ancestor_rc, _, _ = _run_git(["merge-base", "--is-ancestor", key.sha, "HEAD"], cwd=wt)
    if ancestor_rc == 0:
        logger.info(
            "%s slug=%s sha=%s already ancestor of main — skipping as already integrated",
            _NEXT_INTEGRATE_PHASE_LOG,
            key.slug,
            key.sha[:8],
        )
        _emit_lifecycle_event(
            "integration.candidate.already_merged",
            {"slug": key.slug, "branch": key.branch, "sha": key.sha},
        )
        checkpoint.phase = IntegrationPhase.CANDIDATE_DELIVERED.value
        _write_checkpoint(checkpoint_path, checkpoint)
        return True, ""

    rc, _, _stderr = _run_git(["merge", "--squash", key.branch], cwd=wt)

    # Guard: squash merge produced no content changes — candidate already integrated.
    # Catches squash merges where ancestry check (above) doesn't fire because
    # squash commits don't create ancestry links.
    empty_rc, _, _ = _run_git(["diff", "--cached", "--quiet"], cwd=wt)
    if empty_rc == 0:
        conflicted = _get_conflicted_files(wt) if rc != 0 else []
        if not conflicted:
            logger.info(
                "%s slug=%s already integrated (empty squash merge) — skipping",
                _NEXT_INTEGRATE_PHASE_LOG,
                key.slug,
            )
            _emit_lifecycle_event(
                "integration.candidate.already_merged",
                {"slug": key.slug, "branch": key.branch, "sha": key.sha},
            )
            # Clean up SQUASH_MSG left by git (worktree-aware path)
            gd = _git_dir(wt)
            if gd:
                squash_msg = gd / "SQUASH_MSG"
                if squash_msg.exists():
                    squash_msg.unlink()
            checkpoint.phase = IntegrationPhase.CANDIDATE_DELIVERED.value
            _write_checkpoint(checkpoint_path, checkpoint)
            return True, ""

    if rc == 0:
        # Clean merge — read stats from integration worktree, context from repo root
        diff_stats = _get_diff_stats(wt)
        branch_log = _get_branch_log(wt, key.branch, base_ref="origin/main")
        requirements = _read_file_safe(Path(cwd) / "todos" / key.slug / "requirements.md")
        impl_plan = _read_file_safe(Path(cwd) / "todos" / key.slug / "implementation-plan.md")

        checkpoint.phase = IntegrationPhase.MERGE_CLEAN.value
        checkpoint.error_context = {"merge_type": "clean"}
        _write_checkpoint(checkpoint_path, checkpoint)
        _mirror_integration_phase(cwd, key.slug, IntegrationPhase.MERGE_CLEAN.value)
        _emit_lifecycle_event("integration.merge.succeeded", {"slug": key.slug, "branch": key.branch})
        logger.info("%s slug=%s phase=MERGE_CLEAN", _NEXT_INTEGRATE_PHASE_LOG, key.slug)

        return False, _format_commit_decision(key.slug, key.branch, diff_stats, branch_log, requirements, impl_plan)
    else:
        # Conflict
        conflicted_files = _get_conflicted_files(wt)
        checkpoint.phase = IntegrationPhase.MERGE_CONFLICTED.value
        checkpoint.error_context = {"merge_type": "conflicted", "conflicted_files": conflicted_files}
        _write_checkpoint(checkpoint_path, checkpoint)
        _mirror_integration_phase(cwd, key.slug, IntegrationPhase.MERGE_CONFLICTED.value)
        _emit_lifecycle_event(
            "integration.merge.conflicted",
            {"slug": key.slug, "branch": key.branch, "conflicted_files": conflicted_files},
        )
        logger.info(
            "%s slug=%s phase=MERGE_CONFLICTED files=%d", _NEXT_INTEGRATE_PHASE_LOG, key.slug, len(conflicted_files)
        )

        return False, _format_conflict_decision(key.slug, key.branch, conflicted_files)


def _step_awaiting_commit(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """MERGE_CLEAN / MERGE_CONFLICTED / AWAITING_COMMIT: check if agent committed in integration worktree."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "Awaiting-commit phase has no candidate key")

    wt = str(_integration_worktree_path(cwd))

    # Check for unresolved merge conflicts first (in integration worktree)
    if _merge_head_exists(wt):
        conflicted_files = _get_conflicted_files(wt)
        checkpoint.error_context = {**(checkpoint.error_context or {}), "conflicted_files": conflicted_files}
        _write_checkpoint(checkpoint_path, checkpoint)
        _mirror_integration_phase(cwd, key.slug, checkpoint.phase)
        return False, _format_conflict_decision(key.slug, key.branch, conflicted_files)

    # Check if HEAD advanced in integration worktree (commit happened)
    head_sha = _get_head_sha(wt)
    pre_merge = checkpoint.pre_merge_head
    if head_sha and pre_merge and head_sha != pre_merge:
        # Commit detected — advance to COMMITTED
        checkpoint.phase = IntegrationPhase.COMMITTED.value
        _write_checkpoint(checkpoint_path, checkpoint)
        _mirror_integration_phase(cwd, key.slug, IntegrationPhase.COMMITTED.value)
        _emit_lifecycle_event("integration.candidate.committed", {"slug": key.slug, "commit_sha": head_sha})
        logger.info("%s slug=%s phase=COMMITTED commit=%s", _NEXT_INTEGRATE_PHASE_LOG, key.slug, head_sha)
        return True, ""  # loop into COMMITTED

    # No commit yet — re-prompt
    merge_type = (checkpoint.error_context or {}).get("merge_type", "conflicted")
    if merge_type == "clean":
        diff_stats = _get_diff_stats(wt)
        branch_log = _get_branch_log(wt, key.branch, base_ref="origin/main")
        requirements = _read_file_safe(Path(cwd) / "todos" / key.slug / "requirements.md")
        impl_plan = _read_file_safe(Path(cwd) / "todos" / key.slug / "implementation-plan.md")
        return False, _format_commit_decision(key.slug, key.branch, diff_stats, branch_log, requirements, impl_plan)
    else:
        conflicted_files = list((checkpoint.error_context or {}).get("conflicted_files", []))
        return False, _format_conflict_decision(key.slug, key.branch, conflicted_files)


def _step_committed(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """COMMITTED: transition to DELIVERY_BOOKKEEPING."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "COMMITTED phase has no candidate key")

    checkpoint.phase = IntegrationPhase.DELIVERY_BOOKKEEPING.value
    _write_checkpoint(checkpoint_path, checkpoint)
    _mirror_integration_phase(cwd, key.slug, IntegrationPhase.DELIVERY_BOOKKEEPING.value)

    return True, ""  # loop into DELIVERY_BOOKKEEPING


def _step_delivery_bookkeeping(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """DELIVERY_BOOKKEEPING: run bookkeeping in integration worktree, then push all together.

    Bookkeeping commits (roadmap delivery, todo cleanup) are created in the
    integration worktree alongside the squash merge commit. This avoids the
    divergence that occurred when bookkeeping ran on repo root after the
    integration worktree had already pushed.
    """
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "DELIVERY_BOOKKEEPING phase has no candidate key")

    wt = str(_integration_worktree_path(cwd))

    # --- Delivery bookkeeping in integration worktree ---
    from teleclaude.core.next_machine.core import deliver_to_delivered

    if not deliver_to_delivered(wt, key.slug):
        logger.warning("deliver_to_delivered failed for %s (not in roadmap or delivered)", key.slug)

    # Reconcile stale entries that squash merges may re-introduce
    from teleclaude.core.next_machine.delivery import reconcile_roadmap_after_merge

    removed = reconcile_roadmap_after_merge(wt)
    if removed:
        logger.info("Reconciled stale roadmap entries after merge: %s", removed)

    _run_git(["add", "todos/roadmap.yaml", "todos/delivered.yaml"], cwd=wt)
    rc, _, _ = _run_git(["diff", "--cached", "--quiet"], cwd=wt)
    if rc != 0:  # staged changes exist
        _run_git(
            [
                "commit",
                "-m",
                (
                    f"chore({key.slug}): delivery bookkeeping\n\n"
                    "🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)\n\n"
                    "Co-Authored-By: TeleClaude <noreply@instrukt.ai>"
                ),
            ],
            cwd=wt,
        )

    # --- Todo cleanup in integration worktree ---
    from teleclaude.core.next_machine.icebox import clean_dependency_references

    todo_dir_wt = Path(wt) / "todos" / key.slug
    if todo_dir_wt.exists():
        _run_git(["rm", "-r", "--force", f"todos/{key.slug}"], cwd=wt)
    clean_dependency_references(wt, key.slug)
    _run_git(["add", "todos/"], cwd=wt)
    rc, _, _ = _run_git(["diff", "--cached", "--quiet"], cwd=wt)
    if rc != 0:
        _run_git(
            [
                "commit",
                "-m",
                (
                    f"chore({key.slug}): todo cleanup after delivery\n\n"
                    "🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)\n\n"
                    "Co-Authored-By: TeleClaude <noreply@instrukt.ai>"
                ),
            ],
            cwd=wt,
        )

    # --- Push all commits (squash + bookkeeping + cleanup) from integration worktree ---
    rc, stdout, stderr = _run_git(["push", "origin", "HEAD:main"], cwd=wt)
    if rc == 0:
        head_sha = _get_head_sha(wt)
        checkpoint.phase = IntegrationPhase.PUSH_SUCCEEDED.value
        _write_checkpoint(checkpoint_path, checkpoint)
        _mirror_integration_phase(cwd, key.slug, IntegrationPhase.PUSH_SUCCEEDED.value)
        _emit_lifecycle_event("integration.push.succeeded", {"slug": key.slug, "commit_sha": head_sha or "unknown"})
        logger.info("%s slug=%s phase=PUSH_SUCCEEDED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return True, ""  # loop into PUSH_SUCCEEDED
    else:
        rejection = (stderr or stdout).strip()
        checkpoint.phase = IntegrationPhase.PUSH_REJECTED.value
        checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": rejection}
        _write_checkpoint(checkpoint_path, checkpoint)
        _mirror_integration_phase(cwd, key.slug, IntegrationPhase.PUSH_REJECTED.value)
        _emit_lifecycle_event("integration.push.rejected", {"slug": key.slug, "rejection_reason": rejection})
        logger.info("%s slug=%s phase=PUSH_REJECTED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return False, _format_push_rejected(rejection, key.slug)


def _step_push_rejected(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """PUSH_REJECTED: check if agent recovered (integration worktree HEAD == remote main)."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "PUSH_REJECTED phase has no candidate key")

    wt = str(_integration_worktree_path(cwd))
    local_head = _get_head_sha(wt)
    remote_head = _get_remote_main_sha(wt)
    if local_head and remote_head and local_head == remote_head:
        # Recovery detected
        checkpoint.phase = IntegrationPhase.PUSH_SUCCEEDED.value
        _write_checkpoint(checkpoint_path, checkpoint)
        _mirror_integration_phase(cwd, key.slug, IntegrationPhase.PUSH_SUCCEEDED.value)
        _emit_lifecycle_event("integration.push.succeeded", {"slug": key.slug, "commit_sha": local_head})
        logger.info("%s slug=%s phase=PUSH_SUCCEEDED (recovered)", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return True, ""  # loop into PUSH_SUCCEEDED

    rejection = (checkpoint.error_context or {}).get("rejection_reason", "unknown rejection")
    return False, _format_push_rejected(rejection, key.slug)


def _step_push_succeeded(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """PUSH_SUCCEEDED: sync repo root with pushed origin/main, then cleanup."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "PUSH_SUCCEEDED phase has no candidate key")

    # Sync repo root with origin/main (now contains squash + bookkeeping + cleanup commits)
    rc, _, stderr = _run_git(["pull", "--ff-only", "origin", "main"], cwd=cwd)
    if rc != 0:
        # Advance to CLEANUP so re-entry after agent fixes dirty files
        # picks up at cleanup normally.
        checkpoint.phase = IntegrationPhase.CLEANUP.value
        _write_checkpoint(checkpoint_path, checkpoint)
        return False, _format_pull_blocked(stderr.strip(), key.slug)

    checkpoint.phase = IntegrationPhase.CLEANUP.value
    _write_checkpoint(checkpoint_path, checkpoint)
    return _do_cleanup(checkpoint=checkpoint, checkpoint_path=checkpoint_path, key=key, cwd=cwd)


def _step_cleanup(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """CLEANUP: idempotent re-entry for cleanup after crash."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "CLEANUP phase has no candidate key")

    return _do_cleanup(checkpoint=checkpoint, checkpoint_path=checkpoint_path, key=key, cwd=cwd)


def _do_cleanup(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    key: CandidateKey,
    cwd: str,
) -> tuple[bool, str]:
    """Perform cleanup and advance to CANDIDATE_DELIVERED.

    Git-tracked bookkeeping (roadmap delivery, todo removal, dependency
    cleanup) was already committed in the integration worktree and pushed
    to origin/main during DELIVERY_BOOKKEEPING. This step delegates to
    cleanup_delivered_slug which handles physical artifacts (worktree
    removal, branch deletion, leftover directory removal) and also runs
    clean_dependency_references idempotently on repo root.

    The worktree cleanup removes the ``state.yaml`` — that IS the
    consumption mechanism. No separate queue bookkeeping needed.
    """
    from teleclaude.core.next_machine.core import cleanup_delivered_slug

    # Merge commit SHA lives in the integration worktree (where delivery was committed)
    wt = str(_integration_worktree_path(cwd))
    merge_commit = _get_head_sha(wt) or "unknown"

    # Delegates to cleanup_delivered_slug for physical artifacts (worktree,
    # branch, leftover dirs) plus idempotent dependency reference cleanup.
    cleanup_delivered_slug(cwd, key.slug, branch=key.branch)

    _emit_lifecycle_event(
        "integration.candidate.delivered",
        {"slug": key.slug, "branch": key.branch, "merge_commit_sha": merge_commit},
    )

    checkpoint.phase = IntegrationPhase.CANDIDATE_DELIVERED.value
    checkpoint.items_processed += 1
    _write_checkpoint(checkpoint_path, checkpoint)
    _mirror_integration_phase(cwd, key.slug, IntegrationPhase.CANDIDATE_DELIVERED.value)
    logger.info("%s slug=%s phase=CANDIDATE_DELIVERED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)

    return True, ""  # loop to pop next candidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_release_lease(lease_store: IntegrationLeaseStore, session_id: str, lease_token: str | None) -> None:
    if not lease_token:
        return
    try:
        lease_store.release(key=_INTEGRATION_LEASE_KEY, owner_session_id=session_id, lease_token=lease_token)
    except Exception:
        pass


def _mirror_integration_phase(cwd: str, slug: str, phase: str) -> None:
    """Write integration_phase into the candidate todo's per-todo state.yaml.

    Best-effort: failures are logged but do not block the integration flow.
    """
    try:
        from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state

        state = read_phase_state(cwd, slug)
        state["integration_phase"] = phase
        write_phase_state(cwd, slug, state)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("_mirror_integration_phase failed for %s phase=%s: %s", slug, phase, exc)


