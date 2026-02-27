"""Integration coverage for blocked integration outcomes and resume flow."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.core.integration.blocked_followup import BlockedFollowUpStore
from teleclaude.core.integration.event_store import IntegrationEventStore
from teleclaude.core.integration.events import build_integration_event
from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.queue import IntegrationQueue
from teleclaude.core.integration.readiness_projection import CandidateKey, CandidateReadiness, ReadinessStatus
from teleclaude.core.integration.runtime import (
    IntegrationBlockedOutcome,
    IntegratorShadowRuntime,
    MainBranchClearanceProbe,
)


@pytest.mark.integration
def test_runtime_emits_durable_integration_blocked_payload_with_evidence(tmp_path: Path) -> None:
    lease_path = tmp_path / "integration-lease.json"
    queue_path = tmp_path / "integration-queue.json"
    checkpoint_path = tmp_path / "integration-checkpoint.json"
    blocked_events_path = tmp_path / "integration-events.jsonl"

    key = CandidateKey(slug="blocked-flow", branch="worktree/blocked-flow", sha="abc123")
    queue = IntegrationQueue(state_path=queue_path)
    queue.enqueue(key=key, ready_at="2026-02-26T12:01:00+00:00")

    readiness = CandidateReadiness(
        key=key,
        ready_at="2026-02-26T12:01:00+00:00",
        status="NOT_READY",
        reasons=(
            "merge conflict in files: README.md, teleclaude/core/integration/runtime.py",
            "candidate failed readiness recheck",
        ),
        superseded_by=None,
    )
    event_store = IntegrationEventStore(event_log_path=blocked_events_path)
    blocked_payloads = []

    def _blocked_outcome_sink(payload: IntegrationBlockedOutcome) -> None:
        blocked_payloads.append(payload)
        event_payload = {
            "slug": payload.slug,
            "branch": payload.branch,
            "sha": payload.sha,
            "conflict_evidence": list(payload.conflict_evidence),
            "diagnostics": list(payload.diagnostics),
            "next_action": payload.next_action,
            "blocked_at": payload.blocked_at,
        }
        if payload.follow_up_slug:
            event_payload["follow_up_slug"] = payload.follow_up_slug
        event_store.append(
            build_integration_event(
                "integration_blocked",
                event_payload,
            )
        )

    runtime = IntegratorShadowRuntime(
        lease_store=IntegrationLeaseStore(state_path=lease_path),
        queue=queue,
        readiness_lookup=lambda _key: readiness,
        clearance_probe=MainBranchClearanceProbe(
            sessions_provider=lambda: (),
            session_tail_provider=lambda _session_id: "",
            dirty_tracked_paths_provider=lambda: (),
        ),
        outcome_sink=lambda _outcome: None,
        blocked_outcome_sink=_blocked_outcome_sink,
        checkpoint_path=checkpoint_path,
        clearance_retry_seconds=0.001,
    )

    result = runtime.drain_ready_candidates(owner_session_id="integrator-1")
    assert result.lease_acquired is True
    assert [item.outcome for item in result.outcomes] == ["would_block"]
    assert len(blocked_payloads) == 1
    blocked = blocked_payloads[0]

    assert blocked.slug == "blocked-flow"
    assert blocked.branch == "worktree/blocked-flow"
    assert blocked.sha == "abc123"
    assert blocked.conflict_evidence
    assert blocked.diagnostics
    assert blocked.next_action

    replayed = event_store.replay()
    assert len(replayed) == 1
    assert replayed[0].event_type == "integration_blocked"
    assert replayed[0].payload["slug"] == "blocked-flow"
    assert replayed[0].payload["branch"] == "worktree/blocked-flow"
    assert replayed[0].payload["sha"] == "abc123"


@pytest.mark.integration
def test_blocked_follow_up_creation_is_idempotent_and_keeps_candidate_linkage(tmp_path: Path) -> None:
    store = BlockedFollowUpStore(
        state_path=tmp_path / "blocked-followups.json",
        todos_root=tmp_path / "todos",
    )
    payload = {
        "slug": "blocked-flow",
        "branch": "worktree/blocked-flow",
        "sha": "abc123",
        "conflict_evidence": ["merge conflict in files: README.md"],
        "diagnostics": ["resolve merge conflict and push branch"],
        "next_action": "Resolve merge conflicts on the candidate branch, push the fix, then resume integration.",
        "blocked_at": "2026-02-26T12:02:00+00:00",
        "follow_up_slug": "",
    }

    first = store.ensure_follow_up(payload)
    payload["diagnostics"] = ["resolve merge conflict and push updated branch"]
    second = store.ensure_follow_up(payload)

    assert first.follow_up_slug == second.follow_up_slug
    assert len(store.links()) == 1
    assert second.last_diagnostics == ("resolve merge conflict and push updated branch",)
    assert store.candidate_for_follow_up(follow_up_slug=second.follow_up_slug) == CandidateKey(
        slug="blocked-flow",
        branch="worktree/blocked-flow",
        sha="abc123",
    )

    todo_dir = tmp_path / "todos" / second.follow_up_slug
    assert (todo_dir / "requirements.md").exists()
    assert (todo_dir / "implementation-plan.md").exists()
    assert (todo_dir / "state.yaml").exists()

    requirements_text = (todo_dir / "requirements.md").read_text(encoding="utf-8")
    assert "worktree/blocked-flow" in requirements_text
    assert "abc123" in requirements_text


@pytest.mark.integration
def test_resume_from_follow_up_rechecks_readiness_before_requeueing(tmp_path: Path) -> None:
    lease_path = tmp_path / "integration-lease.json"
    queue_path = tmp_path / "integration-queue.json"
    checkpoint_path = tmp_path / "integration-checkpoint.json"
    follow_up_store = BlockedFollowUpStore(
        state_path=tmp_path / "blocked-followups.json",
        todos_root=tmp_path / "todos",
    )

    key = CandidateKey(slug="resume-flow", branch="worktree/resume-flow", sha="def456")
    queue = IntegrationQueue(state_path=queue_path)
    queue.enqueue(key=key, ready_at="2026-02-26T12:01:00+00:00")
    popped = queue.pop_next()
    assert popped is not None
    queue.mark_blocked(key=key, reason="merge conflict in files: runtime.py")

    link = follow_up_store.ensure_follow_up(
        {
            "slug": key.slug,
            "branch": key.branch,
            "sha": key.sha,
            "conflict_evidence": ["merge conflict in files: runtime.py"],
            "diagnostics": ["resolve merge conflict and push branch"],
            "next_action": "Resolve merge conflicts on the candidate branch, push the fix, then resume integration.",
            "blocked_at": "2026-02-26T12:03:00+00:00",
            "follow_up_slug": "",
        }
    )

    readiness_status: ReadinessStatus = "NOT_READY"

    def _readiness_lookup(_key: CandidateKey) -> CandidateReadiness:
        if readiness_status == "READY":
            reasons = ()
        else:
            reasons = ("branch still has unresolved merge conflict",)
        return CandidateReadiness(
            key=key,
            ready_at="2026-02-26T12:01:00+00:00",
            status=readiness_status,
            reasons=reasons,
            superseded_by=None,
        )

    def _follow_up_lookup(follow_up_slug: str) -> CandidateKey | None:
        return follow_up_store.candidate_for_follow_up(follow_up_slug=follow_up_slug)

    def _follow_up_is_resolved(follow_up_slug: str) -> bool:
        candidate_key = follow_up_store.candidate_for_follow_up(follow_up_slug=follow_up_slug)
        if candidate_key is None:
            return False
        link_record = follow_up_store.get_by_candidate(key=candidate_key)
        return link_record is not None and link_record.status == "resolved"

    runtime = IntegratorShadowRuntime(
        lease_store=IntegrationLeaseStore(state_path=lease_path),
        queue=queue,
        readiness_lookup=_readiness_lookup,
        clearance_probe=MainBranchClearanceProbe(
            sessions_provider=lambda: (),
            session_tail_provider=lambda _session_id: "",
            dirty_tracked_paths_provider=lambda: (),
        ),
        outcome_sink=lambda _outcome: None,
        checkpoint_path=checkpoint_path,
        follow_up_candidate_lookup=_follow_up_lookup,
        follow_up_resolution_checker=_follow_up_is_resolved,
        clearance_retry_seconds=0.001,
    )

    unresolved = runtime.resume_from_follow_up(owner_session_id="integrator-1", follow_up_slug=link.follow_up_slug)
    assert unresolved.resumed is False
    assert unresolved.reason == f"follow-up '{link.follow_up_slug}' is not resolved"

    follow_up_store.mark_resolved(follow_up_slug=link.follow_up_slug)
    still_not_ready = runtime.resume_from_follow_up(owner_session_id="integrator-1", follow_up_slug=link.follow_up_slug)
    assert still_not_ready.resumed is False
    assert still_not_ready.reason == "branch still has unresolved merge conflict"
    blocked_item = queue.get(key=key)
    assert blocked_item is not None
    assert blocked_item.status == "blocked"

    readiness_status = "READY"
    resumed = runtime.resume_from_follow_up(owner_session_id="integrator-1", follow_up_slug=link.follow_up_slug)
    assert resumed.resumed is True
    queued_item = queue.get(key=key)
    assert queued_item is not None
    assert queued_item.status == "queued"
    assert queued_item.status_reason == "resume requested after follow-up remediation and readiness recheck"
