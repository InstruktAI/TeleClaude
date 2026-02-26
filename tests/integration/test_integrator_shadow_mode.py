"""Integration tests for shadow-mode integrator runtime behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.queue import IntegrationQueue
from teleclaude.core.integration.readiness_projection import CandidateKey, CandidateReadiness
from teleclaude.core.integration.runtime import IntegratorShadowRuntime, MainBranchClearanceProbe


@pytest.mark.integration
def test_runtime_resumes_after_restart_when_candidate_was_in_progress(tmp_path: Path) -> None:
    lease_path = tmp_path / "integration-lease.json"
    queue_path = tmp_path / "integration-queue.json"
    checkpoint_path = tmp_path / "integration-checkpoint.json"

    key = CandidateKey(slug="resume", branch="worktree/resume", sha="abc123")
    initial_queue = IntegrationQueue(state_path=queue_path)
    initial_queue.enqueue(key=key, ready_at="2026-02-26T12:01:00+00:00")

    popped = initial_queue.pop_next()
    assert popped is not None
    assert popped.status == "in_progress"

    restarted_queue = IntegrationQueue(state_path=queue_path)
    recovered = restarted_queue.get(key=key)
    assert recovered is not None
    assert recovered.status == "queued"

    readiness = CandidateReadiness(
        key=key,
        ready_at="2026-02-26T12:01:00+00:00",
        status="READY",
        reasons=(),
        superseded_by=None,
    )

    outcomes = []
    runtime = IntegratorShadowRuntime(
        lease_store=IntegrationLeaseStore(state_path=lease_path),
        queue=restarted_queue,
        readiness_lookup=lambda _key: readiness,
        clearance_probe=MainBranchClearanceProbe(
            sessions_provider=lambda: (),
            session_tail_provider=lambda _session_id: "",
            dirty_tracked_paths_provider=lambda: (),
        ),
        outcome_sink=outcomes.append,
        checkpoint_path=checkpoint_path,
        clearance_retry_seconds=0.001,
    )

    result = runtime.drain_ready_candidates(owner_session_id="integrator-1")
    assert result.lease_acquired is True
    assert [item.outcome for item in result.outcomes] == ["would_integrate"]


@pytest.mark.integration
def test_runtime_commits_housekeeping_changes_before_processing(tmp_path: Path) -> None:
    lease_path = tmp_path / "integration-lease.json"
    queue_path = tmp_path / "integration-queue.json"
    checkpoint_path = tmp_path / "integration-checkpoint.json"

    key = CandidateKey(slug="housekeeping", branch="worktree/housekeeping", sha="def456")
    queue = IntegrationQueue(state_path=queue_path)
    queue.enqueue(key=key, ready_at="2026-02-26T12:01:00+00:00")

    readiness = CandidateReadiness(
        key=key,
        ready_at="2026-02-26T12:01:00+00:00",
        status="READY",
        reasons=(),
        superseded_by=None,
    )

    dirty_paths: list[str] = ["teleclaude/core/integration/runtime.py"]
    housekeeping_calls: list[tuple[str, ...]] = []

    def _housekeeping_committer(paths: tuple[str, ...]) -> bool:
        housekeeping_calls.append(paths)
        dirty_paths.clear()
        return True

    outcomes = []
    runtime = IntegratorShadowRuntime(
        lease_store=IntegrationLeaseStore(state_path=lease_path),
        queue=queue,
        readiness_lookup=lambda _key: readiness,
        clearance_probe=MainBranchClearanceProbe(
            sessions_provider=lambda: (),
            session_tail_provider=lambda _session_id: "",
            dirty_tracked_paths_provider=lambda: tuple(dirty_paths),
        ),
        outcome_sink=outcomes.append,
        checkpoint_path=checkpoint_path,
        housekeeping_committer=_housekeeping_committer,
        clearance_retry_seconds=0.001,
    )

    result = runtime.drain_ready_candidates(owner_session_id="integrator-1")

    assert result.lease_acquired is True
    assert [item.outcome for item in result.outcomes] == ["would_integrate"]
    assert housekeeping_calls == [("teleclaude/core/integration/runtime.py",)]
