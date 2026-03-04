"""Integration tests for integration readiness projection transitions."""

import pytest

from teleclaude.core.integration import IntegrationEventService


def _create_service() -> IntegrationEventService:
    return IntegrationEventService.create(
        reachability_checker=lambda _branch, _sha, _remote: True,
        integrated_checker=lambda _sha, _main_ref: False,
    )


@pytest.mark.integration
def test_candidate_transitions_from_not_ready_to_ready() -> None:
    service = _create_service()

    finalize_result = service.ingest(
        "finalize_ready",
        {
            "slug": "integration-events-model",
            "branch": "worktree/integration-events-model",
            "sha": "abc123",
            "worker_session_id": "worker-1",
            "orchestrator_session_id": "orch-1",
            "ready_at": "2026-02-26T10:00:00Z",
        },
    )
    assert finalize_result.status == "APPENDED"
    candidate = service.get_candidate(
        slug="integration-events-model",
        branch="worktree/integration-events-model",
        sha="abc123",
    )
    assert candidate is not None
    assert candidate.status == "NOT_READY"
    assert "missing review_approved for slug" in candidate.reasons
    assert "missing branch_pushed for origin/worktree/integration-events-model@abc123" in candidate.reasons

    review_result = service.ingest(
        "review_approved",
        {
            "slug": "integration-events-model",
            "approved_at": "2026-02-26T10:01:00Z",
            "review_round": 1,
            "reviewer_session_id": "review-1",
        },
    )
    assert review_result.status == "APPENDED"
    candidate = service.get_candidate(
        slug="integration-events-model",
        branch="worktree/integration-events-model",
        sha="abc123",
    )
    assert candidate is not None
    assert candidate.status == "NOT_READY"
    assert "missing branch_pushed for origin/worktree/integration-events-model@abc123" in candidate.reasons

    push_result = service.ingest(
        "branch_pushed",
        {
            "branch": "worktree/integration-events-model",
            "sha": "abc123",
            "remote": "origin",
            "pushed_at": "2026-02-26T10:02:00Z",
            "pusher": "worker-1",
        },
    )
    assert push_result.status == "APPENDED"
    assert len(push_result.transitioned_to_ready) == 1
    assert push_result.transitioned_to_ready[0].key.slug == "integration-events-model"

    candidate = service.get_candidate(
        slug="integration-events-model",
        branch="worktree/integration-events-model",
        sha="abc123",
    )
    assert candidate is not None
    assert candidate.status == "READY"
    assert candidate.reasons == ()


@pytest.mark.integration
def test_replay_restores_readiness_from_event_sequence() -> None:
    """Verify projection can be rebuilt by replaying a sequence of events."""
    from teleclaude.core.integration.events import build_integration_event

    events = tuple(
        build_integration_event(et, payload)
        for et, payload in [
            (
                "review_approved",
                {
                    "slug": "integration-events-model",
                    "approved_at": "2026-02-26T10:01:00Z",
                    "review_round": 1,
                    "reviewer_session_id": "review-1",
                },
            ),
            (
                "finalize_ready",
                {
                    "slug": "integration-events-model",
                    "branch": "worktree/integration-events-model",
                    "sha": "abc123",
                    "worker_session_id": "worker-1",
                    "orchestrator_session_id": "orch-1",
                    "ready_at": "2026-02-26T10:00:00Z",
                },
            ),
            (
                "branch_pushed",
                {
                    "branch": "worktree/integration-events-model",
                    "sha": "abc123",
                    "remote": "origin",
                    "pushed_at": "2026-02-26T10:02:00Z",
                    "pusher": "worker-1",
                },
            ),
        ]
    )

    service = _create_service()
    service.replay(events)

    restored = service.get_candidate(
        slug="integration-events-model",
        branch="worktree/integration-events-model",
        sha="abc123",
    )
    assert restored is not None
    assert restored.status == "READY"
