"""Unit tests for canonical integration event model behavior."""

from pathlib import Path

import pytest

from teleclaude.core.integration import (
    CandidateKey,
    IntegrationEventService,
    IntegrationEventStore,
    IntegrationEventStoreError,
    IntegrationEventValidationError,
    build_integration_event,
    validate_event_payload,
)

pytestmark = pytest.mark.timeout(5)


def _always_reachable(_branch: str, _sha: str, _remote: str) -> bool:
    return True


def _never_integrated(_sha: str, _main_ref: str) -> bool:
    return False


def _new_service(event_log_path: Path) -> IntegrationEventService:
    return IntegrationEventService.with_file_store(
        event_log_path=event_log_path,
        reachability_checker=_always_reachable,
        integrated_checker=_never_integrated,
    )


def test_validate_event_payload_rejects_missing_and_unexpected_fields() -> None:
    with pytest.raises(IntegrationEventValidationError) as exc:
        validate_event_payload(
            "review_approved",
            {
                "slug": "demo-slug",
                "approved_at": "2026-02-26T10:00:00Z",
                "review_round": 1,
                "unexpected": "value",
            },
        )

    diagnostics = exc.value.diagnostics
    assert any("missing required fields" in item for item in diagnostics)
    assert any("unexpected fields" in item for item in diagnostics)


def test_build_event_reports_correct_event_type_for_received_at_validation() -> None:
    with pytest.raises(IntegrationEventValidationError) as exc:
        build_integration_event(
            "review_approved",
            {
                "slug": "demo-slug",
                "approved_at": "2026-02-26T10:00:00Z",
                "review_round": 1,
                "reviewer_session_id": "review-1",
            },
            received_at="not-an-iso8601-timestamp",
        )

    assert exc.value.event_type == "review_approved"
    assert any("received_at must be valid ISO8601" in item for item in exc.value.diagnostics)


def test_event_store_append_is_idempotent_and_collision_safe(tmp_path: Path) -> None:
    store = IntegrationEventStore(event_log_path=tmp_path / "integration-events.jsonl")
    event = build_integration_event(
        "branch_pushed",
        {
            "branch": "feat/demo",
            "sha": "abc123",
            "remote": "origin",
            "pushed_at": "2026-02-26T10:00:00Z",
            "pusher": "builder",
        },
    )

    first_append = store.append(event)
    duplicate_append = store.append(event)

    assert first_append.status == "appended"
    assert duplicate_append.status == "duplicate"
    assert store.event_count == 1

    conflicting = build_integration_event(
        "branch_pushed",
        {
            "branch": "feat/demo",
            "sha": "def456",
            "remote": "origin",
            "pushed_at": "2026-02-26T10:00:00Z",
            "pusher": "builder",
        },
        idempotency_key=event.idempotency_key,
    )
    with pytest.raises(IntegrationEventStoreError):
        store.append(conflicting)


def test_service_marks_older_finalize_candidate_as_superseded(tmp_path: Path) -> None:
    service = _new_service(tmp_path / "integration-events.jsonl")

    assert (
        service.ingest(
            "review_approved",
            {
                "slug": "integration-events-model",
                "approved_at": "2026-02-26T10:00:00Z",
                "review_round": 1,
                "reviewer_session_id": "review-1",
            },
        ).status
        == "APPENDED"
    )
    assert (
        service.ingest(
            "branch_pushed",
            {
                "branch": "worktree/integration-events-model-old",
                "sha": "aaa111",
                "remote": "origin",
                "pushed_at": "2026-02-26T10:01:00Z",
                "pusher": "worker-1",
            },
        ).status
        == "APPENDED"
    )
    first_finalize = service.ingest(
        "finalize_ready",
        {
            "slug": "integration-events-model",
            "branch": "worktree/integration-events-model-old",
            "sha": "aaa111",
            "worker_session_id": "worker-1",
            "orchestrator_session_id": "orch-1",
            "ready_at": "2026-02-26T10:02:00Z",
        },
    )
    assert first_finalize.status == "APPENDED"
    assert service.get_candidate(
        slug="integration-events-model", branch="worktree/integration-events-model-old", sha="aaa111"
    )
    assert (
        service.get_candidate(
            slug="integration-events-model", branch="worktree/integration-events-model-old", sha="aaa111"
        )
        and service.get_candidate(
            slug="integration-events-model",
            branch="worktree/integration-events-model-old",
            sha="aaa111",
        ).status
        == "READY"
    )

    assert (
        service.ingest(
            "branch_pushed",
            {
                "branch": "worktree/integration-events-model-new",
                "sha": "bbb222",
                "remote": "origin",
                "pushed_at": "2026-02-26T10:03:00Z",
                "pusher": "worker-2",
            },
        ).status
        == "APPENDED"
    )
    second_finalize = service.ingest(
        "finalize_ready",
        {
            "slug": "integration-events-model",
            "branch": "worktree/integration-events-model-new",
            "sha": "bbb222",
            "worker_session_id": "worker-2",
            "orchestrator_session_id": "orch-1",
            "ready_at": "2026-02-26T10:04:00Z",
        },
    )

    assert second_finalize.status == "APPENDED"
    assert second_finalize.transitioned_to_superseded
    assert any("superseded" in message for message in second_finalize.diagnostics)

    old_candidate = service.get_candidate(
        slug="integration-events-model",
        branch="worktree/integration-events-model-old",
        sha="aaa111",
    )
    new_candidate = service.get_candidate(
        slug="integration-events-model",
        branch="worktree/integration-events-model-new",
        sha="bbb222",
    )
    assert old_candidate is not None
    assert new_candidate is not None
    assert old_candidate.status == "SUPERSEDED"
    assert old_candidate.superseded_by == CandidateKey(
        slug="integration-events-model",
        branch="worktree/integration-events-model-new",
        sha="bbb222",
    )
    assert new_candidate.status == "READY"


def test_service_breaks_equal_ready_at_ties_deterministically(tmp_path: Path) -> None:
    service = _new_service(tmp_path / "integration-events.jsonl")

    assert (
        service.ingest(
            "review_approved",
            {
                "slug": "integration-events-model",
                "approved_at": "2026-02-26T10:00:00Z",
                "review_round": 1,
                "reviewer_session_id": "review-1",
            },
        ).status
        == "APPENDED"
    )
    assert (
        service.ingest(
            "branch_pushed",
            {
                "branch": "worktree/integration-events-model-a",
                "sha": "aaa111",
                "remote": "origin",
                "pushed_at": "2026-02-26T10:01:00Z",
                "pusher": "worker-1",
            },
        ).status
        == "APPENDED"
    )
    assert (
        service.ingest(
            "branch_pushed",
            {
                "branch": "worktree/integration-events-model-z",
                "sha": "bbb222",
                "remote": "origin",
                "pushed_at": "2026-02-26T10:01:30Z",
                "pusher": "worker-2",
            },
        ).status
        == "APPENDED"
    )

    assert (
        service.ingest(
            "finalize_ready",
            {
                "slug": "integration-events-model",
                "branch": "worktree/integration-events-model-a",
                "sha": "aaa111",
                "worker_session_id": "worker-1",
                "orchestrator_session_id": "orch-1",
                "ready_at": "2026-02-26T10:02:00Z",
            },
        ).status
        == "APPENDED"
    )
    second_finalize = service.ingest(
        "finalize_ready",
        {
            "slug": "integration-events-model",
            "branch": "worktree/integration-events-model-z",
            "sha": "bbb222",
            "worker_session_id": "worker-2",
            "orchestrator_session_id": "orch-1",
            "ready_at": "2026-02-26T10:02:00Z",
        },
    )
    assert second_finalize.status == "APPENDED"

    candidate_a = service.get_candidate(
        slug="integration-events-model",
        branch="worktree/integration-events-model-a",
        sha="aaa111",
    )
    candidate_z = service.get_candidate(
        slug="integration-events-model",
        branch="worktree/integration-events-model-z",
        sha="bbb222",
    )
    assert candidate_a is not None
    assert candidate_z is not None
    assert candidate_a.status == "SUPERSEDED"
    assert candidate_a.superseded_by == candidate_z.key
    assert candidate_z.status == "READY"


def test_service_replays_history_on_init(tmp_path: Path) -> None:
    event_log_path = tmp_path / "integration-events.jsonl"
    first = _new_service(event_log_path)
    assert (
        first.ingest(
            "review_approved",
            {
                "slug": "integration-events-model",
                "approved_at": "2026-02-26T10:00:00Z",
                "review_round": 1,
                "reviewer_session_id": "review-1",
            },
        ).status
        == "APPENDED"
    )
    assert (
        first.ingest(
            "branch_pushed",
            {
                "branch": "worktree/integration-events-model",
                "sha": "abc123",
                "remote": "origin",
                "pushed_at": "2026-02-26T10:01:00Z",
                "pusher": "worker-1",
            },
        ).status
        == "APPENDED"
    )
    assert (
        first.ingest(
            "finalize_ready",
            {
                "slug": "integration-events-model",
                "branch": "worktree/integration-events-model",
                "sha": "abc123",
                "worker_session_id": "worker-1",
                "orchestrator_session_id": "orch-1",
                "ready_at": "2026-02-26T10:02:00Z",
            },
        ).status
        == "APPENDED"
    )

    restarted = _new_service(event_log_path)
    candidate = restarted.get_candidate(
        slug="integration-events-model",
        branch="worktree/integration-events-model",
        sha="abc123",
    )
    assert candidate is not None
    assert candidate.status == "READY"
