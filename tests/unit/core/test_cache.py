"""Characterization tests for teleclaude.core.cache."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from teleclaude.core.cache import CachedItem, DaemonCache


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
