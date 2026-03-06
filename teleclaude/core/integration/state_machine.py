"""Deterministic state machine for integration lifecycle management.

Implements `next_integrate()` — the entry point for `telec todo integrate`.
Each call reads a durable checkpoint, executes the next deterministic step,
and returns structured instructions at decision points where agent intelligence
is required.

The state machine is the authority on sequencing.
The agent is the authority on intelligence. Neither does the other's job.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.core.db import Db
from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.queue import IntegrationQueue
from teleclaude.core.integration.readiness_projection import CandidateKey
from teleclaude.core.integration.runtime import MainBranchClearanceProbe, SessionSnapshot

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INTEGRATION_LEASE_KEY = "integration/main"
_INTEGRATION_LEASE_TTL_SECONDS = 120
_NEXT_INTEGRATE_PHASE_LOG = "NEXT_INTEGRATE_PHASE"
_CHECKPOINT_VERSION = 1
_LOOP_LIMIT = 50  # safety cap on internal state transitions per call

# Thread-local storage for event loop reference (used in fire-and-forget async emission)
_tls = threading.local()


# ---------------------------------------------------------------------------
# Phase enum and checkpoint
# ---------------------------------------------------------------------------


class IntegrationPhase(str, Enum):
    """All valid integration lifecycle phases."""

    IDLE = "idle"
    LEASE_ACQUIRED = "lease_acquired"
    CANDIDATE_DEQUEUED = "candidate_dequeued"
    CLEARANCE_WAIT = "clearance_wait"
    MERGE_CLEAN = "merge_clean"
    MERGE_CONFLICTED = "merge_conflicted"
    AWAITING_COMMIT = "awaiting_commit"
    COMMITTED = "committed"
    DELIVERY_BOOKKEEPING = "delivery_bookkeeping"
    PUSH_SUCCEEDED = "push_succeeded"
    PUSH_REJECTED = "push_rejected"
    CLEANUP = "cleanup"
    CANDIDATE_DELIVERED = "candidate_delivered"
    COMPLETED = "completed"


@dataclass
class IntegrationCheckpoint:
    """Durable checkpoint for crash recovery and idempotent re-entry."""

    phase: str  # IntegrationPhase value
    candidate_slug: str | None
    candidate_branch: str | None
    candidate_sha: str | None
    lease_token: str | None
    items_processed: int
    items_blocked: int
    started_at: str  # ISO8601
    last_updated_at: str  # ISO8601
    # Optional context: conflicted files, rejection reason, merge type
    error_context: dict[str, Any] | None  # guard: loose-dict - per-phase metadata bag (shape varies by phase)
    # SHA of main before merge — used to detect when agent commits
    pre_merge_head: str | None


class _CheckpointPayload(TypedDict):
    version: int
    phase: str
    candidate_slug: str | None
    candidate_branch: str | None
    candidate_sha: str | None
    lease_token: str | None
    items_processed: int
    items_blocked: int
    started_at: str
    last_updated_at: str
    error_context: dict[str, Any] | None  # guard: loose-dict - per-phase metadata bag (shape varies by phase)
    pre_merge_head: str | None


# ---------------------------------------------------------------------------
# Checkpoint I/O
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _read_checkpoint(path: Path) -> IntegrationCheckpoint:
    """Read checkpoint; return fresh IDLE checkpoint when absent or corrupt."""
    now = _now_iso()
    default = IntegrationCheckpoint(
        phase=IntegrationPhase.IDLE.value,
        candidate_slug=None,
        candidate_branch=None,
        candidate_sha=None,
        lease_token=None,
        items_processed=0,
        items_blocked=0,
        started_at=now,
        last_updated_at=now,
        error_context=None,
        pre_merge_head=None,
    )
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return default
        data: dict[str, Any] = json.loads(raw)  # guard: loose-dict - JSON from disk, validated field-by-field below
        return IntegrationCheckpoint(
            phase=data.get("phase", IntegrationPhase.IDLE.value),
            candidate_slug=data.get("candidate_slug"),
            candidate_branch=data.get("candidate_branch"),
            candidate_sha=data.get("candidate_sha"),
            lease_token=data.get("lease_token"),
            items_processed=int(data.get("items_processed", 0)),
            items_blocked=int(data.get("items_blocked", 0)),
            started_at=data.get("started_at", now),
            last_updated_at=data.get("last_updated_at", now),
            error_context=data.get("error_context"),
            pre_merge_head=data.get("pre_merge_head"),
        )
    except Exception:
        logger.warning("Failed to read integration checkpoint at %s; starting fresh", path)
        return default


def _write_checkpoint(path: Path, checkpoint: IntegrationCheckpoint) -> None:
    """Write checkpoint atomically via temp-file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _now_iso()
    checkpoint.last_updated_at = now
    payload: _CheckpointPayload = {
        "version": _CHECKPOINT_VERSION,
        "phase": checkpoint.phase,
        "candidate_slug": checkpoint.candidate_slug,
        "candidate_branch": checkpoint.candidate_branch,
        "candidate_sha": checkpoint.candidate_sha,
        "lease_token": checkpoint.lease_token,
        "items_processed": checkpoint.items_processed,
        "items_blocked": checkpoint.items_blocked,
        "started_at": checkpoint.started_at,
        "last_updated_at": now,
        "error_context": checkpoint.error_context,
        "pre_merge_head": checkpoint.pre_merge_head,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# State paths
# ---------------------------------------------------------------------------


def _default_state_dir() -> Path:
    return Path.home() / ".teleclaude" / "integration"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run_git(args: list[str], *, cwd: str) -> tuple[int, str, str]:
    """Run a git command; return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result.returncode, result.stdout, result.stderr


def _get_head_sha(cwd: str) -> str | None:
    rc, stdout, _ = _run_git(["rev-parse", "HEAD"], cwd=cwd)
    return stdout.strip() if rc == 0 and stdout.strip() else None


def _get_remote_main_sha(cwd: str) -> str | None:
    rc, stdout, _ = _run_git(["ls-remote", "origin", "refs/heads/main"], cwd=cwd)
    if rc != 0 or not stdout.strip():
        return None
    parts = stdout.strip().split()
    return parts[0] if parts else None


def _merge_head_exists(cwd: str) -> bool:
    return (Path(cwd) / ".git" / "MERGE_HEAD").exists()


def _get_conflicted_files(cwd: str) -> list[str]:
    rc, stdout, _ = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=cwd)
    if rc != 0:
        return []
    return [f.strip() for f in stdout.splitlines() if f.strip()]


def _get_diff_stats(cwd: str) -> str:
    rc, stdout, _ = _run_git(["diff", "--cached", "--stat"], cwd=cwd)
    return stdout.strip() if rc == 0 else ""


def _get_branch_log(cwd: str, branch: str) -> str:
    rc, stdout, _ = _run_git(["log", f"main..{branch}", "--oneline", "--no-decorate"], cwd=cwd)
    return stdout.strip() if rc == 0 else ""


def _read_file_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Clearance probe factory
# ---------------------------------------------------------------------------


def _make_clearance_probe(cwd: str) -> MainBranchClearanceProbe:
    """Create a MainBranchClearanceProbe backed by telec CLI calls and git status."""

    def _sessions_provider() -> tuple[SessionSnapshot, ...]:
        try:
            result = subprocess.run(
                ["telec", "sessions", "list", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=cwd,
            )
            if result.returncode != 0:
                return ()
            data = json.loads(result.stdout)
            raw_sessions = data if isinstance(data, list) else data.get("sessions", [])
            return tuple(
                SessionSnapshot(
                    session_id=s["session_id"],
                    initiator_session_id=s.get("initiator_session_id"),
                )
                for s in raw_sessions
                if isinstance(s, dict) and s.get("session_id")
            )
        except Exception:
            return ()

    def _tail_provider(session_id: str) -> str:
        try:
            result = subprocess.run(
                ["telec", "sessions", "tail", session_id],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=cwd,
            )
            return result.stdout if result.returncode == 0 else ""
        except Exception:
            return ""

    def _dirty_paths_provider() -> tuple[str, ...]:
        try:
            rc, stdout, _ = _run_git(["status", "--short", "-uno"], cwd=cwd)
            if rc != 0:
                return ()
            paths: list[str] = []
            for line in stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    paths.append(parts[-1])
            return tuple(paths)
        except Exception:
            return ()

    return MainBranchClearanceProbe(
        sessions_provider=_sessions_provider,
        session_tail_provider=_tail_provider,
        dirty_tracked_paths_provider=_dirty_paths_provider,
    )


# ---------------------------------------------------------------------------
# Instruction formatters
# ---------------------------------------------------------------------------


def _format_commit_decision(
    slug: str,
    branch: str,
    diff_stats: str,
    branch_log: str,
    requirements: str,
    impl_plan: str,
) -> str:
    return f"""INTEGRATION DECISION: SQUASH COMMIT REQUIRED

Candidate: {slug} (branch: {branch})

The branch has been squash-merged into main. Stage is ready.
Compose and execute a squash commit that captures the full delivery intent.

## Diff Stats
{diff_stats or "(no staged changes stat available)"}

## Branch Commit History
{branch_log or "(no history available)"}

## Requirements
{requirements[:2000] if requirements else "(not available)"}

## Implementation Plan
{impl_plan[:2000] if impl_plan else "(not available)"}

## Your Task
1. Review the above context
2. Compose a commit message:
   - Subject: clear, imperative, scoped (e.g. "feat({slug}): deliver {slug}")
   - Body: summarize what changed, key decisions, scope
   - Footer: TeleClaude Co-Authored-By trailer
3. Run: git commit -m '<your message>'
4. Then call: telec todo integrate

NEXT: Compose and execute git commit, then call telec todo integrate"""


def _format_conflict_decision(slug: str, branch: str, conflicted_files: list[str]) -> str:
    file_list = "\n".join(f"  - {f}" for f in conflicted_files) if conflicted_files else "  (none detected)"
    return f"""INTEGRATION DECISION: CONFLICT RESOLUTION REQUIRED

Candidate: {slug} (branch: {branch})

The squash merge of {branch} into main encountered conflicts:
{file_list}

## Your Task
1. Examine each conflicted file and understand the code context
2. Resolve all conflict markers (<<<< ==== >>>>)
3. Stage resolved files: git add <files>
4. Compose a commit message capturing the delivery intent (same quality as squash commit)
5. Run: git commit -m '<your message>'
6. Then call: telec todo integrate

If conflicts are unresolvable, call: telec todo integrate
(The state machine will detect no commit was made and re-prompt.
To explicitly block the candidate, the agent must mark_blocked via queue.)

NEXT: Resolve conflicts, stage, commit, then call telec todo integrate"""


def _format_clearance_wait(blocking_session_ids: tuple[str, ...], dirty_paths: tuple[str, ...]) -> str:
    lines = ["INTEGRATION WAIT: Main branch not clear for integration"]
    if blocking_session_ids:
        lines.append("\nBlocking sessions (active work on main detected):")
        for sid in blocking_session_ids:
            lines.append(f"  - {sid}")
    if dirty_paths:
        lines.append("\nDirty tracked paths on main:")
        for p in dirty_paths:
            lines.append(f"  - {p}")
    lines.append("\nCall telec todo integrate again once blockers are resolved.")
    lines.append("\nNEXT: Wait for blockers to clear, then call telec todo integrate")
    return "\n".join(lines)


def _format_housekeeping_commit(dirty_paths: tuple[str, ...]) -> str:
    file_list = "\n".join(f"  - {p}" for p in dirty_paths)
    add_args = " ".join(dirty_paths)
    return f"""INTEGRATION DECISION: HOUSEKEEPING COMMIT REQUIRED

Main has uncommitted tracked changes that must be committed before integration can proceed.

## Dirty paths
{file_list}

## Your Task
1. Review each dirty file briefly to understand what changed
2. Compose a concise commit message describing the in-flight changes
3. Run:
   git add {add_args}
   git commit -m '<your message>'
4. Then call: telec todo integrate

NEXT: Commit the dirty paths above, then call telec todo integrate"""


def _format_push_rejected(rejection_reason: str, slug: str) -> str:
    return f"""INTEGRATION DECISION: PUSH REJECTION RECOVERY

Candidate: {slug}

Push of main to origin was rejected.
Rejection output:
{rejection_reason}

## Your Task
1. Diagnose the rejection (likely non-fast-forward — another commit landed)
2. Fetch and rebase: git fetch origin && git rebase origin/main
3. Resolve any new conflicts if present
4. Push again: git push origin main
5. Then call: telec todo integrate

NEXT: Pull/rebase, resolve (if needed), push, then call telec todo integrate"""


def _format_lease_busy(holder_session_id: str) -> str:
    return f"""INTEGRATION ERROR: LEASE_BUSY

Another integrator session ({holder_session_id}) already holds the integration lease.
Only one integrator may run at a time.

Exit this session immediately. The active integrator will drain the queue.

NEXT: End this session — another integrator is already active"""


def _format_queue_empty(items_processed: int, items_blocked: int, duration_ms: int) -> str:
    return f"""INTEGRATION COMPLETE: Queue empty

Candidates processed: {items_processed}
Candidates blocked: {items_blocked}
Duration: {duration_ms}ms

The integration queue is empty. Self-end this session.

NEXT: End this session — integration complete"""


def _format_error(code: str, message: str) -> str:
    return f"INTEGRATION ERROR: {code}\n{message}"


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
    """Heuristic: check for a bug.md in todos/bugs/{slug}/."""
    return (Path(cwd) / "todos" / "bugs" / slug / "bug.md").exists()


# guard: loose-dict-func - lifecycle event payload shape varies per event type
async def _bridge_emit(
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Dispatch lifecycle event to the appropriate integration_bridge helper."""
    # Lazy import to avoid circular dependency at module load time
    from teleclaude.core import integration_bridge as bridge  # noqa: PLC0415

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
# Core phase dispatch (synchronous inner loop)
# ---------------------------------------------------------------------------


def _dispatch_sync(
    *,
    session_id: str,
    slug: str | None,
    cwd: str,
    state_dir: Path,
    started: float,
    loop: asyncio.AbstractEventLoop | None = None,
) -> str:
    """Synchronous state machine loop. Returns instruction string for the agent."""
    _tls.loop = loop
    checkpoint_path = state_dir / "integrate-state.json"

    for _iter in range(_LOOP_LIMIT):
        queue = IntegrationQueue(state_path=state_dir / "queue.json")
        lease_store = IntegrationLeaseStore(state_path=state_dir / "lease.json")
        checkpoint = _read_checkpoint(checkpoint_path)

        try:
            phase = IntegrationPhase(checkpoint.phase)
        except ValueError:
            return _format_error("UNKNOWN_PHASE", f"Unrecognised checkpoint phase: {checkpoint.phase!r}")

        logger.info(
            "%s slug=%s phase=%s session=%s iter=%d",
            _NEXT_INTEGRATE_PHASE_LOG,
            checkpoint.candidate_slug or slug or "<auto>",
            phase.value,
            session_id,
            _iter,
        )

        # Each handler returns (continue_loop: bool, instruction: str)
        keep_going, instruction = _step(
            phase=phase,
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            queue=queue,
            lease_store=lease_store,
            session_id=session_id,
            slug=slug,
            cwd=cwd,
            started=started,
        )
        if not keep_going:
            return instruction

    return _format_error("LOOP_LIMIT", f"State machine exceeded {_LOOP_LIMIT} internal transitions")


def _step(
    *,
    phase: IntegrationPhase,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    queue: IntegrationQueue,
    lease_store: IntegrationLeaseStore,
    session_id: str,
    slug: str | None,
    cwd: str,
    started: float,
) -> tuple[bool, str]:
    """Execute one phase step. Returns (continue_loop, instruction_or_empty)."""
    if phase == IntegrationPhase.IDLE:
        return _step_idle(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            queue=queue,
            lease_store=lease_store,
            session_id=session_id,
            slug=slug,
            cwd=cwd,
            started=started,
        )

    if phase == IntegrationPhase.CLEARANCE_WAIT:
        return _step_clearance_wait(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            session_id=session_id,
            cwd=cwd,
        )

    if phase in (IntegrationPhase.MERGE_CLEAN, IntegrationPhase.MERGE_CONFLICTED, IntegrationPhase.AWAITING_COMMIT):
        return _step_awaiting_commit(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
        )

    if phase == IntegrationPhase.COMMITTED:
        return _step_committed(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
        )

    if phase == IntegrationPhase.DELIVERY_BOOKKEEPING:
        return _step_delivery_bookkeeping(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
        )

    if phase == IntegrationPhase.PUSH_REJECTED:
        return _step_push_rejected(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            cwd=cwd,
        )

    if phase == IntegrationPhase.PUSH_SUCCEEDED:
        return _step_push_succeeded(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            queue=queue,
            cwd=cwd,
        )

    if phase == IntegrationPhase.CLEANUP:
        return _step_cleanup(
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            queue=queue,
            cwd=cwd,
        )

    if phase == IntegrationPhase.CANDIDATE_DELIVERED:
        # Reset and loop for next candidate
        key = _get_candidate_key(checkpoint)
        if key:
            try:
                queue.mark_integrated(key=key, reason="integrated via state machine")
            except Exception as exc:
                logger.warning("mark_integrated failed for %s: %s", key.slug, exc)
        checkpoint.phase = IntegrationPhase.IDLE.value
        checkpoint.candidate_slug = None
        checkpoint.candidate_branch = None
        checkpoint.candidate_sha = None
        checkpoint.lease_token = None
        checkpoint.pre_merge_head = None
        checkpoint.error_context = None
        _write_checkpoint(checkpoint_path, checkpoint)
        return True, ""  # loop

    if phase == IntegrationPhase.COMPLETED:
        elapsed_ms = int((perf_counter() - started) * 1000)
        return False, _format_queue_empty(checkpoint.items_processed, checkpoint.items_blocked, elapsed_ms)

    return False, _format_error("UNHANDLED_PHASE", f"No handler for phase: {phase.value}")


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


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
    """IDLE: check queue, acquire lease, pop candidate, check clearance, do merge."""
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

    logger.info("%s slug=%s phase=CANDIDATE_DEQUEUED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
    _emit_lifecycle_event(
        "integration.started", {"slug": key.slug, "session_id": session_id, "queue_depth": len(queued_items)}
    )
    _emit_lifecycle_event("integration.candidate.dequeued", {"slug": key.slug, "branch": key.branch, "sha": key.sha})

    # Check clearance
    clearance_probe = _make_clearance_probe(cwd)
    clearance = clearance_probe.check(exclude_session_id=session_id)
    if clearance.blocking_session_ids:
        checkpoint.phase = IntegrationPhase.CLEARANCE_WAIT.value
        _write_checkpoint(checkpoint_path, checkpoint)
        return False, _format_clearance_wait(clearance.blocking_session_ids, clearance.dirty_tracked_paths)
    if clearance.dirty_tracked_paths:
        checkpoint.phase = IntegrationPhase.CLEARANCE_WAIT.value
        _write_checkpoint(checkpoint_path, checkpoint)
        return False, _format_housekeeping_commit(clearance.dirty_tracked_paths)

    # Do merge
    return _do_merge(
        checkpoint=checkpoint,
        checkpoint_path=checkpoint_path,
        key=key,
        cwd=cwd,
    )


def _step_clearance_wait(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    session_id: str,
    cwd: str,
) -> tuple[bool, str]:
    """CLEARANCE_WAIT: re-check clearance, proceed or stay waiting."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "CLEARANCE_WAIT checkpoint missing candidate key")

    clearance_probe = _make_clearance_probe(cwd)
    clearance = clearance_probe.check(exclude_session_id=session_id)
    if clearance.blocking_session_ids:
        return False, _format_clearance_wait(clearance.blocking_session_ids, clearance.dirty_tracked_paths)
    if clearance.dirty_tracked_paths:
        return False, _format_housekeeping_commit(clearance.dirty_tracked_paths)

    return _do_merge(
        checkpoint=checkpoint,
        checkpoint_path=checkpoint_path,
        key=key,
        cwd=cwd,
    )


def _do_merge(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    key: CandidateKey,
    cwd: str,
) -> tuple[bool, str]:
    """Fetch, checkout main, pull, squash merge. Write MERGE_CLEAN or MERGE_CONFLICTED."""
    # Record pre-merge HEAD for commit detection
    pre_merge_head = _get_head_sha(cwd)
    checkpoint.pre_merge_head = pre_merge_head

    rc, _, stderr = _run_git(["fetch", "origin"], cwd=cwd)
    if rc != 0:
        return False, _format_error("GIT_FETCH_FAILED", f"git fetch origin failed:\n{stderr.strip()}")

    rc, _, stderr = _run_git(["checkout", "main"], cwd=cwd)
    if rc != 0:
        return False, _format_error("GIT_CHECKOUT_FAILED", f"git checkout main failed:\n{stderr.strip()}")

    rc, _, stderr = _run_git(["pull", "--ff-only", "origin", "main"], cwd=cwd)
    if rc != 0:
        return False, _format_error("GIT_PULL_FAILED", f"git pull --ff-only failed:\n{stderr.strip()}")

    # Re-record pre-merge HEAD (it may have advanced from pull)
    pre_merge_head = _get_head_sha(cwd)
    checkpoint.pre_merge_head = pre_merge_head

    rc, _, stderr = _run_git(["merge", "--squash", key.branch], cwd=cwd)
    if rc == 0:
        # Clean merge
        diff_stats = _get_diff_stats(cwd)
        branch_log = _get_branch_log(cwd, key.branch)
        todos_root = Path(cwd)
        requirements = _read_file_safe(todos_root / "todos" / key.slug / "requirements.md")
        impl_plan = _read_file_safe(todos_root / "todos" / key.slug / "implementation-plan.md")

        checkpoint.phase = IntegrationPhase.MERGE_CLEAN.value
        checkpoint.error_context = {"merge_type": "clean"}
        _write_checkpoint(checkpoint_path, checkpoint)
        _emit_lifecycle_event("integration.merge.succeeded", {"slug": key.slug, "branch": key.branch})
        logger.info("%s slug=%s phase=MERGE_CLEAN", _NEXT_INTEGRATE_PHASE_LOG, key.slug)

        return False, _format_commit_decision(key.slug, key.branch, diff_stats, branch_log, requirements, impl_plan)
    else:
        # Conflict
        conflicted_files = _get_conflicted_files(cwd)
        checkpoint.phase = IntegrationPhase.MERGE_CONFLICTED.value
        checkpoint.error_context = {"merge_type": "conflicted", "conflicted_files": conflicted_files}
        _write_checkpoint(checkpoint_path, checkpoint)
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
    """MERGE_CLEAN / MERGE_CONFLICTED / AWAITING_COMMIT: check if agent committed."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "Awaiting-commit phase has no candidate key")

    # Check for unresolved merge conflicts first
    if _merge_head_exists(cwd):
        conflicted_files = _get_conflicted_files(cwd)
        checkpoint.error_context = {**(checkpoint.error_context or {}), "conflicted_files": conflicted_files}
        _write_checkpoint(checkpoint_path, checkpoint)
        return False, _format_conflict_decision(key.slug, key.branch, conflicted_files)

    # Check if HEAD advanced (commit happened)
    head_sha = _get_head_sha(cwd)
    pre_merge = checkpoint.pre_merge_head
    if head_sha and pre_merge and head_sha != pre_merge:
        # Commit detected — advance to COMMITTED
        checkpoint.phase = IntegrationPhase.COMMITTED.value
        _write_checkpoint(checkpoint_path, checkpoint)
        _emit_lifecycle_event("integration.candidate.committed", {"slug": key.slug, "commit_sha": head_sha})
        logger.info("%s slug=%s phase=COMMITTED commit=%s", _NEXT_INTEGRATE_PHASE_LOG, key.slug, head_sha)
        return True, ""  # loop into COMMITTED

    # No commit yet — re-prompt
    merge_type = (checkpoint.error_context or {}).get("merge_type", "conflicted")
    if merge_type == "clean":
        diff_stats = _get_diff_stats(cwd)
        branch_log = _get_branch_log(cwd, key.branch)
        todos_root = Path(cwd)
        requirements = _read_file_safe(todos_root / "todos" / key.slug / "requirements.md")
        impl_plan = _read_file_safe(todos_root / "todos" / key.slug / "implementation-plan.md")
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
    """COMMITTED: delivery bookkeeping (roadmap deliver, demo), stage, commit."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "COMMITTED phase has no candidate key")

    checkpoint.phase = IntegrationPhase.DELIVERY_BOOKKEEPING.value
    _write_checkpoint(checkpoint_path, checkpoint)

    is_bug = _is_bug_slug(cwd, key.slug)
    if not is_bug:
        result = subprocess.run(
            ["telec", "roadmap", "deliver", key.slug],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        if result.returncode != 0:
            logger.warning("telec roadmap deliver %s failed: %s", key.slug, result.stderr.strip())

    demo_path = Path(cwd) / "todos" / key.slug / "demo.md"
    if demo_path.exists():
        result = subprocess.run(
            ["telec", "todo", "demo", "create", key.slug],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        if result.returncode != 0:
            logger.warning("telec todo demo create %s failed: %s", key.slug, result.stderr.strip())

    # Stage and commit delivery files if anything changed
    _run_git(["add", "-A"], cwd=cwd)
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

    return True, ""  # loop into DELIVERY_BOOKKEEPING → push


def _step_delivery_bookkeeping(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """DELIVERY_BOOKKEEPING: push main to origin."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "DELIVERY_BOOKKEEPING phase has no candidate key")

    rc, stdout, stderr = _run_git(["push", "origin", "main"], cwd=cwd)
    if rc == 0:
        head_sha = _get_head_sha(cwd)
        checkpoint.phase = IntegrationPhase.PUSH_SUCCEEDED.value
        _write_checkpoint(checkpoint_path, checkpoint)
        _emit_lifecycle_event("integration.push.succeeded", {"slug": key.slug, "commit_sha": head_sha or "unknown"})
        logger.info("%s slug=%s phase=PUSH_SUCCEEDED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return True, ""  # loop into PUSH_SUCCEEDED
    else:
        rejection = (stderr or stdout).strip()
        checkpoint.phase = IntegrationPhase.PUSH_REJECTED.value
        checkpoint.error_context = {**(checkpoint.error_context or {}), "rejection_reason": rejection}
        _write_checkpoint(checkpoint_path, checkpoint)
        _emit_lifecycle_event("integration.push.rejected", {"slug": key.slug, "rejection_reason": rejection})
        logger.info("%s slug=%s phase=PUSH_REJECTED", _NEXT_INTEGRATE_PHASE_LOG, key.slug)
        return False, _format_push_rejected(rejection, key.slug)


def _step_push_rejected(
    *,
    checkpoint: IntegrationCheckpoint,
    checkpoint_path: Path,
    cwd: str,
) -> tuple[bool, str]:
    """PUSH_REJECTED: check if agent recovered (local main == remote main)."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "PUSH_REJECTED phase has no candidate key")

    local_head = _get_head_sha(cwd)
    remote_head = _get_remote_main_sha(cwd)
    if local_head and remote_head and local_head == remote_head:
        # Recovery detected
        checkpoint.phase = IntegrationPhase.PUSH_SUCCEEDED.value
        _write_checkpoint(checkpoint_path, checkpoint)
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
    """PUSH_SUCCEEDED: cleanup worktree, branch, todo dir; restart daemon."""
    key = _get_candidate_key(checkpoint)
    if not key:
        return False, _format_error("INVALID_STATE", "PUSH_SUCCEEDED phase has no candidate key")

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
    merge_commit = _get_head_sha(cwd) or "unknown"

    # Remove worktree
    worktree_path = Path(cwd) / "trees" / key.slug
    if worktree_path.exists():
        rc, _, stderr = _run_git(["worktree", "remove", "--force", str(worktree_path)], cwd=cwd)
        if rc != 0:
            logger.warning("worktree remove failed for %s: %s", key.slug, stderr.strip())

    # Delete local branch
    _run_git(["branch", "-D", key.branch], cwd=cwd)

    # Delete remote branch (non-fatal)
    _run_git(["push", "origin", "--delete", key.branch], cwd=cwd)

    # Remove todo directory
    todo_dir = Path(cwd) / "todos" / key.slug
    if todo_dir.exists():
        shutil.rmtree(str(todo_dir), ignore_errors=True)

    # Stage and commit cleanup
    _run_git(["add", "-A"], cwd=cwd)
    rc, _, _ = _run_git(["diff", "--cached", "--quiet"], cwd=cwd)
    if rc != 0:
        _run_git(
            [
                "commit",
                "-m",
                (
                    f"chore({key.slug}): worktree and todo cleanup after delivery\n\n"
                    "🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)\n\n"
                    "Co-Authored-By: TeleClaude <noreply@instrukt.ai>"
                ),
            ],
            cwd=cwd,
        )

    _emit_lifecycle_event(
        "integration.candidate.delivered",
        {"slug": key.slug, "branch": key.branch, "merge_commit_sha": merge_commit},
    )

    # Restart daemon (non-fatal)
    subprocess.run(["make", "restart"], capture_output=True, text=True, cwd=cwd)

    # Mark integrated and advance checkpoint
    try:
        queue.mark_integrated(key=key, reason="integrated via state machine")
    except Exception as exc:
        logger.warning("mark_integrated failed for %s: %s", key.slug, exc)

    checkpoint.phase = IntegrationPhase.CANDIDATE_DELIVERED.value
    checkpoint.items_processed += 1
    _write_checkpoint(checkpoint_path, checkpoint)
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


# ---------------------------------------------------------------------------
# Public async entry point
# ---------------------------------------------------------------------------


async def next_integrate(
    db: Db,  # noqa: ARG001  # pylint: disable=unused-argument — reserved for future DB-backed state
    slug: str | None,
    cwd: str,
    caller_session_id: str | None = None,
) -> str:
    """Integration state machine entry point.

    Reads current state from a durable checkpoint, executes the next
    deterministic step, and returns structured instructions at decision
    points where agent intelligence is required.

    Args:
        db: Database instance (reserved for future use).
        slug: Optional slug filter — must match next candidate in FIFO queue.
        cwd: Project root directory for git operations.
        caller_session_id: Session ID of the calling agent (lease owner).

    Returns:
        Plain text instruction block for the agent to execute.
    """
    session_id = caller_session_id or os.environ.get("TELECLAUDE_SESSION_ID", "unknown")
    started = perf_counter()
    state_dir = _default_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()

    return await asyncio.to_thread(
        _dispatch_sync,
        session_id=session_id,
        slug=slug,
        cwd=cwd,
        state_dir=state_dir,
        started=started,
        loop=loop,
    )
