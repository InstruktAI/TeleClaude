"""Unit tests for singleton lease and shadow integrator primitives."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock, Thread

import pytest

from teleclaude.core.integration.lease import IntegrationLeaseStore, LeaseRenewResult
from teleclaude.core.integration.queue import IntegrationQueue, IntegrationQueueError
from teleclaude.core.integration.readiness_projection import CandidateKey, CandidateReadiness
from teleclaude.core.integration.runtime import (
    IntegrationRuntimeError,
    IntegratorShadowRuntime,
    MainBranchClearanceProbe,
    SessionSnapshot,
)


def test_lease_acquire_is_single_holder_under_concurrency(tmp_path: Path) -> None:
    store = IntegrationLeaseStore(state_path=tmp_path / "integration-lease.json")
    key = "integration/main"
    now = datetime(2026, 2, 26, 12, 0, 0, tzinfo=UTC)

    barrier = Barrier(8)
    lock = Lock()
    statuses: list[str] = []

    def _attempt(owner: str) -> None:
        barrier.wait()
        result = store.acquire(key=key, owner_session_id=owner, ttl_seconds=120, now=now)
        with lock:
            statuses.append(result.status)

    threads = [Thread(target=_attempt, args=(f"session-{index}",)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert statuses.count("acquired") == 1
    assert statuses.count("busy") == 7


def test_stale_lease_can_be_replaced_after_ttl_expiry(tmp_path: Path) -> None:
    store = IntegrationLeaseStore(state_path=tmp_path / "integration-lease.json")
    key = "integration/main"
    acquired_at = datetime(2026, 2, 26, 12, 0, 0, tzinfo=UTC)

    first = store.acquire(
        key=key,
        owner_session_id="session-a",
        ttl_seconds=120,
        now=acquired_at,
    )
    assert first.status == "acquired"
    assert first.lease is not None

    busy = store.acquire(
        key=key,
        owner_session_id="session-b",
        ttl_seconds=120,
        now=acquired_at + timedelta(seconds=10),
    )
    assert busy.status == "busy"

    replacement = store.acquire(
        key=key,
        owner_session_id="session-b",
        ttl_seconds=120,
        now=acquired_at + timedelta(seconds=121),
    )
    assert replacement.status == "acquired"
    assert replacement.replaced_stale is True
    assert replacement.lease is not None

    stale_renew = store.renew(
        key=key,
        owner_session_id="session-a",
        lease_token=first.lease.lease_token,
        ttl_seconds=120,
        now=acquired_at + timedelta(seconds=122),
    )
    assert stale_renew.status == "stolen"

    renewed = store.renew(
        key=key,
        owner_session_id="session-b",
        lease_token=replacement.lease.lease_token,
        ttl_seconds=120,
        now=acquired_at + timedelta(seconds=180),
    )
    assert renewed.status == "renewed"
    assert renewed.lease is not None

    assert store.release(
        key=key,
        owner_session_id="session-b",
        lease_token=replacement.lease.lease_token,
    )


def test_queue_processes_candidates_fifo_by_ready_at_and_tracks_transitions(tmp_path: Path) -> None:
    queue = IntegrationQueue(state_path=tmp_path / "integration-queue.json")

    early_key = CandidateKey(slug="a", branch="worktree/a", sha="111")
    middle_key = CandidateKey(slug="b", branch="worktree/b", sha="222")
    late_key = CandidateKey(slug="c", branch="worktree/c", sha="333")

    queue.enqueue(key=late_key, ready_at="2026-02-26T12:03:00+00:00")
    queue.enqueue(key=early_key, ready_at="2026-02-26T12:01:00+00:00")
    queue.enqueue(key=middle_key, ready_at="2026-02-26T12:02:00+00:00")

    first = queue.pop_next()
    assert first is not None
    assert first.key == early_key
    queue.mark_integrated(key=early_key)

    second = queue.pop_next()
    assert second is not None
    assert second.key == middle_key
    queue.mark_blocked(key=middle_key, reason="readiness recheck failed")

    third = queue.pop_next()
    assert third is not None
    assert third.key == late_key
    queue.mark_integrated(key=late_key)

    assert queue.pop_next() is None

    transitions = queue.transitions()
    keyed_transitions = [(item.key.slug, item.from_status, item.to_status) for item in transitions]
    assert keyed_transitions[:3] == [
        ("c", None, "queued"),
        ("a", None, "queued"),
        ("b", None, "queued"),
    ]
    assert ("a", "queued", "in_progress") in keyed_transitions
    assert ("a", "in_progress", "integrated") in keyed_transitions
    assert ("b", "in_progress", "blocked") in keyed_transitions


def test_queue_rejects_invalid_status_transitions(tmp_path: Path) -> None:
    queue = IntegrationQueue(state_path=tmp_path / "integration-queue.json")
    key = CandidateKey(slug="invalid", branch="worktree/invalid", sha="444")
    queue.enqueue(key=key, ready_at="2026-02-26T12:01:00+00:00")

    with pytest.raises(IntegrationQueueError, match="invalid queue transition queued->integrated"):
        queue.mark_integrated(key=key)

    popped = queue.pop_next()
    assert popped is not None
    queue.mark_blocked(key=key, reason="failed readiness")

    with pytest.raises(IntegrationQueueError, match="invalid queue transition blocked->integrated"):
        queue.mark_integrated(key=key)


def test_shadow_runtime_rechecks_readiness_and_never_pushes_main_in_shadow_mode(tmp_path: Path) -> None:
    lease_store = IntegrationLeaseStore(state_path=tmp_path / "integration-lease.json")
    queue = IntegrationQueue(state_path=tmp_path / "integration-queue.json")

    integrate_key = CandidateKey(slug="integrate", branch="worktree/integrate", sha="aaa111")
    block_key = CandidateKey(slug="block", branch="worktree/block", sha="bbb222")
    queue.enqueue(key=integrate_key, ready_at="2026-02-26T12:01:00+00:00")
    queue.enqueue(key=block_key, ready_at="2026-02-26T12:02:00+00:00")

    readiness_map = {
        integrate_key: CandidateReadiness(
            key=integrate_key,
            ready_at="2026-02-26T12:01:00+00:00",
            status="READY",
            reasons=(),
            superseded_by=None,
        ),
        block_key: CandidateReadiness(
            key=block_key,
            ready_at="2026-02-26T12:02:00+00:00",
            status="NOT_READY",
            reasons=("branch is no longer reachable",),
            superseded_by=None,
        ),
    }

    clearance_probe = MainBranchClearanceProbe(
        sessions_provider=lambda: (),
        session_tail_provider=lambda _session_id: "",
        dirty_tracked_paths_provider=lambda: (),
    )

    outcomes = []
    push_calls = []
    runtime = IntegratorShadowRuntime(
        lease_store=lease_store,
        queue=queue,
        readiness_lookup=lambda key: readiness_map.get(key),
        clearance_probe=clearance_probe,
        outcome_sink=outcomes.append,
        checkpoint_path=tmp_path / "integration-checkpoint.json",
        canonical_main_pusher=push_calls.append,
        shadow_mode=True,
        clearance_retry_seconds=0.001,
    )

    result = runtime.drain_ready_candidates(owner_session_id="integrator-1")

    assert result.lease_acquired is True
    assert [outcome.outcome for outcome in result.outcomes] == ["would_integrate", "would_block"]
    assert push_calls == []
    assert queue.get(key=integrate_key) and queue.get(key=integrate_key).status == "integrated"
    assert queue.get(key=block_key) and queue.get(key=block_key).status == "blocked"


def test_shadow_runtime_requires_pusher_when_shadow_mode_disabled(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical_main_pusher is required when shadow_mode=False"):
        IntegratorShadowRuntime(
            lease_store=IntegrationLeaseStore(state_path=tmp_path / "integration-lease.json"),
            queue=IntegrationQueue(state_path=tmp_path / "integration-queue.json"),
            readiness_lookup=lambda _key: None,
            clearance_probe=MainBranchClearanceProbe(
                sessions_provider=lambda: (),
                session_tail_provider=lambda _session_id: "",
                dirty_tracked_paths_provider=lambda: (),
            ),
            outcome_sink=lambda _outcome: None,
            checkpoint_path=tmp_path / "integration-checkpoint.json",
            shadow_mode=False,
            canonical_main_pusher=None,
        )


def test_shadow_runtime_would_block_sets_fallback_reason_when_readiness_reasons_empty(tmp_path: Path) -> None:
    lease_store = IntegrationLeaseStore(state_path=tmp_path / "integration-lease.json")
    queue = IntegrationQueue(state_path=tmp_path / "integration-queue.json")
    key = CandidateKey(slug="block", branch="worktree/block", sha="bbb222")
    queue.enqueue(key=key, ready_at="2026-02-26T12:02:00+00:00")

    readiness = CandidateReadiness(
        key=key,
        ready_at="2026-02-26T12:02:00+00:00",
        status="NOT_READY",
        reasons=(),
        superseded_by=None,
    )

    outcomes = []
    runtime = IntegratorShadowRuntime(
        lease_store=lease_store,
        queue=queue,
        readiness_lookup=lambda _key: readiness,
        clearance_probe=MainBranchClearanceProbe(
            sessions_provider=lambda: (),
            session_tail_provider=lambda _session_id: "",
            dirty_tracked_paths_provider=lambda: (),
        ),
        outcome_sink=outcomes.append,
        checkpoint_path=tmp_path / "integration-checkpoint.json",
        clearance_retry_seconds=0.001,
    )

    result = runtime.drain_ready_candidates(owner_session_id="integrator-1")
    assert result.lease_acquired is True
    assert len(result.outcomes) == 1
    assert result.outcomes[0].outcome == "would_block"
    assert result.outcomes[0].reasons == ("candidate failed readiness recheck",)
    blocked = queue.get(key=key)
    assert blocked is not None
    assert blocked.status == "blocked"
    assert blocked.status_reason == "candidate failed readiness recheck"


def test_shadow_runtime_raises_when_lease_lost_during_drain(tmp_path: Path) -> None:
    class _LeaseStoreLosesRenewal(IntegrationLeaseStore):
        def __init__(self, *, state_path: Path) -> None:
            super().__init__(state_path=state_path)
            self._renew_calls = 0

        def renew(
            self,
            *,
            key: str,
            owner_session_id: str,
            lease_token: str,
            ttl_seconds: int | None = None,
            now: datetime | None = None,
        ) -> LeaseRenewResult:
            self._renew_calls += 1
            if self._renew_calls >= 2:
                return LeaseRenewResult(status="stolen", lease=None)
            return super().renew(
                key=key,
                owner_session_id=owner_session_id,
                lease_token=lease_token,
                ttl_seconds=ttl_seconds,
                now=now,
            )

    key = CandidateKey(slug="lease-loss", branch="worktree/lease-loss", sha="ccc333")
    queue = IntegrationQueue(state_path=tmp_path / "integration-queue.json")
    queue.enqueue(key=key, ready_at="2026-02-26T12:01:00+00:00")

    readiness = CandidateReadiness(
        key=key,
        ready_at="2026-02-26T12:01:00+00:00",
        status="READY",
        reasons=(),
        superseded_by=None,
    )

    runtime = IntegratorShadowRuntime(
        lease_store=_LeaseStoreLosesRenewal(state_path=tmp_path / "integration-lease.json"),
        queue=queue,
        readiness_lookup=lambda _key: readiness,
        clearance_probe=MainBranchClearanceProbe(
            sessions_provider=lambda: (),
            session_tail_provider=lambda _session_id: "",
            dirty_tracked_paths_provider=lambda: (),
        ),
        outcome_sink=lambda _outcome: None,
        checkpoint_path=tmp_path / "integration-checkpoint.json",
        clearance_retry_seconds=0.001,
    )

    with pytest.raises(IntegrationRuntimeError, match="lost integration lease during runtime: status=stolen"):
        runtime.drain_ready_candidates(owner_session_id="integrator-1")

    queued = queue.get(key=key)
    assert queued is not None
    assert queued.status == "queued"


def test_clearance_probe_excludes_orchestrator_worker_pairs_and_ignores_idle_standalone() -> None:
    sessions = (
        SessionSnapshot(session_id="orchestrator", initiator_session_id=None),
        SessionSnapshot(session_id="worker", initiator_session_id="orchestrator"),
        SessionSnapshot(session_id="standalone", initiator_session_id=None),
    )

    tails = {
        "orchestrator": "git switch main",
        "worker": "git switch main",
        "standalone": "idle - waiting for input",
    }

    probe = MainBranchClearanceProbe(
        sessions_provider=lambda: sessions,
        session_tail_provider=lambda session_id: tails[session_id],
        dirty_tracked_paths_provider=lambda: (),
    )

    check = probe.check()

    assert check.standalone_session_ids == ("standalone",)
    assert check.blocking_session_ids == ()


def test_clearance_probe_blocks_active_standalone_main_session() -> None:
    probe = MainBranchClearanceProbe(
        sessions_provider=lambda: (SessionSnapshot(session_id="solo", initiator_session_id=None),),
        session_tail_provider=lambda _session_id: "git switch main && git commit -m 'wip'",
        dirty_tracked_paths_provider=lambda: (),
    )

    check = probe.check()
    assert check.blocking_session_ids == ("solo",)


def test_clearance_probe_excludes_owner_session_from_standalone_blockers() -> None:
    probe = MainBranchClearanceProbe(
        sessions_provider=lambda: (
            SessionSnapshot(session_id="integrator-1", initiator_session_id=None),
            SessionSnapshot(session_id="solo", initiator_session_id=None),
        ),
        session_tail_provider=lambda _session_id: "git switch main && git commit -m 'wip'",
        dirty_tracked_paths_provider=lambda: (),
    )

    check = probe.check(exclude_session_id="integrator-1")
    assert check.standalone_session_ids == ("solo",)
    assert check.blocking_session_ids == ("solo",)
