"""Integration step functions — git helpers, phase helpers, step implementations.

No imports from state_machine.py (circular-import guard).
Instruction formatters live in formatters.py.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
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
    _format_push_rejected,
    _format_queue_empty,
)
from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.queue import IntegrationQueue
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


def _is_bug_slug(cwd: str, slug: str) -> bool:
    """Heuristic: check for a bug.md in todos/{slug}/."""
    return (Path(cwd) / "todos" / slug / "bug.md").exists()


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


def _try_auto_enqueue(*, queue: IntegrationQueue, slug: str, cwd: str) -> bool:
    """Auto-enqueue a candidate when called by slug but not yet in the queue.

    Derives branch name from slug (convention: branch == slug) and resolves
    the SHA from the local branch ref. Used for legacy/manual direct-integrate
    entry when a caller invokes ``telec todo integrate <slug>`` without a
    prior queue population step.

    Skips enqueue when the candidate is already tracked in the queue (any
    status) — this is the primary guard against re-enqueue loops, covering
    cases where recovery requeues in_progress items or squash merges bypass
    ancestry detection. Also skips when the candidate SHA is already an
    ancestor of main (fast-forward integrated).
    """
    branch = slug  # branch == slug by project convention
    rc, stdout, _ = _run_git(["rev-parse", branch], cwd=cwd)
    if rc != 0 or not stdout.strip():
        logger.warning("Auto-enqueue: could not resolve SHA for branch %s", branch)
        return False
    sha = stdout.strip()
    # Validate SHA looks like a 40-char hex (guards against git printing non-SHA output)
    if len(sha) != 40 or not all(c in "0123456789abcdefABCDEF" for c in sha):
        logger.warning("Auto-enqueue: invalid SHA for branch %s: %r", branch, sha)
        return False
    # Skip if already tracked in queue (any status — prevents re-enqueue loops
    # when recovery requeues in_progress items or squash merges bypass ancestry)
    existing = queue.get(key=CandidateKey(slug=slug, branch=branch, sha=sha))
    if existing is not None:
        logger.info("Auto-enqueue: %s already in queue (status=%s) — skipping", slug, existing.status)
        return False
    ancestor_rc, _, _ = _run_git(["merge-base", "--is-ancestor", sha, "HEAD"], cwd=cwd)
    if ancestor_rc == 0:
        logger.info("Auto-enqueue: %s (sha=%s) already ancestor of main — skipping", slug, sha[:8])
        return False
    ready_at = _now_iso()
    try:
        queue.enqueue(key=CandidateKey(slug=slug, branch=branch, sha=sha), ready_at=ready_at)
        logger.info("Auto-enqueued candidate %s (branch=%s sha=%s)", slug, branch, sha[:8])
        return True
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Auto-enqueue failed for %s: %s", slug, exc)
        return False


def _step_idle(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    queue: IntegrationQueue,
    lease_store: IntegrationLeaseStore,
    session_id: str,
    slug: str | None,
    cwd: str,
    started: float,
) -> tuple[bool, str]:
    """IDLE: check queue, acquire lease, pop candidate, proceed to merge."""
    queued_items = [item for item in queue.items() if item.status == "queued"]
    if not queued_items:
        # When a specific slug is requested, auto-enqueue from the local branch
        # (branch == slug by convention). This preserves the legacy/manual
        # direct-integrate path where a caller invokes
        # ``telec todo integrate <slug>`` without a prior deployment event.
        if slug is not None:
            _try_auto_enqueue(queue=queue, slug=slug, cwd=cwd)
            queued_items = [item for item in queue.items() if item.status == "queued"]

    if not queued_items:
        elapsed_ms = int((perf_counter() - started) * 1000)
        # Release any stale lease we might hold
        _try_release_lease(lease_store, session_id, checkpoint.lease_token)
        return False, _format_queue_empty(checkpoint.items_processed, checkpoint.items_blocked, elapsed_ms)

    # Validate slug filter (queue is FIFO)
    if slug is not None:
        next_item = queued_items[0]
        if next_item.key.slug != slug:
            return False, _format_error(
                "SLUG_NOT_NEXT",
                f"Requested slug '{slug}' is not next in queue (next: '{next_item.key.slug}').\n"
                "The integration queue is FIFO. Process queued items in order.",
            )

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

    # Pop next candidate
    item = queue.pop_next()
    if item is None:
        # Race between count and pop
        lease_store.release(key=_INTEGRATION_LEASE_KEY, owner_session_id=session_id, lease_token=lease_token)
        elapsed_ms = int((perf_counter() - started) * 1000)
        return False, _format_queue_empty(checkpoint.items_processed, checkpoint.items_blocked, elapsed_ms)

    key = item.key
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
        "integration.started", {"slug": key.slug, "session_id": session_id, "queue_depth": len(queued_items)}
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
    """COMMITTED: push from integration worktree first, then bookkeeping on repo root."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "COMMITTED phase has no candidate key")

    checkpoint.phase = IntegrationPhase.DELIVERY_BOOKKEEPING.value
    _write_checkpoint(checkpoint_path, checkpoint)
    _mirror_integration_phase(cwd, key.slug, IntegrationPhase.DELIVERY_BOOKKEEPING.value)

    return True, ""  # loop into DELIVERY_BOOKKEEPING → push


def _step_delivery_bookkeeping(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """DELIVERY_BOOKKEEPING: push from integration worktree to origin/main."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "DELIVERY_BOOKKEEPING phase has no candidate key")

    wt = str(_integration_worktree_path(cwd))
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
    queue: IntegrationQueue,
    cwd: str,
) -> tuple[bool, str]:
    """PUSH_SUCCEEDED: sync repo root with pushed origin/main, run delivery bookkeeping, then cleanup."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "PUSH_SUCCEEDED phase has no candidate key")

    # Sync repo root with origin/main (now contains the squash commit)
    rc, _, stderr = _run_git(["pull", "--ff-only", "origin", "main"], cwd=cwd)
    if rc != 0:
        logger.warning("repo root pull failed after push: %s", stderr.strip())
        # Non-fatal: bookkeeping will still work on repo root, just with stale HEAD.
        # The entry-point pull on next `telec todo integrate` call will catch divergence.

    # Delivery bookkeeping on repo root — operational metadata, not delivery content
    is_bug = _is_bug_slug(cwd, key.slug)
    if not is_bug:
        from teleclaude.core.next_machine.core import deliver_to_delivered

        if not deliver_to_delivered(cwd, key.slug):
            logger.warning("deliver_to_delivered failed for %s (not in roadmap or delivered)", key.slug)

    # Stage only bookkeeping files (not git add -A which sweeps dirty main)
    _run_git(["add", "todos/roadmap.yaml", "todos/delivered.yaml"], cwd=cwd)
    rc, _, _ = _run_git(["diff", "--cached", "--quiet"], cwd=cwd)
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
            cwd=cwd,
        )

    checkpoint.phase = IntegrationPhase.CLEANUP.value
    _write_checkpoint(checkpoint_path, checkpoint)
    return _do_cleanup(checkpoint=checkpoint, checkpoint_path=checkpoint_path, queue=queue, key=key, cwd=cwd)


def _step_cleanup(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    queue: IntegrationQueue,
    cwd: str,
) -> tuple[bool, str]:
    """CLEANUP: idempotent re-entry for cleanup after crash."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "CLEANUP phase has no candidate key")

    return _do_cleanup(checkpoint=checkpoint, checkpoint_path=checkpoint_path, queue=queue, key=key, cwd=cwd)


def _do_cleanup(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    queue: IntegrationQueue,
    key: CandidateKey,
    cwd: str,
) -> tuple[bool, str]:
    """Perform cleanup and advance to CANDIDATE_DELIVERED."""
    from teleclaude.core.next_machine.core import cleanup_delivered_slug

    # Merge commit SHA lives in the integration worktree (where delivery was committed)
    wt = str(_integration_worktree_path(cwd))
    merge_commit = _get_head_sha(wt) or "unknown"

    # Delegate physical cleanup (worktree, branch, todo dir, deps)
    cleanup_delivered_slug(cwd, key.slug, branch=key.branch)

    # Stage todo directory removal and commit
    _run_git(["add", f"todos/{key.slug}"], cwd=cwd)
    rc, _, _ = _run_git(["diff", "--cached", "--quiet"], cwd=cwd)
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
            cwd=cwd,
        )

    # Push bookkeeping + cleanup commits to origin/main so repo root stays in sync
    rc, _, stderr = _run_git(["push", "origin", "main"], cwd=cwd)
    if rc != 0:
        logger.warning("repo root push after cleanup failed: %s", stderr.strip())

    _emit_lifecycle_event(
        "integration.candidate.delivered",
        {"slug": key.slug, "branch": key.branch, "merge_commit_sha": merge_commit},
    )

    # Mark integrated and advance checkpoint
    try:
        queue.mark_integrated(key=key, reason="integrated via state machine")
    except Exception as exc:
        logger.warning("mark_integrated failed for %s: %s", key.slug, exc)

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


