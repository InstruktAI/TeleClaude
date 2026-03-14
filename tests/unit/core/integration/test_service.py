"""Characterization tests for teleclaude.core.integration.service."""

from __future__ import annotations

from teleclaude.core.integration.events import (
    BranchPushedPayload,
    FinalizeReadyPayload,
    ReviewApprovedPayload,
)
from teleclaude.core.integration.service import (
    IngestionResult,
    IntegrationEventService,
)

_REVIEW_APPROVED: ReviewApprovedPayload = {
    "slug": "slug-a",
    "approved_at": "2024-01-01T12:00:00+00:00",
    "review_round": 1,
    "reviewer_session_id": "rev-1",
}

_FINALIZE_READY: FinalizeReadyPayload = {
    "slug": "slug-a",
    "branch": "branch-a",
    "sha": "sha-abc",
    "worker_session_id": "w1",
    "orchestrator_session_id": "o1",
    "ready_at": "2024-01-01T12:00:00+00:00",
}

_BRANCH_PUSHED: BranchPushedPayload = {
    "branch": "branch-a",
    "sha": "sha-abc",
    "remote": "origin",
    "pushed_at": "2024-01-01T11:00:00+00:00",
    "pusher": "agent-1",
}


def _make_service(*, reachable: bool = True, integrated: bool = False) -> IntegrationEventService:
    return IntegrationEventService.create(
        reachability_checker=lambda _b, _s, _r: reachable,
        integrated_checker=lambda _s, _ref: integrated,
        remote="origin",
    )


# ---------------------------------------------------------------------------
# IntegrationEventService.create
# ---------------------------------------------------------------------------


def test_create_returns_service_instance():
    svc = _make_service()
    assert isinstance(svc, IntegrationEventService)


# ---------------------------------------------------------------------------
# IntegrationEventService.ingest_raw
# ---------------------------------------------------------------------------


def test_ingest_raw_valid_event_returns_appended():
    svc = _make_service()
    result = svc.ingest_raw("review_approved", _REVIEW_APPROVED)
    assert result.status == "APPENDED"
    assert result.event is not None


def test_ingest_raw_unknown_event_type_returns_rejected():
    svc = _make_service()
    result = svc.ingest_raw("not_a_real_type", {"slug": "x"})
    assert result.status == "REJECTED"
    assert result.event is None
    assert len(result.diagnostics) > 0


def test_ingest_raw_invalid_payload_returns_rejected():
    svc = _make_service()
    result = svc.ingest_raw("review_approved", {"slug": "only-this"})
    assert result.status == "REJECTED"


# ---------------------------------------------------------------------------
# IntegrationEventService.ingest
# ---------------------------------------------------------------------------


def test_ingest_valid_event_returns_appended():
    svc = _make_service()
    result = svc.ingest("review_approved", _REVIEW_APPROVED)
    assert result.status == "APPENDED"


def test_ingest_finalize_ready_transitions_to_not_ready_without_review():
    svc = _make_service(reachable=True, integrated=False)
    result = svc.ingest("finalize_ready", _FINALIZE_READY)
    assert result.status == "APPENDED"
    # No review_approved yet → not READY
    assert len(result.transitioned_to_ready) == 0


def test_ingest_all_events_transitions_candidate_to_ready():
    svc = _make_service(reachable=True, integrated=False)
    svc.ingest("review_approved", _REVIEW_APPROVED)
    svc.ingest("branch_pushed", _BRANCH_PUSHED)
    result = svc.ingest("finalize_ready", _FINALIZE_READY)
    assert len(result.transitioned_to_ready) == 1
    assert result.transitioned_to_ready[0].status == "READY"


def test_ingest_returns_ingestion_result_type():
    svc = _make_service()
    result = svc.ingest("review_approved", _REVIEW_APPROVED)
    assert isinstance(result, IngestionResult)


# ---------------------------------------------------------------------------
# IntegrationEventService.get_candidate
# ---------------------------------------------------------------------------


def test_get_candidate_returns_none_before_finalize_ready():
    svc = _make_service()
    svc.ingest("review_approved", _REVIEW_APPROVED)
    assert svc.get_candidate(slug="slug-a", branch="branch-a", sha="sha-abc") is None


def test_get_candidate_returns_readiness_after_finalize_ready():
    svc = _make_service()
    svc.ingest("finalize_ready", _FINALIZE_READY)
    readiness = svc.get_candidate(slug="slug-a", branch="branch-a", sha="sha-abc")
    assert readiness is not None


# ---------------------------------------------------------------------------
# IntegrationEventService.all_candidates
# ---------------------------------------------------------------------------


def test_all_candidates_returns_empty_initially():
    svc = _make_service()
    assert svc.all_candidates() == ()


def test_all_candidates_includes_ingested_candidate():
    svc = _make_service()
    svc.ingest("finalize_ready", _FINALIZE_READY)
    candidates = svc.all_candidates()
    assert len(candidates) == 1
    assert candidates[0].key.slug == "slug-a"


# ---------------------------------------------------------------------------
# IntegrationEventService.replay
# ---------------------------------------------------------------------------


def test_replay_rebuilds_projection_from_events():
    from teleclaude.core.integration.events import build_integration_event

    svc = _make_service(reachable=True, integrated=False)
    e1 = build_integration_event("review_approved", _REVIEW_APPROVED)
    e2 = build_integration_event("branch_pushed", _BRANCH_PUSHED)
    e3 = build_integration_event("finalize_ready", _FINALIZE_READY)
    update = svc.replay((e1, e2, e3))
    assert len(update.transitioned_to_ready) == 1
