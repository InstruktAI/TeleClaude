"""Characterization tests for teleclaude.core.integration.runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.queue import IntegrationQueue
from teleclaude.core.integration.readiness_projection import CandidateKey, CandidateReadiness
from teleclaude.core.integration.runtime import (
    IntegratorShadowRuntime,
    MainBranchClearanceProbe,
    RuntimeDrainResult,
    SessionSnapshot,
    ShadowOutcome,
    classify_standalone_sessions,
    tail_indicates_active_main_modification,
)

_NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
_READY_AT = "2024-01-01T10:00:00+00:00"


# ---------------------------------------------------------------------------
# classify_standalone_sessions
# ---------------------------------------------------------------------------


def test_classify_standalone_excludes_workers() -> None:
    orch = SessionSnapshot(session_id="orch-1", initiator_session_id=None)
    worker = SessionSnapshot(session_id="worker-1", initiator_session_id="orch-1")
    result = classify_standalone_sessions((orch, worker))
    ids = {s.session_id for s in result}
    assert "worker-1" not in ids


def test_classify_standalone_excludes_orchestrators() -> None:
    orch = SessionSnapshot(session_id="orch-1", initiator_session_id=None)
    worker = SessionSnapshot(session_id="worker-1", initiator_session_id="orch-1")
    result = classify_standalone_sessions((orch, worker))
    # orch-1 appears as orchestrator_id so is excluded
    ids = {s.session_id for s in result}
    assert "orch-1" not in ids


def test_classify_standalone_excludes_specified_session() -> None:
    s1 = SessionSnapshot(session_id="standalone-1", initiator_session_id=None)
    s2 = SessionSnapshot(session_id="standalone-2", initiator_session_id=None)
    result = classify_standalone_sessions((s1, s2), exclude_session_id="standalone-1")
    ids = {s.session_id for s in result}
    assert "standalone-1" not in ids
    assert "standalone-2" in ids


def test_classify_standalone_returns_sorted_by_session_id() -> None:
    sessions = (
        SessionSnapshot(session_id="session-c", initiator_session_id=None),
        SessionSnapshot(session_id="session-a", initiator_session_id=None),
        SessionSnapshot(session_id="session-b", initiator_session_id=None),
    )
    result = classify_standalone_sessions(sessions)
    ids = [s.session_id for s in result]
    assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# tail_indicates_active_main_modification
# ---------------------------------------------------------------------------


def test_tail_indicates_modification_detects_git_commit() -> None:
    tail = "running: git commit -m 'fix' on branch main"
    assert tail_indicates_active_main_modification(tail) is True


def test_tail_indicates_modification_returns_false_for_empty() -> None:
    assert tail_indicates_active_main_modification("") is False


def test_tail_indicates_modification_returns_false_when_idle() -> None:
    assert tail_indicates_active_main_modification("idle") is False
    assert tail_indicates_active_main_modification("waiting for input on main") is False


def test_tail_indicates_modification_returns_false_without_main() -> None:
    assert tail_indicates_active_main_modification("git commit -m 'fix'") is False


# ---------------------------------------------------------------------------
# MainBranchClearanceProbe
# ---------------------------------------------------------------------------


def test_clearance_probe_cleared_when_no_sessions_and_no_dirty() -> None:
    probe = MainBranchClearanceProbe(
        sessions_provider=lambda: (),
        session_tail_provider=lambda _: "",
        dirty_tracked_paths_provider=lambda: (),
    )
    check = probe.check()
    assert check.cleared is True
    assert check.blocking_session_ids == ()
    assert check.dirty_tracked_paths == ()


def test_clearance_probe_reports_dirty_paths() -> None:
    probe = MainBranchClearanceProbe(
        sessions_provider=lambda: (),
        session_tail_provider=lambda _: "",
        dirty_tracked_paths_provider=lambda: ("file.py",),
    )
    check = probe.check()
    assert check.cleared is False
    assert "file.py" in check.dirty_tracked_paths


def test_clearance_probe_sorts_dirty_paths() -> None:
    probe = MainBranchClearanceProbe(
        sessions_provider=lambda: (),
        session_tail_provider=lambda _: "",
        dirty_tracked_paths_provider=lambda: ("z.py", "a.py"),
    )
    check = probe.check()
    assert check.dirty_tracked_paths == ("a.py", "z.py")


# ---------------------------------------------------------------------------
# IntegratorShadowRuntime — drain with no items
# ---------------------------------------------------------------------------


def _make_runtime(tmp_path: Path) -> tuple[IntegratorShadowRuntime, IntegrationQueue]:
    queue = IntegrationQueue(state_path=tmp_path / "queue.json")
    lease_store = IntegrationLeaseStore(state_path=tmp_path / "lease.json")
    probe = MainBranchClearanceProbe(
        sessions_provider=lambda: (),
        session_tail_provider=lambda _: "",
        dirty_tracked_paths_provider=lambda: (),
    )
    outcomes: list[ShadowOutcome] = []
    runtime = IntegratorShadowRuntime(
        lease_store=lease_store,
        queue=queue,
        readiness_lookup=lambda _: None,
        clearance_probe=probe,
        outcome_sink=outcomes.append,
        checkpoint_path=tmp_path / "cp.json",
        clock=lambda: _NOW,
        sleep_fn=lambda _: None,
        shadow_mode=True,
    )
    return runtime, queue


def test_drain_empty_queue_returns_no_outcomes(tmp_path: Path) -> None:
    runtime, _ = _make_runtime(tmp_path)
    result = runtime.drain_ready_candidates(owner_session_id="integrator-session-1")
    assert isinstance(result, RuntimeDrainResult)
    assert result.outcomes == ()
    assert result.lease_acquired is True


def test_drain_acquires_and_releases_lease(tmp_path: Path) -> None:
    lease_store = IntegrationLeaseStore(state_path=tmp_path / "lease.json")
    queue = IntegrationQueue(state_path=tmp_path / "queue.json")
    probe = MainBranchClearanceProbe(
        sessions_provider=lambda: (),
        session_tail_provider=lambda _: "",
        dirty_tracked_paths_provider=lambda: (),
    )
    runtime = IntegratorShadowRuntime(
        lease_store=lease_store,
        queue=queue,
        readiness_lookup=lambda _: None,
        clearance_probe=probe,
        outcome_sink=lambda _: None,
        checkpoint_path=tmp_path / "cp.json",
        clock=lambda: _NOW,
        sleep_fn=lambda _: None,
        shadow_mode=True,
    )
    runtime.drain_ready_candidates(owner_session_id="integrator-session-1")
    # After drain completes, lease should be released
    record = lease_store.read(key="integration/main")
    assert record is None


def test_drain_returns_lease_acquired_false_when_busy(tmp_path: Path) -> None:
    lease_store = IntegrationLeaseStore(state_path=tmp_path / "lease.json")
    # Pre-acquire with another owner
    lease_store.acquire(key="integration/main", owner_session_id="other-owner", now=_NOW)

    queue = IntegrationQueue(state_path=tmp_path / "queue.json")
    probe = MainBranchClearanceProbe(
        sessions_provider=lambda: (),
        session_tail_provider=lambda _: "",
        dirty_tracked_paths_provider=lambda: (),
    )
    runtime = IntegratorShadowRuntime(
        lease_store=lease_store,
        queue=queue,
        readiness_lookup=lambda _: None,
        clearance_probe=probe,
        outcome_sink=lambda _: None,
        checkpoint_path=tmp_path / "cp.json",
        clock=lambda: _NOW,
        sleep_fn=lambda _: None,
        shadow_mode=True,
    )
    result = runtime.drain_ready_candidates(owner_session_id="integrator-session-1")
    assert result.lease_acquired is False


# ---------------------------------------------------------------------------
# IntegratorShadowRuntime — enqueue_ready_candidates
# ---------------------------------------------------------------------------


def test_enqueue_ready_candidates_adds_ready_items(tmp_path: Path) -> None:
    runtime, queue = _make_runtime(tmp_path)
    key = CandidateKey(slug="slug-a", branch="branch-a", sha="sha-a")
    readiness = CandidateReadiness(
        key=key,
        ready_at=_READY_AT,
        status="READY",
        reasons=(),
        superseded_by=None,
    )
    runtime.enqueue_ready_candidates((readiness,))
    item = queue.get(key=key)
    assert item is not None
    assert item.status == "queued"


def test_enqueue_ready_candidates_skips_non_ready(tmp_path: Path) -> None:
    runtime, queue = _make_runtime(tmp_path)
    key = CandidateKey(slug="slug-b", branch="branch-b", sha="sha-b")
    readiness = CandidateReadiness(
        key=key,
        ready_at=_READY_AT,
        status="NOT_READY",
        reasons=("missing review",),
        superseded_by=None,
    )
    runtime.enqueue_ready_candidates((readiness,))
    assert queue.get(key=key) is None
