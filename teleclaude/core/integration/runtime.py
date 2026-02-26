"""Shadow-mode integration runtime for lease, queue, and clearance processing."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal, TypedDict

from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.queue import IntegrationQueue
from teleclaude.core.integration.readiness_projection import CandidateKey, CandidateReadiness

ReadinessLookup = Callable[[CandidateKey], CandidateReadiness | None]
SessionsProvider = Callable[[], tuple["SessionSnapshot", ...]]
SessionTailProvider = Callable[[str], str]
DirtyTrackedPathsProvider = Callable[[], tuple[str, ...]]
HousekeepingCommitter = Callable[[tuple[str, ...]], bool]
OutcomeSink = Callable[["ShadowOutcome"], None]
ClockFn = Callable[[], datetime]
SleepFn = Callable[[float], None]
CanonicalMainPusher = Callable[[CandidateReadiness], None]

ShadowOutcomeType = Literal["would_integrate", "would_block"]

_IDLE_TOKENS: tuple[str, ...] = (
    "idle",
    "stale",
    "waiting for input",
    "no new input",
    "no new output",
    "stand by",
)
_MAIN_ACTIVITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgit\s+(switch|checkout)\s+main\b"),
    re.compile(r"\bgit\s+pull\b[^\n]*\bmain\b"),
    re.compile(r"\bgit\s+merge\b[^\n]*\bmain\b"),
    re.compile(r"\bgit\s+rebase\b[^\n]*\bmain\b"),
    re.compile(r"\bgit\s+commit\b"),
    re.compile(r"\bon\s+branch\s+main\b"),
    re.compile(r"\brefs/heads/main\b"),
)


class IntegrationRuntimeError(RuntimeError):
    """Raised when runtime invariants are violated."""


@dataclass(frozen=True)
class SessionSnapshot:
    """Minimal session metadata for main-branch clearance heuristics."""

    session_id: str
    initiator_session_id: str | None


@dataclass(frozen=True)
class MainBranchClearanceCheck:
    """Result of one branch-clearance probe cycle."""

    standalone_session_ids: tuple[str, ...]
    blocking_session_ids: tuple[str, ...]
    dirty_tracked_paths: tuple[str, ...]

    @property
    def cleared(self) -> bool:
        """True when no session blockers and no dirty tracked files remain."""
        return not self.blocking_session_ids and not self.dirty_tracked_paths


@dataclass(frozen=True)
class ShadowOutcome:
    """Recorded outcome for one shadow-mode integration attempt."""

    outcome: ShadowOutcomeType
    key: CandidateKey
    emitted_at: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeDrainResult:
    """Result summary for one runtime drain invocation."""

    outcomes: tuple[ShadowOutcome, ...]
    lease_acquired: bool


class MainBranchClearanceProbe:
    """Evaluate whether canonical main is currently safe to process."""

    def __init__(
        self,
        *,
        sessions_provider: SessionsProvider,
        session_tail_provider: SessionTailProvider,
        dirty_tracked_paths_provider: DirtyTrackedPathsProvider,
    ) -> None:
        self._sessions_provider = sessions_provider
        self._session_tail_provider = session_tail_provider
        self._dirty_tracked_paths_provider = dirty_tracked_paths_provider

    def check(self) -> MainBranchClearanceCheck:
        """Return standalone blockers and dirty tracked paths."""
        sessions = self._sessions_provider()
        standalone = classify_standalone_sessions(sessions)

        blockers: list[str] = []
        for session in standalone:
            tail_output = self._session_tail_provider(session.session_id)
            if tail_indicates_active_main_modification(tail_output):
                blockers.append(session.session_id)

        dirty_paths = tuple(sorted(self._dirty_tracked_paths_provider()))
        return MainBranchClearanceCheck(
            standalone_session_ids=tuple(session.session_id for session in standalone),
            blocking_session_ids=tuple(sorted(blockers)),
            dirty_tracked_paths=dirty_paths,
        )


def classify_standalone_sessions(sessions: tuple[SessionSnapshot, ...]) -> tuple[SessionSnapshot, ...]:
    """Exclude workers and orchestrators; return standalone main-session candidates."""
    orchestrator_ids = {item.initiator_session_id for item in sessions if item.initiator_session_id is not None}
    standalone = [
        item for item in sessions if item.initiator_session_id is None and item.session_id not in orchestrator_ids
    ]
    standalone.sort(key=lambda item: item.session_id)
    return tuple(standalone)


def tail_indicates_active_main_modification(tail_output: str) -> bool:
    """Heuristic: detect recent output showing active work against canonical main."""
    normalized = tail_output.strip().lower()
    if not normalized:
        return False
    if any(token in normalized for token in _IDLE_TOKENS):
        return False
    if "main" not in normalized:
        return False
    return any(pattern.search(normalized) is not None for pattern in _MAIN_ACTIVITY_PATTERNS)


class _RuntimeCheckpointPayload(TypedDict):
    version: int
    owner_session_id: str
    last_outcome: ShadowOutcomeType | None
    last_slug: str | None
    last_branch: str | None
    last_sha: str | None
    updated_at: str


class IntegratorShadowRuntime:
    """Drain READY candidates under a singleton lease in shadow mode."""

    def __init__(
        self,
        *,
        lease_store: IntegrationLeaseStore,
        queue: IntegrationQueue,
        readiness_lookup: ReadinessLookup,
        clearance_probe: MainBranchClearanceProbe,
        outcome_sink: OutcomeSink,
        checkpoint_path: Path,
        lease_key: str = "integration/main",
        lease_ttl_seconds: int = 120,
        clearance_retry_seconds: float = 60.0,
        housekeeping_committer: HousekeepingCommitter | None = None,
        clock: ClockFn | None = None,
        sleep_fn: SleepFn | None = None,
        shadow_mode: bool = True,
        canonical_main_pusher: CanonicalMainPusher | None = None,
    ) -> None:
        self._lease_store = lease_store
        self._queue = queue
        self._readiness_lookup = readiness_lookup
        self._clearance_probe = clearance_probe
        self._outcome_sink = outcome_sink
        self._checkpoint_path = checkpoint_path
        self._lease_key = lease_key
        self._lease_ttl_seconds = lease_ttl_seconds
        self._clearance_retry_seconds = clearance_retry_seconds
        self._housekeeping_committer = housekeeping_committer
        self._clock = clock if clock is not None else lambda: datetime.now(tz=UTC)
        self._sleep_fn = sleep_fn if sleep_fn is not None else time.sleep
        self._shadow_mode = shadow_mode
        self._canonical_main_pusher = canonical_main_pusher

    def enqueue_ready_candidates(self, candidates: tuple[CandidateReadiness, ...]) -> None:
        """Enqueue READY candidates by their declared `ready_at` timestamp."""
        for candidate in candidates:
            if candidate.status != "READY":
                continue
            self._queue.enqueue(key=candidate.key, ready_at=candidate.ready_at, now=self._clock())

    def drain_ready_candidates(self, *, owner_session_id: str, max_items: int | None = None) -> RuntimeDrainResult:
        """Acquire lease, process queue serially, and release lease on shutdown."""
        acquire_result = self._lease_store.acquire(
            key=self._lease_key,
            owner_session_id=owner_session_id,
            ttl_seconds=self._lease_ttl_seconds,
            now=self._clock(),
        )
        if acquire_result.status != "acquired" or acquire_result.lease is None:
            self._write_checkpoint(owner_session_id=owner_session_id, outcome=None)
            return RuntimeDrainResult(outcomes=(), lease_acquired=False)

        lease_token = acquire_result.lease.lease_token
        outcomes: list[ShadowOutcome] = []

        try:
            processed = 0
            while True:
                if max_items is not None and processed >= max_items:
                    break
                self._renew_or_raise(owner_session_id=owner_session_id, lease_token=lease_token)
                self._wait_for_main_clearance(owner_session_id=owner_session_id, lease_token=lease_token)

                item = self._queue.pop_next(now=self._clock())
                if item is None:
                    break

                readiness = self._readiness_lookup(item.key)
                outcome = self._apply_candidate(item.key, readiness)
                outcomes.append(outcome)
                self._outcome_sink(outcome)
                self._write_checkpoint(owner_session_id=owner_session_id, outcome=outcome)
                processed += 1
        finally:
            self._lease_store.release(
                key=self._lease_key,
                owner_session_id=owner_session_id,
                lease_token=lease_token,
            )
            self._write_checkpoint(owner_session_id=owner_session_id, outcome=outcomes[-1] if outcomes else None)

        return RuntimeDrainResult(outcomes=tuple(outcomes), lease_acquired=True)

    def _apply_candidate(self, key: CandidateKey, readiness: CandidateReadiness | None) -> ShadowOutcome:
        now_iso = _format_timestamp(self._clock())

        if readiness is None:
            reason = "candidate no longer exists in readiness projection"
            self._queue.mark_blocked(key=key, reason=reason, now=self._clock())
            return ShadowOutcome(outcome="would_block", key=key, emitted_at=now_iso, reasons=(reason,))

        if readiness.status == "SUPERSEDED":
            reason = "candidate superseded by newer finalize_ready"
            self._queue.mark_superseded(key=key, reason=reason, now=self._clock())
            return ShadowOutcome(outcome="would_block", key=key, emitted_at=now_iso, reasons=(reason,))

        if readiness.status != "READY":
            reason = "; ".join(readiness.reasons) if readiness.reasons else "candidate failed readiness recheck"
            self._queue.mark_blocked(key=key, reason=reason, now=self._clock())
            return ShadowOutcome(outcome="would_block", key=key, emitted_at=now_iso, reasons=readiness.reasons)

        if not self._shadow_mode and self._canonical_main_pusher is not None:
            self._canonical_main_pusher(readiness)

        self._queue.mark_integrated(key=key, now=self._clock())
        return ShadowOutcome(outcome="would_integrate", key=key, emitted_at=now_iso, reasons=())

    def _wait_for_main_clearance(self, *, owner_session_id: str, lease_token: str) -> None:
        while True:
            self._renew_or_raise(owner_session_id=owner_session_id, lease_token=lease_token)
            clearance = self._clearance_probe.check()

            if clearance.blocking_session_ids:
                self._sleep_fn(self._clearance_retry_seconds)
                continue

            if clearance.dirty_tracked_paths:
                committed = False
                if self._housekeeping_committer is not None:
                    committed = self._housekeeping_committer(clearance.dirty_tracked_paths)

                if not committed:
                    self._sleep_fn(self._clearance_retry_seconds)
                    continue

                post_commit = self._clearance_probe.check()
                if not post_commit.cleared:
                    self._sleep_fn(self._clearance_retry_seconds)
                    continue

            return

    def _renew_or_raise(self, *, owner_session_id: str, lease_token: str) -> None:
        renewed = self._lease_store.renew(
            key=self._lease_key,
            owner_session_id=owner_session_id,
            lease_token=lease_token,
            ttl_seconds=self._lease_ttl_seconds,
            now=self._clock(),
        )
        if renewed.status != "renewed":
            raise IntegrationRuntimeError(f"lost integration lease during runtime: status={renewed.status}")

    def _write_checkpoint(self, *, owner_session_id: str, outcome: ShadowOutcome | None) -> None:
        payload: _RuntimeCheckpointPayload = {
            "version": 1,
            "owner_session_id": owner_session_id,
            "last_outcome": outcome.outcome if outcome is not None else None,
            "last_slug": outcome.key.slug if outcome is not None else None,
            "last_branch": outcome.key.branch if outcome is not None else None,
            "last_sha": outcome.key.sha if outcome is not None else None,
            "updated_at": _format_timestamp(self._clock()),
        }
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
        temp_path = self._checkpoint_path.with_suffix(f"{self._checkpoint_path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as file_handle:
            file_handle.write(serialized)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temp_path, self._checkpoint_path)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")
