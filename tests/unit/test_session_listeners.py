"""Unit tests for session_listeners module (SQLite-backed)."""

from datetime import datetime, timedelta, timezone

import pytest

from teleclaude.core.session_listeners import (
    cleanup_caller_listeners,
    count_listeners,
    get_all_listeners,
    get_listeners,
    get_listeners_for_caller,
    get_stale_targets,
    notify_stop,
    pop_listeners,
    register_listener,
    unregister_listener,
)


@pytest.fixture(autouse=True)
async def _init_db():
    """Initialize DB schema so session_listeners table exists."""
    from teleclaude.core.db import db

    await db.initialize()
    yield


class TestRegisterListener:
    """Tests for register_listener function."""

    @pytest.mark.asyncio
    async def test_register_new_listener(self):
        """Should register a new listener and return True."""
        result = await register_listener(
            target_session_id="target-123",
            caller_session_id="caller-456",
            caller_tmux_session="tc_caller",
        )

        assert result is True
        assert await count_listeners() == 1

    @pytest.mark.asyncio
    async def test_register_duplicate_caller_target_pair_rejected(self):
        """Should reject duplicate caller-target pairs."""
        await register_listener("target-123", "caller-456", "tc_caller")

        # Same caller trying to register again for same target
        result = await register_listener("target-123", "caller-456", "tc_caller")

        assert result is False
        assert await count_listeners() == 1

    @pytest.mark.asyncio
    async def test_multiple_callers_same_target(self):
        """Should allow multiple callers to wait for the same target."""
        await register_listener("target-123", "caller-A", "tc_callerA")
        await register_listener("target-123", "caller-B", "tc_callerB")
        await register_listener("target-123", "caller-C", "tc_callerC")

        assert await count_listeners() == 3
        listeners = await get_listeners("target-123")
        assert len(listeners) == 3

    @pytest.mark.asyncio
    async def test_same_caller_multiple_targets(self):
        """Should allow same caller to wait for multiple targets."""
        await register_listener("target-1", "caller-A", "tc_callerA")
        await register_listener("target-2", "caller-A", "tc_callerA")
        await register_listener("target-3", "caller-A", "tc_callerA")

        assert await count_listeners() == 3


class TestGetListeners:
    """Tests for get_listeners function."""

    @pytest.mark.asyncio
    async def test_get_listeners_nonexistent_target(self):
        """Should return empty list for nonexistent target."""
        listeners = await get_listeners("nonexistent")
        assert listeners == []


@pytest.mark.asyncio
async def test_notify_stop_delivers_message(monkeypatch):
    """notify_stop should deliver a message to the caller session."""
    await register_listener("target-123", "caller-A", "tc_callerA")
    delivered: dict[str, str] = {}

    async def fake_deliver(session_id: str, tmux_session: str, message: str) -> bool:
        delivered["session_id"] = session_id
        delivered["tmux_session"] = tmux_session
        delivered["message"] = message
        return True

    monkeypatch.setattr("teleclaude.core.tmux_delivery.deliver_listener_message", fake_deliver)

    count = await notify_stop("target-123", "Local", title="Test Title")

    assert count == 1
    assert delivered["session_id"] == "caller-A"
    assert delivered["tmux_session"] == "tc_callerA"
    assert "teleclaude__get_session_data" in delivered["message"]
    assert "target-123" in delivered["message"]


class TestPopListeners:
    """Tests for pop_listeners function (one-shot pattern)."""

    @pytest.mark.asyncio
    async def test_pop_removes_all_listeners_for_target(self):
        """Should remove and return all listeners for a target."""
        await register_listener("target-123", "caller-A", "tc_callerA")
        await register_listener("target-123", "caller-B", "tc_callerB")

        popped = await pop_listeners("target-123")

        assert len(popped) == 2
        assert await count_listeners() == 0
        assert await get_listeners("target-123") == []

    @pytest.mark.asyncio
    async def test_pop_nonexistent_target_returns_empty(self):
        """Should return empty list for nonexistent target."""
        popped = await pop_listeners("nonexistent")
        assert popped == []

    @pytest.mark.asyncio
    async def test_pop_does_not_affect_other_targets(self):
        """Should only remove listeners for the specified target."""
        await register_listener("target-A", "caller-1", "tc_caller1")
        await register_listener("target-B", "caller-2", "tc_caller2")

        await pop_listeners("target-A")

        assert await count_listeners() == 1
        assert len(await get_listeners("target-B")) == 1


class TestCleanupCallerListeners:
    """Tests for cleanup_caller_listeners function."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_all_listeners_by_caller(self):
        """Should remove all listeners registered by a specific caller."""
        await register_listener("target-1", "caller-A", "tc_callerA")
        await register_listener("target-2", "caller-A", "tc_callerA")
        await register_listener("target-3", "caller-B", "tc_callerB")

        removed = await cleanup_caller_listeners("caller-A")

        assert removed == 2
        assert await count_listeners() == 1
        assert len(await get_listeners("target-3")) == 1

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_caller_returns_zero(self):
        """Should return 0 for nonexistent caller."""
        await register_listener("target-1", "caller-A", "tc_callerA")

        removed = await cleanup_caller_listeners("nonexistent")

        assert removed == 0
        assert await count_listeners() == 1

    @pytest.mark.asyncio
    async def test_cleanup_removes_empty_target_entries(self):
        """Should clean up target entries after removing listeners."""
        await register_listener("target-1", "caller-A", "tc_callerA")

        await cleanup_caller_listeners("caller-A")

        all_listeners = await get_all_listeners()
        assert "target-1" not in all_listeners


class TestGetListenersForCaller:
    """Tests for get_listeners_for_caller function."""

    @pytest.mark.asyncio
    async def test_get_all_listeners_for_caller(self):
        """Should return all listeners registered by a caller."""
        await register_listener("target-1", "caller-A", "tc_callerA")
        await register_listener("target-2", "caller-A", "tc_callerA")
        await register_listener("target-3", "caller-B", "tc_callerB")

        listeners = await get_listeners_for_caller("caller-A")

        assert len(listeners) == 2
        assert all(listener.caller_session_id == "caller-A" for listener in listeners)

    @pytest.mark.asyncio
    async def test_get_listeners_for_nonexistent_caller(self):
        """Should return empty list for nonexistent caller."""
        listeners = await get_listeners_for_caller("nonexistent")
        assert listeners == []


class TestListenerDataIntegrity:
    """Tests for listener data integrity."""

    @pytest.mark.asyncio
    async def test_listener_stores_all_fields(self):
        """Should store all fields correctly."""
        await register_listener("target-123", "caller-456", "tc_caller_session")

        listeners = await get_listeners("target-123")
        assert len(listeners) == 1

        listener = listeners[0]
        assert listener.target_session_id == "target-123"
        assert listener.caller_session_id == "caller-456"
        assert listener.caller_tmux_session == "tc_caller_session"
        assert listener.registered_at is not None


class TestGetStaleTargets:
    """Tests for get_stale_targets function (health check support)."""

    @pytest.mark.asyncio
    async def test_fresh_listeners_not_stale(self):
        """Should not return targets with fresh listeners."""
        await register_listener("target-123", "caller-456", "tc_caller")

        stale = await get_stale_targets(max_age_minutes=10)
        assert stale == []

    @pytest.mark.asyncio
    async def test_old_listeners_are_stale(self):
        """Should return targets with old listeners."""
        await register_listener("target-123", "caller-456", "tc_caller")

        # Manually age the listener via DB
        from teleclaude.core.db import db

        old_time = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        await db.reset_listener_timestamps("target-123", old_time)

        stale = await get_stale_targets(max_age_minutes=10)
        assert stale == ["target-123"]

    @pytest.mark.asyncio
    async def test_stale_check_resets_timestamp(self):
        """Should reset timestamp after finding stale target."""
        await register_listener("target-123", "caller-456", "tc_caller")

        # Manually age the listener via DB
        from teleclaude.core.db import db

        old_time = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        await db.reset_listener_timestamps("target-123", old_time)

        # First call finds it stale
        stale = await get_stale_targets(max_age_minutes=10)
        assert stale == ["target-123"]

        # Timestamp was reset, so second call finds nothing
        stale = await get_stale_targets(max_age_minutes=10)
        assert stale == []

    @pytest.mark.asyncio
    async def test_multiple_stale_targets(self):
        """Should return all stale targets."""
        await register_listener("target-A", "caller-1", "tc_caller1")
        await register_listener("target-B", "caller-2", "tc_caller2")
        await register_listener("target-C", "caller-3", "tc_caller3")

        # Age some listeners via DB
        from teleclaude.core.db import db

        old_time = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        await db.reset_listener_timestamps("target-A", old_time)
        await db.reset_listener_timestamps("target-C", old_time)
        # target-B stays fresh

        stale = await get_stale_targets(max_age_minutes=10)
        assert sorted(stale) == ["target-A", "target-C"]


class TestUnregisterListener:
    """Tests for unregister_listener function."""

    @pytest.mark.asyncio
    async def test_unregister_existing_listener(self):
        """Should unregister an existing listener and return True."""
        await register_listener("target-123", "caller-456", "tc_caller")
        assert await count_listeners() == 1

        result = await unregister_listener("target-123", "caller-456")

        assert result is True
        assert await count_listeners() == 0

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_target_returns_false(self):
        """Should return False if target doesn't exist."""
        result = await unregister_listener("nonexistent-target", "caller-456")

        assert result is False

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_caller_returns_false(self):
        """Should return False if caller not listening to target."""
        await register_listener("target-123", "caller-A", "tc_callerA")

        result = await unregister_listener("target-123", "caller-B")

        assert result is False
        assert await count_listeners() == 1  # Original listener still there

    @pytest.mark.asyncio
    async def test_unregister_specific_caller_leaves_others(self):
        """Should only remove the specific caller's listener."""
        await register_listener("target-123", "caller-A", "tc_callerA")
        await register_listener("target-123", "caller-B", "tc_callerB")
        assert await count_listeners() == 2

        result = await unregister_listener("target-123", "caller-A")

        assert result is True
        assert await count_listeners() == 1

        # Verify caller-B's listener still exists
        listeners = await get_listeners("target-123")
        assert len(listeners) == 1
        assert listeners[0].caller_session_id == "caller-B"
