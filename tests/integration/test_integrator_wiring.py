"""Integration tests for integrator wiring — event schemas, bridge, trigger, and service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.integration.lease import IntegrationLeaseStore
from teleclaude.core.integration.queue import IntegrationQueue
from teleclaude.core.integration.readiness_projection import CandidateKey, CandidateReadiness
from teleclaude.core.integration.runtime import IntegratorShadowRuntime, MainBranchClearanceProbe
from teleclaude.core.integration.service import IntegrationEventService


# ---------------------------------------------------------------------------
# Phase 1: Event schemas
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_integration_event_schemas_registered_in_catalog() -> None:
    from teleclaude_events.catalog import build_default_catalog

    catalog = build_default_catalog()
    for event_type in [
        "domain.software-development.review.approved",
        "domain.software-development.deployment.started",
        "domain.software-development.deployment.completed",
        "domain.software-development.deployment.failed",
    ]:
        schema = catalog.get(event_type)
        assert schema is not None, f"Missing schema: {event_type}"
        assert schema.lifecycle is not None, f"Missing lifecycle: {event_type}"


@pytest.mark.integration
def test_deployment_lifecycle_declarations() -> None:
    from teleclaude_events.catalog import build_default_catalog

    catalog = build_default_catalog()

    started = catalog.get("domain.software-development.deployment.started")
    assert started is not None
    assert started.lifecycle is not None
    assert started.lifecycle.creates is True
    assert started.lifecycle.group_key == "slug"

    completed = catalog.get("domain.software-development.deployment.completed")
    assert completed is not None
    assert completed.lifecycle is not None
    assert completed.lifecycle.resolves is True
    assert completed.lifecycle.group_key == "slug"

    failed = catalog.get("domain.software-development.deployment.failed")
    assert failed is not None
    assert failed.lifecycle is not None
    assert failed.lifecycle.updates is True
    assert failed.lifecycle.group_key == "slug"
    assert "blocked_at" in failed.lifecycle.meaningful_fields
    assert failed.actionable is True


# ---------------------------------------------------------------------------
# Phase 2: Event emission bridge
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_emit_review_approved() -> None:
    with patch("teleclaude.core.integration_bridge.emit_event", new_callable=AsyncMock) as mock_emit:
        mock_emit.return_value = "1234-0"
        from teleclaude.core.integration_bridge import emit_review_approved

        result = await emit_review_approved(
            slug="my-feature",
            reviewer_session_id="sess-123",
            review_round=2,
            approved_at="2026-03-01T12:00:00+00:00",
        )
        assert result == "1234-0"
        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args
        assert call_kwargs.kwargs["event"] == "domain.software-development.review.approved"
        assert call_kwargs.kwargs["payload"]["slug"] == "my-feature"
        assert call_kwargs.kwargs["payload"]["review_round"] == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_emit_deployment_started() -> None:
    with patch("teleclaude.core.integration_bridge.emit_event", new_callable=AsyncMock) as mock_emit:
        mock_emit.return_value = "1234-1"
        from teleclaude.core.integration_bridge import emit_deployment_started

        result = await emit_deployment_started(
            slug="my-feature",
            branch="my-feature",
            sha="abc123def",
            orchestrator_session_id="orch-1",
        )
        assert result == "1234-1"
        assert mock_emit.call_args.kwargs["payload"]["branch"] == "my-feature"
        assert mock_emit.call_args.kwargs["payload"]["sha"] == "abc123def"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_emit_deployment_completed() -> None:
    with patch("teleclaude.core.integration_bridge.emit_event", new_callable=AsyncMock) as mock_emit:
        mock_emit.return_value = "1234-2"
        from teleclaude.core.integration_bridge import emit_deployment_completed

        result = await emit_deployment_completed(
            slug="my-feature",
            branch="my-feature",
            sha="abc123def",
            merge_commit="deadbeef",
        )
        assert result == "1234-2"
        assert mock_emit.call_args.kwargs["payload"]["merge_commit"] == "deadbeef"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_emit_deployment_failed() -> None:
    with patch("teleclaude.core.integration_bridge.emit_event", new_callable=AsyncMock) as mock_emit:
        mock_emit.return_value = "1234-3"
        from teleclaude.core.integration_bridge import emit_deployment_failed

        result = await emit_deployment_failed(
            slug="my-feature",
            branch="my-feature",
            sha="abc123def",
            conflict_evidence=["CONFLICT in file.py"],
            next_action="resolve conflict",
        )
        assert result == "1234-3"
        assert mock_emit.call_args.kwargs["payload"]["conflict_evidence"] == ["CONFLICT in file.py"]


# ---------------------------------------------------------------------------
# Phase 3: Integration trigger cartridge
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_trigger_fires_on_deployment_started() -> None:
    from teleclaude_events.cartridges.integration_trigger import IntegrationTriggerCartridge
    from teleclaude_events.envelope import EventEnvelope, EventLevel
    from teleclaude_events.pipeline import PipelineContext

    spawn_calls: list[tuple[str, str, str]] = []

    async def mock_spawn(slug: str, branch: str, sha: str) -> None:
        spawn_calls.append((slug, branch, sha))

    cartridge = IntegrationTriggerCartridge(spawn_callback=mock_spawn)

    event = EventEnvelope(
        event="domain.software-development.deployment.started",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        payload={"slug": "feat-x", "branch": "feat-x", "sha": "abc123"},
    )
    context = PipelineContext(catalog=AsyncMock(), db=AsyncMock())

    result = await cartridge.process(event, context)
    assert result is not None
    assert spawn_calls == [("feat-x", "feat-x", "abc123")]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_trigger_passes_non_matching_events() -> None:
    from teleclaude_events.cartridges.integration_trigger import IntegrationTriggerCartridge
    from teleclaude_events.envelope import EventEnvelope, EventLevel
    from teleclaude_events.pipeline import PipelineContext

    cartridge = IntegrationTriggerCartridge(spawn_callback=None)

    event = EventEnvelope(
        event="domain.software-development.planning.todo_created",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        payload={"slug": "unrelated"},
    )
    context = PipelineContext(catalog=AsyncMock(), db=AsyncMock())

    result = await cartridge.process(event, context)
    assert result is event  # Pass through unchanged


# ---------------------------------------------------------------------------
# Phase 5: Service without file store
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_service_create_without_file_store() -> None:
    service = IntegrationEventService.create(
        reachability_checker=lambda _b, _s, _r: True,
        integrated_checker=lambda _s, _r: False,
    )
    assert service.all_candidates() == ()


@pytest.mark.integration
def test_service_ingests_and_projects_review_approved() -> None:
    service = IntegrationEventService.create(
        reachability_checker=lambda _b, _s, _r: True,
        integrated_checker=lambda _s, _r: False,
    )
    result = service.ingest(
        "review_approved",
        {
            "slug": "feat-1",
            "approved_at": "2026-03-01T12:00:00+00:00",
            "review_round": 1,
            "reviewer_session_id": "sess-1",
        },
    )
    assert result.status == "APPENDED"


@pytest.mark.integration
def test_service_ingests_finalize_ready_and_branch_pushed() -> None:
    service = IntegrationEventService.create(
        reachability_checker=lambda _b, _s, _r: True,
        integrated_checker=lambda _s, _r: False,
    )
    # Review approved
    service.ingest(
        "review_approved",
        {"slug": "feat-1", "approved_at": "2026-03-01T12:00:00+00:00", "review_round": 1, "reviewer_session_id": "s1"},
    )
    # Finalize ready
    service.ingest(
        "finalize_ready",
        {
            "slug": "feat-1",
            "branch": "feat-1",
            "sha": "abc123",
            "worker_session_id": "w1",
            "orchestrator_session_id": "o1",
            "ready_at": "2026-03-01T13:00:00+00:00",
        },
    )
    # Branch pushed
    result = service.ingest(
        "branch_pushed",
        {
            "branch": "feat-1",
            "sha": "abc123",
            "remote": "origin",
            "pushed_at": "2026-03-01T13:05:00+00:00",
            "pusher": "worker",
        },
    )
    assert result.status == "APPENDED"
    assert len(result.transitioned_to_ready) == 1
    assert result.transitioned_to_ready[0].key.slug == "feat-1"
    assert result.transitioned_to_ready[0].status == "READY"


# ---------------------------------------------------------------------------
# Phase 6.1: End-to-end integrator queue drain
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_multiple_ready_candidates_processed_fifo(tmp_path: Path) -> None:
    lease_path = tmp_path / "lease.json"
    queue_path = tmp_path / "queue.json"
    checkpoint_path = tmp_path / "checkpoint.json"

    key1 = CandidateKey(slug="first", branch="worktree/first", sha="aaa111")
    key2 = CandidateKey(slug="second", branch="worktree/second", sha="bbb222")

    queue = IntegrationQueue(state_path=queue_path)
    queue.enqueue(key=key1, ready_at="2026-03-01T10:00:00+00:00")
    queue.enqueue(key=key2, ready_at="2026-03-01T11:00:00+00:00")

    readiness_map = {
        key1: CandidateReadiness(key=key1, ready_at="2026-03-01T10:00:00+00:00", status="READY", reasons=(), superseded_by=None),
        key2: CandidateReadiness(key=key2, ready_at="2026-03-01T11:00:00+00:00", status="READY", reasons=(), superseded_by=None),
    }

    outcomes = []
    runtime = IntegratorShadowRuntime(
        lease_store=IntegrationLeaseStore(state_path=lease_path),
        queue=queue,
        readiness_lookup=lambda k: readiness_map.get(k),
        clearance_probe=MainBranchClearanceProbe(
            sessions_provider=lambda: (),
            session_tail_provider=lambda _: "",
            dirty_tracked_paths_provider=lambda: (),
        ),
        outcome_sink=outcomes.append,
        checkpoint_path=checkpoint_path,
        clearance_retry_seconds=0.001,
    )

    result = runtime.drain_ready_candidates(owner_session_id="integrator-1")
    assert result.lease_acquired is True
    assert len(result.outcomes) == 2
    # FIFO order: first before second
    assert result.outcomes[0].key.slug == "first"
    assert result.outcomes[1].key.slug == "second"


@pytest.mark.integration
def test_integrator_self_ends_when_queue_empty(tmp_path: Path) -> None:
    lease_path = tmp_path / "lease.json"
    queue_path = tmp_path / "queue.json"
    checkpoint_path = tmp_path / "checkpoint.json"

    queue = IntegrationQueue(state_path=queue_path)

    runtime = IntegratorShadowRuntime(
        lease_store=IntegrationLeaseStore(state_path=lease_path),
        queue=queue,
        readiness_lookup=lambda _: None,
        clearance_probe=MainBranchClearanceProbe(
            sessions_provider=lambda: (),
            session_tail_provider=lambda _: "",
            dirty_tracked_paths_provider=lambda: (),
        ),
        outcome_sink=lambda _: None,
        checkpoint_path=checkpoint_path,
    )

    result = runtime.drain_ready_candidates(owner_session_id="integrator-1")
    assert result.lease_acquired is True
    assert len(result.outcomes) == 0
    # Lease released after drain
    lease = IntegrationLeaseStore(state_path=lease_path).read(key="integration/main")
    assert lease is None


@pytest.mark.integration
def test_merge_conflict_produces_would_block_outcome(tmp_path: Path) -> None:
    lease_path = tmp_path / "lease.json"
    queue_path = tmp_path / "queue.json"
    checkpoint_path = tmp_path / "checkpoint.json"

    key = CandidateKey(slug="conflicted", branch="worktree/conflicted", sha="ccc333")
    queue = IntegrationQueue(state_path=queue_path)
    queue.enqueue(key=key, ready_at="2026-03-01T12:00:00+00:00")

    not_ready = CandidateReadiness(
        key=key,
        ready_at="2026-03-01T12:00:00+00:00",
        status="NOT_READY",
        reasons=("SHA ccc333 is not reachable from origin/worktree/conflicted",),
        superseded_by=None,
    )

    outcomes = []
    runtime = IntegratorShadowRuntime(
        lease_store=IntegrationLeaseStore(state_path=lease_path),
        queue=queue,
        readiness_lookup=lambda _: not_ready,
        clearance_probe=MainBranchClearanceProbe(
            sessions_provider=lambda: (),
            session_tail_provider=lambda _: "",
            dirty_tracked_paths_provider=lambda: (),
        ),
        outcome_sink=outcomes.append,
        checkpoint_path=checkpoint_path,
        clearance_retry_seconds=0.001,
    )

    result = runtime.drain_ready_candidates(owner_session_id="integrator-1")
    assert result.lease_acquired is True
    assert len(result.outcomes) == 1
    assert result.outcomes[0].outcome == "would_block"


# ---------------------------------------------------------------------------
# Phase 6.2: Notification lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_notification_lifecycle_deployment_events() -> None:
    from teleclaude_events.cartridges.notification import NotificationProjectorCartridge
    from teleclaude_events.catalog import build_default_catalog
    from teleclaude_events.db import EventDB
    from teleclaude_events.envelope import EventEnvelope, EventLevel
    from teleclaude_events.pipeline import PipelineContext

    catalog = build_default_catalog()
    db = EventDB(db_path=":memory:")
    await db.init()
    context = PipelineContext(catalog=catalog, db=db)
    projector = NotificationProjectorCartridge()

    # deployment.started creates notification
    started_event = EventEnvelope(
        event="domain.software-development.deployment.started",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        payload={"slug": "feat-x", "branch": "feat-x", "sha": "abc123", "ready_at": "2026-03-01T12:00:00+00:00"},
    )
    await projector.process(started_event, context)

    notifications = await db.list_notifications(domain="software-development")
    assert len(notifications) >= 1
    started_notif = [n for n in notifications if n["event_type"] == "domain.software-development.deployment.started"]
    assert len(started_notif) == 1
    assert started_notif[0]["human_status"] == "unseen"

    # deployment.completed resolves notification
    completed_event = EventEnvelope(
        event="domain.software-development.deployment.completed",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        payload={"slug": "feat-x", "branch": "feat-x", "sha": "abc123", "merge_commit": "deadbeef"},
    )
    await projector.process(completed_event, context)

    # Check notification was resolved (resolve_notification sets agent_status)
    notifications_after = await db.list_notifications(domain="software-development", agent_status="resolved")
    resolved = [n for n in notifications_after if "feat-x" in str(n.get("payload", ""))]
    assert len(resolved) >= 1

    await db.close()


# ---------------------------------------------------------------------------
# Phase 6.3: Regression
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_bidirectional_sync_functions_removed() -> None:
    """Verify sync_slug_todo_from_worktree_to_main and sync_slug_todo_from_main_to_worktree are gone."""
    import inspect

    import teleclaude.core.next_machine.core as core

    source = inspect.getsource(core)
    assert "sync_slug_todo_from_worktree_to_main" not in source
    assert "sync_slug_todo_from_main_to_worktree" not in source


@pytest.mark.integration
def test_post_completion_no_longer_merges_main() -> None:
    """Verify next-finalize POST_COMPLETION no longer has inline merge/push steps."""
    from teleclaude.core.next_machine.core import POST_COMPLETION

    finalize_instructions = POST_COMPLETION["next-finalize"]
    # Should not contain the old merge/push sequence
    assert "git merge --squash" not in finalize_instructions
    assert "git push origin main" not in finalize_instructions
    # Should contain the new handoff
    assert "telec todo integrate" in finalize_instructions
    assert "Integrator will process" in finalize_instructions
