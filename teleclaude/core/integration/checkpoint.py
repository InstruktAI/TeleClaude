"""Integration checkpoint — phase enum, durable checkpoint I/O, and state paths.

No imports from state_machine.py (circular-import guard).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.project_root import resolve_project_root

logger = get_logger(__name__)

_CHECKPOINT_VERSION_V1 = 1
_CHECKPOINT_VERSION = 2
_CHECKPOINT_VERSION_FIELD = "version"
_CHECKPOINT_PARKED_FIELD = "parked"
_UNSUPPORTED_CHECKPOINT_VERSION = "Unsupported integration checkpoint version: {version}"

# A legacy persisted checkpoint phase value. Normalized to CONTENT_GATE_BLOCKED
# before checkpoint data reaches the dispatcher, so a durably persisted
# candidate stays owned by the content-gate conflict path.
_LEGACY_CANDIDATE_ABANDONED_PHASE = "candidate_abandoned"


# ---------------------------------------------------------------------------
# Phase enum and checkpoint
# ---------------------------------------------------------------------------


class IntegrationPhase(str, Enum):
    """All valid integration lifecycle phases."""

    IDLE = "idle"
    CANDIDATE_DEQUEUED = "candidate_dequeued"
    MERGE_CLEAN = "merge_clean"
    MERGE_CONFLICTED = "merge_conflicted"
    AWAITING_COMMIT = "awaiting_commit"
    COMMITTED = "committed"
    DELIVERY_BOOKKEEPING = "delivery_bookkeeping"
    PUSH_SUCCEEDED = "push_succeeded"
    PUSH_REJECTED = "push_rejected"
    CONTENT_GATE_BLOCKED = "content_gate_blocked"
    CLEANUP = "cleanup"
    CANDIDATE_DELIVERED = "candidate_delivered"
    COMPLETED = "completed"


class ParkedCandidate(TypedDict):
    """A candidate set aside for the duration of one integration drain."""

    slug: str
    branch: str
    sha: str
    reason: str
    parked_at: str


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
    # Commit SHA actually pushed to origin/main, frozen at push time — the
    # delivery-confirmation gate's ref-check handle
    pushed_sha: str | None
    parked: list[ParkedCandidate]
    # Non-fatal anomalies accumulated during integration (surfaced to agents)
    warnings: list[str] | None = None


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
    pushed_sha: str | None
    parked: list[ParkedCandidate]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Checkpoint I/O
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


# guard: loose-dict-func - versioned JSON boundary is upcast before typed domain construction
def _upcast_checkpoint_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Return current-shape checkpoint data after ordered version migrations."""
    migrated = dict(data)
    version = int(migrated.get(_CHECKPOINT_VERSION_FIELD, _CHECKPOINT_VERSION_V1))
    if version == _CHECKPOINT_VERSION_V1:
        migrated[_CHECKPOINT_PARKED_FIELD] = []
        migrated[_CHECKPOINT_VERSION_FIELD] = _CHECKPOINT_VERSION
        version = _CHECKPOINT_VERSION
    if version != _CHECKPOINT_VERSION:
        raise ValueError(_UNSUPPORTED_CHECKPOINT_VERSION.format(version=version))
    return migrated


def _reset_candidate(checkpoint: IntegrationCheckpoint) -> None:
    """Reset candidate-owned fields and return the checkpoint to IDLE."""
    checkpoint.phase = IntegrationPhase.IDLE.value
    checkpoint.candidate_slug = None
    checkpoint.candidate_branch = None
    checkpoint.candidate_sha = None
    checkpoint.lease_token = None
    checkpoint.pre_merge_head = None
    checkpoint.pushed_sha = None
    checkpoint.error_context = None


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
        pushed_sha=None,
        parked=[],
        warnings=[],
    )
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return default
        raw_data: dict[str, Any] = json.loads(raw)  # guard: loose-dict - JSON boundary, upcast before domain use
        data = _upcast_checkpoint_payload(raw_data)
        phase = data.get("phase", IntegrationPhase.IDLE.value)
        if phase == _LEGACY_CANDIDATE_ABANDONED_PHASE:
            phase = IntegrationPhase.CONTENT_GATE_BLOCKED.value
        return IntegrationCheckpoint(
            phase=phase,
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
            pushed_sha=data.get("pushed_sha"),
            parked=list(data[_CHECKPOINT_PARKED_FIELD]),
            warnings=list(data.get("warnings", [])),
        )
    except (OSError, TypeError, ValueError):
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
        "pushed_sha": checkpoint.pushed_sha,
        "parked": checkpoint.parked,
        "warnings": checkpoint.warnings or [],
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


def _default_state_dir(cwd: str | Path) -> Path:
    return resolve_project_root(cwd) / ".teleclaude" / "integration"


__all__ = [
    "_CHECKPOINT_VERSION",
    "IntegrationCheckpoint",
    "IntegrationPhase",
    "ParkedCandidate",
    "_CheckpointPayload",
    "_default_state_dir",
    "_now_iso",
    "_read_checkpoint",
    "_reset_candidate",
    "_write_checkpoint",
]
