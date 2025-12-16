"""Unit tests for session_listeners module."""

from datetime import datetime, timedelta

import pytest

from teleclaude.core.session_listeners import (
    cleanup_caller_listeners,
    count_listeners,
    get_all_listeners,
    get_listeners,
    get_listeners_for_caller,
    get_stale_targets,
    pop_listeners,
    register_listener,
    unregister_listener,
)


@pytest.fixture(autouse=True)
def clear_listeners():
    """Clear all listeners before and after each test."""
    # Import the module-level dict to clear it
    from teleclaude.core import session_listeners

    session_listeners._listeners.clear()
    yield
    session_listeners._listeners.clear()


class TestRegisterListener:
    """Tests for register_listener function."""

    def test_register_new_listener(self):
        """Should register a new listener and return True."""
        result = register_listener(
            target_session_id="target-123",
            caller_session_id="caller-456",
            caller_tmux_session="tc_caller",
        )

        assert result is True
        assert count_listeners() == 1

    def test_register_duplicate_caller_target_pair_rejected(self):
        """Should reject duplicate caller-target pairs."""
        register_listener("target-123", "caller-456", "tc_caller")

        # Same caller trying to register again for same target
        result = register_listener("target-123", "caller-456", "tc_caller")

        assert result is False
        assert count_listeners() == 1

    def test_multiple_callers_same_target(self):
        """Should allow multiple callers to wait for the same target."""
        register_listener("target-123", "caller-A", "tc_callerA")
        register_listener("target-123", "caller-B", "tc_callerB")
        register_listener("target-123", "caller-C", "tc_callerC")

        assert count_listeners() == 3
        listeners = get_listeners("target-123")
        assert len(listeners) == 3

    def test_same_caller_multiple_targets(self):
        """Should allow same caller to wait for multiple targets."""
        register_listener("target-1", "caller-A", "tc_callerA")
        register_listener("target-2", "caller-A", "tc_callerA")
        register_listener("target-3", "caller-A", "tc_callerA")

        assert count_listeners() == 3


class TestGetListeners:
    """Tests for get_listeners function."""

    def test_get_listeners_returns_copy(self):
        """Should return a copy, not the original list."""
        register_listener("target-123", "caller-456", "tc_caller")

        listeners = get_listeners("target-123")
        listeners.clear()  # Modify the returned list

        # Original should be unaffected
        assert count_listeners() == 1

    def test_get_listeners_nonexistent_target(self):
        """Should return empty list for nonexistent target."""
        listeners = get_listeners("nonexistent")
        assert listeners == []


class TestPopListeners:
    """Tests for pop_listeners function (one-shot pattern)."""

    def test_pop_removes_all_listeners_for_target(self):
        """Should remove and return all listeners for a target."""
        register_listener("target-123", "caller-A", "tc_callerA")
        register_listener("target-123", "caller-B", "tc_callerB")

        popped = pop_listeners("target-123")

        assert len(popped) == 2
        assert count_listeners() == 0
        assert get_listeners("target-123") == []

    def test_pop_nonexistent_target_returns_empty(self):
        """Should return empty list for nonexistent target."""
        popped = pop_listeners("nonexistent")
        assert popped == []

    def test_pop_does_not_affect_other_targets(self):
        """Should only remove listeners for the specified target."""
        register_listener("target-A", "caller-1", "tc_caller1")
        register_listener("target-B", "caller-2", "tc_caller2")

        pop_listeners("target-A")

        assert count_listeners() == 1
        assert len(get_listeners("target-B")) == 1


class TestCleanupCallerListeners:
    """Tests for cleanup_caller_listeners function."""

    def test_cleanup_removes_all_listeners_by_caller(self):
        """Should remove all listeners registered by a specific caller."""
        register_listener("target-1", "caller-A", "tc_callerA")
        register_listener("target-2", "caller-A", "tc_callerA")
        register_listener("target-3", "caller-B", "tc_callerB")

        removed = cleanup_caller_listeners("caller-A")

        assert removed == 2
        assert count_listeners() == 1
        assert len(get_listeners("target-3")) == 1

    def test_cleanup_nonexistent_caller_returns_zero(self):
        """Should return 0 for nonexistent caller."""
        register_listener("target-1", "caller-A", "tc_callerA")

        removed = cleanup_caller_listeners("nonexistent")

        assert removed == 0
        assert count_listeners() == 1

    def test_cleanup_removes_empty_target_entries(self):
        """Should clean up empty target entries after removing listeners."""
        register_listener("target-1", "caller-A", "tc_callerA")

        cleanup_caller_listeners("caller-A")

        # The target entry should be removed entirely
        all_listeners = get_all_listeners()
        assert "target-1" not in all_listeners


class TestGetListenersForCaller:
    """Tests for get_listeners_for_caller function."""

    def test_get_all_listeners_for_caller(self):
        """Should return all listeners registered by a caller."""
        register_listener("target-1", "caller-A", "tc_callerA")
        register_listener("target-2", "caller-A", "tc_callerA")
        register_listener("target-3", "caller-B", "tc_callerB")

        listeners = get_listeners_for_caller("caller-A")

        assert len(listeners) == 2
        assert all(listener.caller_session_id == "caller-A" for listener in listeners)

    def test_get_listeners_for_nonexistent_caller(self):
        """Should return empty list for nonexistent caller."""
        listeners = get_listeners_for_caller("nonexistent")
        assert listeners == []


class TestListenerDataIntegrity:
    """Tests for listener data integrity."""

    def test_listener_stores_all_fields(self):
        """Should store all fields correctly."""
        register_listener("target-123", "caller-456", "tc_caller_session")

        listeners = get_listeners("target-123")
        assert len(listeners) == 1

        listener = listeners[0]
        assert listener.target_session_id == "target-123"
        assert listener.caller_session_id == "caller-456"
        assert listener.caller_tmux_session == "tc_caller_session"
        assert listener.registered_at is not None

    def test_get_all_listeners_returns_copy(self):
        """Should return a deep copy of all listeners."""
        register_listener("target-1", "caller-A", "tc_callerA")
        register_listener("target-2", "caller-B", "tc_callerB")

        all_listeners = get_all_listeners()
        all_listeners.clear()

        # Original should be unaffected
        assert count_listeners() == 2


class TestGetStaleTargets:
    """Tests for get_stale_targets function (health check support)."""

    def test_fresh_listeners_not_stale(self):
        """Should not return targets with fresh listeners."""
        register_listener("target-123", "caller-456", "tc_caller")

        stale = get_stale_targets(max_age_minutes=10)
        assert stale == []

    def test_old_listeners_are_stale(self):
        """Should return targets with old listeners."""
        register_listener("target-123", "caller-456", "tc_caller")

        # Manually age the listener
        from teleclaude.core import session_listeners

        listeners = session_listeners._listeners["target-123"]
        listeners[0].registered_at = datetime.now() - timedelta(minutes=15)

        stale = get_stale_targets(max_age_minutes=10)
        assert stale == ["target-123"]

    def test_stale_check_resets_timestamp(self):
        """Should reset timestamp after finding stale target."""
        register_listener("target-123", "caller-456", "tc_caller")

        # Manually age the listener
        from teleclaude.core import session_listeners

        listeners = session_listeners._listeners["target-123"]
        old_time = datetime.now() - timedelta(minutes=15)
        listeners[0].registered_at = old_time

        # First call finds it stale
        stale = get_stale_targets(max_age_minutes=10)
        assert stale == ["target-123"]

        # Timestamp was reset, so second call finds nothing
        stale = get_stale_targets(max_age_minutes=10)
        assert stale == []

    def test_multiple_stale_targets(self):
        """Should return all stale targets."""
        register_listener("target-A", "caller-1", "tc_caller1")
        register_listener("target-B", "caller-2", "tc_caller2")
        register_listener("target-C", "caller-3", "tc_caller3")

        # Age some listeners
        from teleclaude.core import session_listeners

        old_time = datetime.now() - timedelta(minutes=15)
        session_listeners._listeners["target-A"][0].registered_at = old_time
        session_listeners._listeners["target-C"][0].registered_at = old_time
        # target-B stays fresh

        stale = get_stale_targets(max_age_minutes=10)
        assert sorted(stale) == ["target-A", "target-C"]

    def test_only_one_stale_listener_needed_per_target(self):
        """Should return target if at least one listener is stale."""
        register_listener("target-123", "caller-A", "tc_callerA")
        register_listener("target-123", "caller-B", "tc_callerB")

        # Age only one listener
        from teleclaude.core import session_listeners

        old_time = datetime.now() - timedelta(minutes=15)
        session_listeners._listeners["target-123"][0].registered_at = old_time
        # Second listener stays fresh

        stale = get_stale_targets(max_age_minutes=10)
        assert stale == ["target-123"]


class TestUnregisterListener:
    """Tests for unregister_listener function."""

    def test_unregister_existing_listener(self):
        """Should unregister an existing listener and return True."""
        register_listener("target-123", "caller-456", "tc_caller")
        assert count_listeners() == 1

        result = unregister_listener("target-123", "caller-456")

        assert result is True
        assert count_listeners() == 0

    def test_unregister_nonexistent_target_returns_false(self):
        """Should return False if target doesn't exist."""
        result = unregister_listener("nonexistent-target", "caller-456")

        assert result is False

    def test_unregister_nonexistent_caller_returns_false(self):
        """Should return False if caller not listening to target."""
        register_listener("target-123", "caller-A", "tc_callerA")

        result = unregister_listener("target-123", "caller-B")

        assert result is False
        assert count_listeners() == 1  # Original listener still there

    def test_unregister_specific_caller_leaves_others(self):
        """Should only remove the specific caller's listener."""
        register_listener("target-123", "caller-A", "tc_callerA")
        register_listener("target-123", "caller-B", "tc_callerB")
        assert count_listeners() == 2

        result = unregister_listener("target-123", "caller-A")

        assert result is True
        assert count_listeners() == 1

        # Verify caller-B's listener still exists
        listeners = get_listeners("target-123")
        assert len(listeners) == 1
        assert listeners[0].caller_session_id == "caller-B"

    def test_unregister_cleans_up_empty_target_list(self):
        """Should remove empty target list from internal storage."""
        register_listener("target-123", "caller-456", "tc_caller")

        unregister_listener("target-123", "caller-456")

        # Verify internal storage cleaned up
        from teleclaude.core import session_listeners

        assert "target-123" not in session_listeners._listeners
