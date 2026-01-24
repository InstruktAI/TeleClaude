"""Unit tests for DaemonCache."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from teleclaude.core.cache import CachedItem, DaemonCache
from teleclaude.core.models import ComputerInfo, ProjectInfo, SessionSummary, TodoInfo

# ==================== CachedItem Tests ====================


def test_cached_item_is_stale_with_zero_ttl():
    """Test TTL of 0 means always stale (always refresh)."""
    item = CachedItem({"data": "test"})
    assert item.is_stale(0) is True


def test_cached_item_is_stale_with_negative_ttl():
    """Test negative TTL means infinite (never stale)."""
    # Create item from 10 years ago
    old_timestamp = datetime.now(timezone.utc) - timedelta(days=3650)
    item = CachedItem({"data": "test"}, cached_at=old_timestamp)
    assert item.is_stale(-1) is False


def test_cached_item_is_stale_within_ttl():
    """Test item within TTL is not stale."""
    item = CachedItem({"data": "test"})
    assert item.is_stale(60) is False


def test_cached_item_is_stale_exceeds_ttl():
    """Test item older than TTL is stale."""
    old_timestamp = datetime.now(timezone.utc) - timedelta(seconds=120)
    item = CachedItem({"data": "test"}, cached_at=old_timestamp)
    assert item.is_stale(60) is True


def test_cached_item_is_stale_at_boundary():
    """Test item exactly at TTL boundary."""
    old_timestamp = datetime.now(timezone.utc) - timedelta(seconds=60)
    item = CachedItem({"data": "test"}, cached_at=old_timestamp)
    # At boundary, item is stale (age > ttl)
    assert item.is_stale(60) is True


# ==================== DaemonCache Tests ====================


def test_get_computers_auto_expires_stale_entries():
    """Test get_computers() removes stale entries automatically."""
    cache = DaemonCache()

    # Add fresh computer
    fresh_computer = ComputerInfo(name="fresh", status="online")
    cache.update_computer(fresh_computer)

    # Add stale computer (cached 120 seconds ago, TTL is 60s)
    stale_timestamp = datetime.now(timezone.utc) - timedelta(seconds=120)
    stale_computer = ComputerInfo(name="stale", status="online")
    cache._computers["stale"] = CachedItem(stale_computer, cached_at=stale_timestamp)

    # get_computers should auto-expire stale entry
    computers = cache.get_computers()
    assert len(computers) == 1
    assert computers[0].name == "fresh"

    # Verify stale entry was removed from cache
    assert "stale" not in cache._computers


def test_get_sessions_filters_by_computer():
    """Test get_sessions() filters by computer parameter."""
    cache = DaemonCache()

    cache.update_session(
        SessionSummary(
            session_id="sess-1",
            computer="local",
            title="Local",
            last_input_origin="cli",
            project_path="~",
            thinking_mode="slow",
            active_agent=None,
            status="active",
        )
    )
    cache.update_session(
        SessionSummary(
            session_id="sess-2",
            computer="remote",
            title="Remote",
            last_input_origin="cli",
            project_path="~",
            thinking_mode="slow",
            active_agent=None,
            status="active",
        )
    )

    # Get all sessions
    all_sessions = cache.get_sessions()
    assert len(all_sessions) == 2

    # Filter by computer
    local_sessions = cache.get_sessions(computer="local")
    assert len(local_sessions) == 1
    assert local_sessions[0].session_id == "sess-1"


def test_update_computer_notifies_subscribers():
    """Test update_computer() notifies subscribers."""
    cache = DaemonCache()
    callback = MagicMock()
    callback.__name__ = "test_callback"  # Add __name__ for logger
    cache.subscribe(callback)

    computer = ComputerInfo(name="test", status="online")
    cache.update_computer(computer)

    callback.assert_called_once_with("computer_updated", computer)


def test_update_session_notifies_subscribers():
    """Test update_session() notifies subscribers."""
    cache = DaemonCache()
    callback = MagicMock()
    callback.__name__ = "test_callback"
    cache.subscribe(callback)

    session = SessionSummary(
        session_id="sess-123",
        computer="local",
        title="Test",
        last_input_origin="cli",
        project_path="~",
        thinking_mode="slow",
        active_agent=None,
        status="active",
    )
    cache.update_session(session)

    callback.assert_called_once_with("session_started", session)

    # Update same session again should emit session_updated
    callback.reset_mock()
    cache.update_session(session)
    callback.assert_called_once_with("session_updated", session)


def test_remove_session_notifies_subscribers():
    """Test remove_session() notifies subscribers."""
    cache = DaemonCache()
    callback = MagicMock()
    callback.__name__ = "test_callback"
    cache.subscribe(callback)

    # Add then remove session
    session = SessionSummary(
        session_id="sess-123",
        computer="local",
        title="Test",
        last_input_origin="cli",
        project_path="~",
        thinking_mode="slow",
        active_agent=None,
        status="active",
    )
    cache.update_session(session)
    callback.reset_mock()  # Clear the update notification

    cache.remove_session("sess-123")

    callback.assert_called_once_with("session_closed", {"session_id": "sess-123"})


def test_apply_projects_snapshot_dedupes_notifications():
    """Apply snapshot should notify only on changes."""
    cache = DaemonCache()
    callback = MagicMock()
    callback.__name__ = "test_callback"
    cache.subscribe(callback)

    projects = [
        ProjectInfo(name="Proj", path="/tmp/proj", description="Test"),
    ]

    changed = cache.apply_projects_snapshot("remote", projects)
    assert changed is True
    callback.assert_called_once_with("projects_snapshot", {"computer": "remote", "version": 1})

    callback.reset_mock()
    changed = cache.apply_projects_snapshot("remote", projects)
    assert changed is False
    callback.assert_not_called()
    assert "sess-123" not in cache._sessions


def test_set_projects_notifies_subscribers():
    """Test set_projects() notifies subscribers."""
    cache = DaemonCache()
    callback = MagicMock()
    callback.__name__ = "test_callback"
    cache.subscribe(callback)

    projects = [ProjectInfo(name="proj1", path="/path1", description="Test")]
    cache.set_projects("local", projects)

    callback.assert_called_once_with("projects_updated", {"computer": "local", "projects": projects})


def test_set_todos_notifies_subscribers():
    """Test set_todos() notifies subscribers."""
    cache = DaemonCache()
    callback = MagicMock()
    callback.__name__ = "test_callback"
    cache.subscribe(callback)

    todos = [TodoInfo(slug="todo-1", status="pending", description="Test")]
    cache.set_todos("local", "/path", todos)

    callback.assert_called_once_with(
        "todos_updated",
        {"computer": "local", "project_path": "/path", "todos": todos},
    )


def test_set_interest_per_computer():
    """Test set_interest() registers interest per computer."""
    cache = DaemonCache()

    cache.set_interest("sessions", "raspi")
    cache.set_interest("sessions", "macbook")
    cache.set_interest("projects", "raspi")

    # Check interest for specific computers
    assert cache.has_interest("sessions", "raspi")
    assert cache.has_interest("sessions", "macbook")
    assert cache.has_interest("projects", "raspi")
    assert not cache.has_interest("projects", "macbook")

    # Get interested computers
    assert set(cache.get_interested_computers("sessions")) == {"raspi", "macbook"}
    assert cache.get_interested_computers("projects") == ["raspi"]


def test_notify_handles_callback_exception():
    """Test _notify() catches and logs subscriber exceptions without crashing."""
    cache = DaemonCache()

    # Add failing callback
    failing_callback = MagicMock(side_effect=Exception("Callback error"))
    failing_callback.__name__ = "failing_callback"
    cache.subscribe(failing_callback)

    # Add successful callback
    success_callback = MagicMock()
    success_callback.__name__ = "success_callback"
    cache.subscribe(success_callback)

    # Trigger notification - should not raise exception
    cache.update_computer(ComputerInfo(name="test", status="online"))

    # Both callbacks should have been called despite one failing
    assert failing_callback.call_count == 1
    assert success_callback.call_count == 1


def test_get_projects_filters_stale_entries():
    """Test get_projects() filters out stale entries."""
    cache = DaemonCache()

    # Add fresh project
    fresh_project = ProjectInfo(name="fresh", path="/fresh", description="Fresh")
    cache._projects["local:/fresh"] = CachedItem(fresh_project)

    # Add stale project (cached 400 seconds ago, TTL is 300s)
    stale_timestamp = datetime.now(timezone.utc) - timedelta(seconds=400)
    stale_project = ProjectInfo(name="stale", path="/stale", description="Stale")
    cache._projects["local:/stale"] = CachedItem(stale_project, cached_at=stale_timestamp)

    # get_projects should filter out stale entry
    projects = cache.get_projects()
    assert len(projects) == 1
    assert projects[0].name == "fresh"


def test_get_projects_includes_stale_when_requested():
    """Test get_projects(include_stale=True) includes stale entries."""
    cache = DaemonCache()

    stale_timestamp = datetime.now(timezone.utc) - timedelta(seconds=400)
    stale_project = ProjectInfo(name="stale", path="/stale", description="Stale")
    cache._projects["local:/stale"] = CachedItem(stale_project, cached_at=stale_timestamp)

    projects = cache.get_projects(include_stale=True)
    assert len(projects) == 1
    assert projects[0].name == "stale"


def test_get_todos_returns_empty_for_stale_data():
    """Test get_todos() returns empty list for stale data."""
    cache = DaemonCache()

    # Add stale todos (cached 400 seconds ago, TTL is 300s)
    stale_timestamp = datetime.now(timezone.utc) - timedelta(seconds=400)
    todos = [TodoInfo(slug="todo-1", status="pending")]
    cache._todos["local:/path"] = CachedItem(todos, cached_at=stale_timestamp)

    # get_todos should return empty list for stale data
    result = cache.get_todos("local", "/path")
    assert result == []


def test_get_todo_entries_include_stale():
    """Test get_todo_entries(include_stale=True) returns stale entries with context."""
    cache = DaemonCache()

    stale_timestamp = datetime.now(timezone.utc) - timedelta(seconds=400)
    todos = [TodoInfo(slug="todo-1", status="pending")]
    cache._todos["remote:/path"] = CachedItem(todos, cached_at=stale_timestamp)

    entries = cache.get_todo_entries(include_stale=True)
    assert len(entries) == 1
    assert entries[0].computer == "remote"
    assert entries[0].project_path == "/path"
    assert entries[0].is_stale is True


def test_invalidate_removes_from_cache():
    """Test invalidate() removes key from cache."""
    cache = DaemonCache()

    # Add data to all caches
    cache.update_computer(ComputerInfo(name="test", status="online"))
    cache.update_session(
        SessionSummary(
            session_id="sess-123",
            computer="local",
            title="Test",
            last_input_origin="cli",
            project_path="~",
            thinking_mode="slow",
            active_agent=None,
            status="active",
        )
    )
    cache.set_projects("local", [ProjectInfo(name="proj", path="/path", description="Test")])

    # Invalidate computer
    cache.invalidate("test")
    assert "test" not in cache._computers

    # Invalidate session
    cache.invalidate("sess-123")
    assert "sess-123" not in cache._sessions


def test_invalidate_all_clears_everything():
    """Test invalidate_all() clears all caches."""
    cache = DaemonCache()

    # Add data to all caches
    cache.update_computer(ComputerInfo(name="test", status="online"))
    cache.update_session(
        SessionSummary(
            session_id="sess-123",
            computer="local",
            title="Test",
            last_input_origin="cli",
            project_path="~",
            thinking_mode="slow",
            active_agent=None,
            status="active",
        )
    )
    cache.set_projects("local", [ProjectInfo(name="proj", path="/path", description="Test")])
    cache.set_todos("local", "/path", [TodoInfo(slug="todo-1", status="pending")])

    # Clear everything
    cache.invalidate_all()

    assert len(cache._computers) == 0
    assert len(cache._sessions) == 0
    assert len(cache._projects) == 0
    assert len(cache._todos) == 0


def test_subscribe_and_unsubscribe():
    """Test subscribe() and unsubscribe() manage subscriber set."""
    cache = DaemonCache()
    callback = MagicMock()
    callback.__name__ = "test_callback"

    cache.subscribe(callback)
    assert callback in cache._subscribers

    cache.unsubscribe(callback)
    assert callback not in cache._subscribers


def test_remove_interest():
    """Test remove_interest() removes per-computer interest."""
    cache = DaemonCache()

    cache.set_interest("sessions", "raspi")
    cache.set_interest("sessions", "macbook")

    assert cache.has_interest("sessions", "raspi")
    assert cache.has_interest("sessions", "macbook")

    # Remove interest for one computer
    cache.remove_interest("sessions", "raspi")

    assert not cache.has_interest("sessions", "raspi")
    assert cache.has_interest("sessions", "macbook")

    # Remove last computer should clean up the data type
    cache.remove_interest("sessions", "macbook")
    assert cache.get_interested_computers("sessions") == []


def test_is_stale_returns_true_for_missing_key():
    """Test is_stale() returns True for non-existent key."""
    cache = DaemonCache()
    assert cache.is_stale("nonexistent", 60) is True


def test_get_projects_filters_by_computer():
    """Test get_projects() filters by computer prefix."""
    cache = DaemonCache()

    cache.set_projects("local", [ProjectInfo(name="local-proj", path="/local", description="Local")])
    cache.set_projects("remote", [ProjectInfo(name="remote-proj", path="/remote", description="Remote")])

    # Get all projects
    all_projects = cache.get_projects()
    assert len(all_projects) == 2

    # Filter by computer
    local_projects = cache.get_projects(computer="local")
    assert len(local_projects) == 1
    assert local_projects[0].name == "local-proj"


def test_cached_item_uses_current_time_by_default():
    """Test CachedItem defaults cached_at to now."""
    item = CachedItem({"data": "test"})
    age = (datetime.now(timezone.utc) - item.cached_at).total_seconds()
    assert age < 1  # Should be less than 1 second old


def test_get_interested_computers_returns_list():
    """Test get_interested_computers() returns a list that can be safely modified."""
    cache = DaemonCache()
    cache.set_interest("sessions", "raspi")
    cache.set_interest("sessions", "macbook")

    # Get computers and modify the list
    computers = cache.get_interested_computers("sessions")
    computers.append("tampered")

    # Original cache should be unchanged
    assert set(cache.get_interested_computers("sessions")) == {"raspi", "macbook"}
