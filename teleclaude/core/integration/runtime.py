"""Shadow-mode integration runtime for lease, queue, and clearance processing."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal, TypedDict

from teleclaude.core.integration.authorization import (
    CutoverResolution,
    IntegrationAuthorizationError,
    IntegratorCutoverControls,
    require_integrator_owner,
    resolve_cutover_mode,
)
from teleclaude.core.integration.events import IntegrationBlockedPayload, build_integration_event
from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.queue import IntegrationQueue
from teleclaude.core.integration.readiness_projection import CandidateKey, CandidateReadiness

ReadinessLookup = Callable[[CandidateKey], CandidateReadiness | None]
SessionsProvider = Callable[[], tuple["SessionSnapshot", ...]]
SessionTailProvider = Callable[[str], str]
DirtyTrackedPathsProvider = Callable[[], tuple[str, ...]]
HousekeepingCommitter = Callable[[tuple[str, ...]], bool]
OutcomeSink = Callable[["ShadowOutcome"], None]
BlockedOutcomeSink = Callable[["IntegrationBlockedOutcome"], None]
BlockedFollowUpLinker = Callable[["IntegrationBlockedOutcome"], str | None]
FollowUpCandidateLookup = Callable[[str], CandidateKey | None]
FollowUpResolutionChecker = Callable[[str], bool]
ClockFn = Callable[[], datetime]
SleepFn = Callable[[float], None]
CanonicalMainPusher = Callable[[CandidateReadiness], None]
IntegratorOwnerPredicate = Callable[[str], bool]

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
    blocked: IntegrationBlockedOutcome | None = None


@dataclass(frozen=True)
class IntegrationBlockedOutcome:
    """Structured blocked-outcome payload with durable evidence fields."""

    event_type: Literal["integration_blocked"]
    slug: str
    branch: str
    sha: str
    conflict_evidence: tuple[str, ...]
    diagnostics: tuple[str, ...]
    next_action: str
    blocked_at: str
    follow_up_slug: str


@dataclass(frozen=True)
class ResumeBlockedResult:
    """Result of one blocked-candidate resume attempt."""

    resumed: bool
    key: CandidateKey | None
    reason: str | None


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

    def check(self, *, exclude_session_id: str | None = None) -> MainBranchClearanceCheck:
        """Return standalone blockers and dirty tracked paths."""
        sessions = self._sessions_provider()
        standalone = classify_standalone_sessions(sessions, exclude_session_id=exclude_session_id)

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


def classify_standalone_sessions(
    sessions: tuple[SessionSnapshot, ...],
    *,
    exclude_session_id: str | None = None,
) -> tuple[SessionSnapshot, ...]:
    """Exclude workers and orchestrators; return standalone main-session candidates."""
    orchestrator_ids = {item.initiator_session_id for item in sessions if item.initiator_session_id is not None}
    standalone = [
        item
        for item in sessions
        if item.initiator_session_id is None
        and item.session_id not in orchestrator_ids
        and item.session_id != exclude_session_id
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
    last_follow_up_slug: str | None
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
        cutover_controls: IntegratorCutoverControls | None = None,
        is_integrator_owner: IntegratorOwnerPredicate | None = None,
        blocked_outcome_sink: BlockedOutcomeSink | None = None,
        blocked_follow_up_linker: BlockedFollowUpLinker | None = None,
        follow_up_candidate_lookup: FollowUpCandidateLookup | None = None,
        follow_up_resolution_checker: FollowUpResolutionChecker | None = None,
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
        self._is_integrator_owner = is_integrator_owner if is_integrator_owner is not None else _default_is_integrator
        self._blocked_outcome_sink = blocked_outcome_sink
        self._blocked_follow_up_linker = blocked_follow_up_linker
        self._follow_up_candidate_lookup = follow_up_candidate_lookup
        self._follow_up_resolution_checker = follow_up_resolution_checker

        self._cutover_resolution: CutoverResolution | None = None
        effective_shadow_mode = shadow_mode
        if cutover_controls is not None:
            self._cutover_resolution = resolve_cutover_mode(
                requested_shadow_mode=shadow_mode,
                controls=cutover_controls,
            )
            effective_shadow_mode = self._cutover_resolution.shadow_mode

        if not effective_shadow_mode and canonical_main_pusher is None:
            raise ValueError("canonical_main_pusher is required when shadow_mode=False")
        self._shadow_mode = effective_shadow_mode
        self._canonical_main_pusher = canonical_main_pusher

    def resume_from_follow_up(self, *, owner_session_id: str, follow_up_slug: str) -> ResumeBlockedResult:
        """Resume a blocked candidate linked to a follow-up slug."""
        if self._follow_up_candidate_lookup is None:
            raise IntegrationRuntimeError("follow_up_candidate_lookup is required for resume_from_follow_up")

        normalized_slug = follow_up_slug.strip()
        if not normalized_slug:
            return ResumeBlockedResult(resumed=False, key=None, reason="follow_up_slug must be a non-empty string")

        key = self._follow_up_candidate_lookup(normalized_slug)
        if key is None:
            return ResumeBlockedResult(
                resumed=False,
                key=None,
                reason=f"no blocked candidate linked to follow-up '{normalized_slug}'",
            )
        if self._follow_up_resolution_checker is not None and not self._follow_up_resolution_checker(normalized_slug):
            return ResumeBlockedResult(
                resumed=False,
                key=key,
                reason=f"follow-up '{normalized_slug}' is not resolved",
            )
        return self.resume_blocked_candidate(owner_session_id=owner_session_id, key=key)

    def resume_blocked_candidate(self, *, owner_session_id: str, key: CandidateKey) -> ResumeBlockedResult:
        """Re-queue one blocked candidate only after readiness re-check under lease."""
        acquire_result = self._lease_store.acquire(
            key=self._lease_key,
            owner_session_id=owner_session_id,
            ttl_seconds=self._lease_ttl_seconds,
            now=self._clock(),
        )
        if acquire_result.status != "acquired" or acquire_result.lease is None:
            self._write_checkpoint(owner_session_id=owner_session_id, outcome=None)
            return ResumeBlockedResult(
                resumed=False, key=key, reason="integration lease is currently held by another owner"
            )

        lease_token = acquire_result.lease.lease_token
        try:
            self._renew_or_raise(owner_session_id=owner_session_id, lease_token=lease_token)
            self._wait_for_main_clearance(owner_session_id=owner_session_id, lease_token=lease_token)
            item = self._queue.get(key=key)
            if item is None:
                return ResumeBlockedResult(
                    resumed=False, key=key, reason="candidate is not present in the integration queue"
                )
            if item.status != "blocked":
                return ResumeBlockedResult(
                    resumed=False,
                    key=key,
                    reason=f"candidate status must be 'blocked' to resume (current={item.status})",
                )

            readiness = self._readiness_lookup(key)
            if readiness is None:
                return ResumeBlockedResult(
                    resumed=False,
                    key=key,
                    reason="candidate no longer exists in readiness projection",
                )
            if readiness.status != "READY":
                if readiness.reasons:
                    reason = "; ".join(readiness.reasons)
                else:
                    reason = "candidate failed readiness recheck"
                return ResumeBlockedResult(resumed=False, key=key, reason=reason)

            self._queue.resume_blocked(
                key=key,
                reason="resume requested after follow-up remediation and readiness recheck",
                now=self._clock(),
            )
            self._write_checkpoint(owner_session_id=owner_session_id, outcome=None)
            return ResumeBlockedResult(resumed=True, key=key, reason=None)
        finally:
            self._lease_store.release(
                key=self._lease_key,
                owner_session_id=owner_session_id,
                lease_token=lease_token,
            )

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
            if not self._shadow_mode:
                try:
                    require_integrator_owner(
                        owner_session_id=owner_session_id,
                        is_integrator_owner=self._is_integrator_owner,
                        action="canonical-main integration",
                    )
                except IntegrationAuthorizationError as exc:
                    raise IntegrationRuntimeError(str(exc)) from exc

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
            blocked = self._emit_blocked_outcome(key=key, reasons=(reason,), blocked_at=now_iso)
            return ShadowOutcome(outcome="would_block", key=key, emitted_at=now_iso, reasons=(reason,), blocked=blocked)

        if readiness.status == "SUPERSEDED":
            reason = "candidate superseded by newer finalize_ready"
            self._queue.mark_superseded(key=key, reason=reason, now=self._clock())
            blocked = self._emit_blocked_outcome(key=key, reasons=(reason,), blocked_at=now_iso)
            return ShadowOutcome(outcome="would_block", key=key, emitted_at=now_iso, reasons=(reason,), blocked=blocked)

        if readiness.status != "READY":
            reason = "; ".join(readiness.reasons) if readiness.reasons else "candidate failed readiness recheck"
            self._queue.mark_blocked(key=key, reason=reason, now=self._clock())
            resolved_reasons = readiness.reasons if readiness.reasons else (reason,)
            blocked = self._emit_blocked_outcome(key=key, reasons=resolved_reasons, blocked_at=now_iso)
            return ShadowOutcome(
                outcome="would_block",
                key=key,
                emitted_at=now_iso,
                reasons=resolved_reasons,
                blocked=blocked,
            )

        if not self._shadow_mode and self._canonical_main_pusher is not None:
            self._canonical_main_pusher(readiness)

        self._queue.mark_integrated(key=key, now=self._clock())
        return ShadowOutcome(outcome="would_integrate", key=key, emitted_at=now_iso, reasons=())

    def _emit_blocked_outcome(
        self, *, key: CandidateKey, reasons: tuple[str, ...], blocked_at: str
    ) -> IntegrationBlockedOutcome:
        conflict_evidence = _derive_conflict_evidence(reasons)
        next_action = _derive_next_action(reasons)
        blocked = IntegrationBlockedOutcome(
            event_type="integration_blocked",
            slug=key.slug,
            branch=key.branch,
            sha=key.sha,
            conflict_evidence=conflict_evidence,
            diagnostics=reasons,
            next_action=next_action,
            blocked_at=blocked_at,
            follow_up_slug="",
        )
        if self._blocked_follow_up_linker is not None:
            linked_slug = self._blocked_follow_up_linker(blocked)
            if linked_slug is not None:
                normalized_linked_slug = linked_slug.strip()
                if normalized_linked_slug:
                    blocked = replace(blocked, follow_up_slug=normalized_linked_slug)

        event_payload: IntegrationBlockedPayload = {
            "slug": blocked.slug,
            "branch": blocked.branch,
            "sha": blocked.sha,
            "conflict_evidence": list(blocked.conflict_evidence),
            "diagnostics": list(blocked.diagnostics),
            "next_action": blocked.next_action,
            "blocked_at": blocked.blocked_at,
        }
        if blocked.follow_up_slug:
            event_payload["follow_up_slug"] = blocked.follow_up_slug
        build_integration_event("integration_blocked", event_payload)

        if self._blocked_outcome_sink is not None:
            self._blocked_outcome_sink(blocked)
        return blocked

    def _wait_for_main_clearance(self, *, owner_session_id: str, lease_token: str) -> None:
        while True:
            self._renew_or_raise(owner_session_id=owner_session_id, lease_token=lease_token)
            clearance = self._clearance_probe.check(exclude_session_id=owner_session_id)

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

                post_commit = self._clearance_probe.check(exclude_session_id=owner_session_id)
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
            "last_follow_up_slug": (
                outcome.blocked.follow_up_slug if outcome is not None and outcome.blocked is not None else None
            ),
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


def _derive_conflict_evidence(reasons: tuple[str, ...]) -> tuple[str, ...]:
    evidence = [reason for reason in reasons if "conflict" in reason.lower()]
    if evidence:
        return tuple(evidence)
    return ("no merge-conflict evidence captured; blocked before merge apply",)


def _derive_next_action(reasons: tuple[str, ...]) -> str:
    lowered = " ".join(reasons).lower()
    if "conflict" in lowered:
        return "Resolve merge conflicts on the candidate branch, push the fix, then resume integration."
    if "superseded" in lowered:
        return "Evaluate the newer candidate and re-queue this candidate only if it is still needed."
    if "no longer exists" in lowered:
        return "Re-create readiness evidence for this candidate before attempting resume."
    return "Resolve readiness diagnostics, confirm the follow-up is complete, then resume integration."


def _default_is_integrator(owner_session_id: str) -> bool:
    return owner_session_id.startswith("integrator-")
