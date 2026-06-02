"""Characterization tests for teleclaude.core.cache."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from teleclaude.api_models import TodoDTO
from teleclaude.core.cache import CachedItem, DaemonCache
from teleclaude.transport.cluster_publisher import ClusterPublisher

# Protocol identifiers (named-constant form per snapshot-testing policy).
SESSION_CREATED_CHANNEL = "cluster.session.created"
SESSION_UPDATED_CHANNEL = "cluster.session.updated"
SESSION_CLOSED_CHANNEL = "cluster.session.closed"


class TestCachedItem:
    @pytest.mark.unit
    def test_stores_data(self):
        item = CachedItem("some data")
        assert item.data == "some data"

    @pytest.mark.unit
    def test_cached_at_defaults_to_now(self):
        before = datetime.now(UTC)
        item = CachedItem("data")
        after = datetime.now(UTC)
        assert before <= item.cached_at <= after

    @pytest.mark.unit
    def test_is_stale_with_zero_ttl_always_true(self):
        item = CachedItem("data")
        assert item.is_stale(0) is True

    @pytest.mark.unit
    def test_is_stale_with_negative_ttl_always_false(self):
        item = CachedItem("data", cached_at=datetime(2000, 1, 1, tzinfo=UTC))
        assert item.is_stale(-1) is False

    @pytest.mark.unit
    def test_is_stale_fresh_item_within_ttl(self):
        item = CachedItem("data")
        assert item.is_stale(3600) is False

    @pytest.mark.unit
    def test_is_stale_old_item_beyond_ttl(self):
        old_time = datetime.now(UTC) - timedelta(seconds=400)
        item = CachedItem("data", cached_at=old_time)
        assert item.is_stale(300) is True


class TestDaemonCache:
    @pytest.mark.unit
    def test_get_computers_empty_initially(self):
        cache = DaemonCache()
        assert cache.get_computers() == []

    @pytest.mark.unit
    def test_get_sessions_empty_initially(self):
        cache = DaemonCache()
        assert cache.get_sessions() == []

    @pytest.mark.unit
    def test_get_todos_returns_empty_for_unknown_key(self):
        cache = DaemonCache()
        result = cache.get_todos("local", "/some/path")
        assert result == []

    @pytest.mark.unit
    def test_invalidate_all_clears_data(self):
        cache = DaemonCache()
        session = MagicMock()
        session.session_id = "sess-001"
        session.computer = "local"
        cache.update_session(session)
        cache.invalidate_all()
        assert cache.get_sessions() == []

    @pytest.mark.unit
    def test_subscribe_and_unsubscribe(self):
        cache = DaemonCache()

        def callback(key: str, data: object) -> None:
            pass

        cache.subscribe(callback)
        cache.unsubscribe(callback)
        # _subscribers: only observation point; unsubscribe returns None with no public query.
        assert callback not in cache._subscribers

    @pytest.mark.unit
    def test_interest_registration(self):
        cache = DaemonCache()
        cache.set_interest("sessions", "raspi")
        assert cache.has_interest("sessions", "raspi") is True
        assert cache.has_interest("sessions", "other") is False

    @pytest.mark.unit
    def test_remove_interest(self):
        cache = DaemonCache()
        cache.set_interest("projects", "raspi")
        cache.remove_interest("projects", "raspi")
        assert cache.has_interest("projects", "raspi") is False

    @pytest.mark.unit
    def test_get_interested_computers(self):
        cache = DaemonCache()
        cache.set_interest("sessions", "raspi")
        cache.set_interest("sessions", "macbook")
        computers = cache.get_interested_computers("sessions")
        assert "raspi" in computers
        assert "macbook" in computers

    @pytest.mark.unit
    def test_publish_workflow_change_todos_invalidates_and_notifies(self):
        cache = DaemonCache()
        todo = TodoDTO(slug="t1", status="pending", has_requirements=False, has_impl_plan=False)
        cache.set_todos("local", "/p", [todo])
        events: list[tuple[str, object]] = []
        cache.subscribe(lambda e, d: events.append((e, d)))

        cache.publish_workflow_change("todos", computer="local", project_path="/p")

        assert cache.get_todos("local", "/p") == []
        assert ("todos_updated", {"computer": "local", "project_path": "/p"}) in events

    @pytest.mark.unit
    def test_publish_workflow_change_roadmap_notifies_projects_updated(self):
        cache = DaemonCache()
        events: list[tuple[str, object]] = []
        cache.subscribe(lambda e, d: events.append((e, d)))

        cache.publish_workflow_change("roadmap", computer="local")

        assert ("projects_updated", {"computer": "local"}) in events

    @pytest.mark.unit
    def test_publish_workflow_change_skips_todo_scope_without_project_path(self):
        cache = DaemonCache()
        events: list[tuple[str, object]] = []
        cache.subscribe(lambda e, d: events.append((e, d)))

        cache.publish_workflow_change("todos", computer="local")

        assert events == []

    @pytest.mark.unit
    def test_apply_todos_snapshot_propagates_lifecycle_phase_changes(self):
        """Reconcile-only phase changes must invalidate the cache so the TUI re-renders."""
        cache = DaemonCache()
        before = TodoDTO(
            slug="t1",
            status="pending",
            has_requirements=False,
            has_impl_plan=False,
            lifecycle_phase="draft",
        )
        after = before.model_copy(update={"lifecycle_phase": "prd_drafting"})

        assert cache.apply_todos_snapshot("local", {"/p": [before]}) is True
        assert cache.apply_todos_snapshot("local", {"/p": [after]}) is True
        cached = cache.get_todos("local", "/p")
        assert cached[0].lifecycle_phase == "prd_drafting"

    @pytest.mark.unit
    def test_apply_todos_snapshot_propagates_artifact_version_total_changes(self):
        """Version-only artifact edits must invalidate snapshots even when artifact names stay fixed."""
        cache = DaemonCache()
        before = TodoDTO(
            slug="t1",
            status="pending",
            has_requirements=True,
            has_impl_plan=False,
            files=["requirements"],
            version_total=1,
        )
        after = before.model_copy(update={"version_total": 2})

        assert cache.apply_todos_snapshot("local", {"/p": [before]}) is True
        assert cache.apply_todos_snapshot("local", {"/p": [after]}) is True
        cached = cache.get_todos("local", "/p")
        assert cached[0].version_total == 2


class _RecordingPublisher(ClusterPublisher):
    """Stub publisher that records publish calls instead of touching Redis."""

    def __init__(self) -> None:
        async def _no_redis() -> object:
            raise AssertionError("redis_provider should not be invoked in unit tests")

        super().__init__(origin="MozMini", redis_provider=_no_redis)
        self.calls: list[tuple[str, dict[str, object]]] = []  # guard: loose-dict - test capture

    async def publish(
        self,
        channel: str,
        payload: dict[str, object],  # guard: loose-dict - matches base signature
    ) -> bool:
        self.calls.append((channel, payload))
        return True


def _make_session(session_id: str = "sess-001", computer: str = "MozMini") -> MagicMock:
    session = MagicMock()
    session.session_id = session_id
    session.computer = computer
    session.title = "test"
    session.to_dict.return_value = {"session_id": session_id, "computer": computer, "title": "test"}
    return session


class TestClusterPublish:
    @pytest.mark.unit
    async def test_update_session_without_publisher_is_silent(self) -> None:
        cache = DaemonCache()
        session = _make_session()

        # Must not raise even with no publisher attached.
        cache.update_session(session)

        assert cache.get_sessions() == [session]

    @pytest.mark.unit
    async def test_update_session_publishes_created_channel_for_new_session(self) -> None:
        cache = DaemonCache()
        publisher = _RecordingPublisher()
        cache.attach_cluster_publisher(publisher)
        session = _make_session()

        cache.update_session(session)
        await asyncio.sleep(0)  # let the create_task drain

        assert len(publisher.calls) == 1
        channel, payload = publisher.calls[0]
        assert channel == SESSION_CREATED_CHANNEL
        assert payload["session_id"] == session.session_id

    @pytest.mark.unit
    async def test_update_session_publishes_updated_channel_for_existing_session(self) -> None:
        cache = DaemonCache()
        publisher = _RecordingPublisher()
        cache.attach_cluster_publisher(publisher)
        session = _make_session()

        cache.update_session(session)
        cache.update_session(session)
        await asyncio.sleep(0)

        assert publisher.calls[0][0] == SESSION_CREATED_CHANNEL
        assert publisher.calls[1][0] == SESSION_UPDATED_CHANNEL

    @pytest.mark.unit
    async def test_update_session_from_cluster_does_not_republish(self) -> None:
        """Round-trip back-leg must not re-emit, or events loop indefinitely."""
        cache = DaemonCache()
        publisher = _RecordingPublisher()
        cache.attach_cluster_publisher(publisher)
        session = _make_session()

        cache.update_session(session, from_cluster=True)
        await asyncio.sleep(0)

        assert publisher.calls == []

    @pytest.mark.unit
    async def test_remove_session_publishes_closed_channel(self) -> None:
        cache = DaemonCache()
        publisher = _RecordingPublisher()
        cache.attach_cluster_publisher(publisher)
        session = _make_session()
        cache.update_session(session, from_cluster=True)  # seed without publish

        cache.remove_session(session.session_id)
        await asyncio.sleep(0)

        assert len(publisher.calls) == 1
        channel, payload = publisher.calls[0]
        assert channel == SESSION_CLOSED_CHANNEL
        assert payload == {"session_id": session.session_id}

    @pytest.mark.unit
    async def test_remove_session_from_cluster_does_not_republish(self) -> None:
        cache = DaemonCache()
        publisher = _RecordingPublisher()
        cache.attach_cluster_publisher(publisher)
        session = _make_session()
        cache.update_session(session, from_cluster=True)

        cache.remove_session(session.session_id, from_cluster=True)
        await asyncio.sleep(0)

        assert publisher.calls == []

    @pytest.mark.unit
    def test_publish_cluster_without_running_loop_logs_warning_and_drops(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When a publisher is attached but no event loop is running, the publish is dropped — but loudly.

        Production cache writers always run under asyncio; this branch should be unreachable.
        If it ever fires (e.g. an unforeseen sync entry point), the warning surfaces the loss
        so it isn't silent. The bug we guard against is the silent drop, not specific wording —
        per snapshot-testing procedure, the non-empty WARNING guard is the right shape here.
        """
        cache = DaemonCache()
        publisher = _RecordingPublisher()
        cache.attach_cluster_publisher(publisher)
        session = _make_session()

        # Note: this test is intentionally sync — no event loop is running.
        with caplog.at_level("WARNING"):
            cache.update_session(session)

        # Local cache write still succeeded (publish loss must not block the cache contract).
        assert cache.get_sessions() == [session]
        # The publish was NOT silently dropped — at least one WARNING was emitted.
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warnings
        assert publisher.calls == []
