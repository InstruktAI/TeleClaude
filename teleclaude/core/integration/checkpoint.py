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

from teleclaude.core.integration.queue import default_integration_state_dir

logger = get_logger(__name__)

_CHECKPOINT_VERSION = 1


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
    return default_integration_state_dir()


__all__ = [
    "_CHECKPOINT_VERSION",
    "IntegrationCheckpoint",
    "IntegrationPhase",
    "_CheckpointPayload",
    "_default_state_dir",
    "_now_iso",
    "_read_checkpoint",
    "_write_checkpoint",
]
