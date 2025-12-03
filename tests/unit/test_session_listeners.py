"""Unit tests for session_listeners module."""

import pytest

from teleclaude.core.session_listeners import (
    cleanup_caller_listeners,
    count_listeners,
    get_all_listeners,
    get_listeners,
    get_listeners_for_caller,
    pop_listeners,
    register_listener,
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
        assert all(l.caller_session_id == "caller-A" for l in listeners)

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
