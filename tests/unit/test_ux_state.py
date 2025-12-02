"""Unit tests for UX state management."""

import json

import aiosqlite
import pytest


@pytest.fixture
async def test_db():
    """Create in-memory test database with required tables."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row

    # Create sessions table
    await db.execute("""
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            ux_state TEXT
        )
    """)

    # Create system_settings table
    await db.execute("""
        CREATE TABLE system_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
    """)

    await db.commit()
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_get_session_ux_state_loads_from_db(test_db):
    """Test that get_session_ux_state loads state from database."""
    from teleclaude.core.ux_state import get_session_ux_state

    # Insert session with UX state
    ux_data = {
        "output_message_id": "msg-123",
        "polling_active": True,
        "notification_sent": True,
    }
    await test_db.execute(
        "INSERT INTO sessions (session_id, ux_state) VALUES (?, ?)",
        ("test-session-123", json.dumps(ux_data)),
    )
    await test_db.commit()

    state = await get_session_ux_state(test_db, "test-session-123")

    assert state.output_message_id == "msg-123"
    assert state.polling_active is True
    assert state.notification_sent is True


@pytest.mark.asyncio
async def test_get_session_ux_state_returns_defaults_when_missing(test_db):
    """Test that get_session_ux_state returns defaults when no state stored."""
    from teleclaude.core.ux_state import get_session_ux_state

    # Insert session with NULL ux_state
    await test_db.execute(
        "INSERT INTO sessions (session_id, ux_state) VALUES (?, ?)",
        ("test-session-123", None),
    )
    await test_db.commit()

    state = await get_session_ux_state(test_db, "test-session-123")

    assert state.output_message_id is None
    assert state.polling_active is False
    assert state.notification_sent is False
    assert state.pending_deletions == []


@pytest.mark.asyncio
async def test_get_session_ux_state_handles_invalid_json(test_db):
    """Test that get_session_ux_state handles corrupted JSON gracefully."""
    from teleclaude.core.ux_state import get_session_ux_state

    # Insert session with invalid JSON
    await test_db.execute(
        "INSERT INTO sessions (session_id, ux_state) VALUES (?, ?)",
        ("test-session-123", "not valid json {{{"),
    )
    await test_db.commit()

    # Should return defaults, not crash
    state = await get_session_ux_state(test_db, "test-session-123")

    assert state.output_message_id is None
    assert state.polling_active is False


@pytest.mark.asyncio
async def test_update_session_ux_state_merges_with_existing(test_db):
    """Test that update_session_ux_state merges partial updates."""
    from teleclaude.core.ux_state import get_session_ux_state, update_session_ux_state

    # Insert session with existing state
    existing_data = {
        "output_message_id": "msg-123",
        "polling_active": True,
        "notification_sent": False,
    }
    await test_db.execute(
        "INSERT INTO sessions (session_id, ux_state) VALUES (?, ?)",
        ("test-session-123", json.dumps(existing_data)),
    )
    await test_db.commit()

    # Update only one field
    await update_session_ux_state(test_db, "test-session-123", notification_sent=True)

    # Verify other fields preserved
    state = await get_session_ux_state(test_db, "test-session-123")
    assert state.output_message_id == "msg-123"  # Preserved
    assert state.polling_active is True  # Preserved
    assert state.notification_sent is True  # Updated


@pytest.mark.asyncio
async def test_update_session_ux_state_respects_sentinel_value(test_db):
    """Test that update_session_ux_state only updates provided fields."""
    from teleclaude.core.ux_state import get_session_ux_state, update_session_ux_state

    # Insert session with existing state
    existing_data = {
        "output_message_id": "msg-123",
        "polling_active": True,
    }
    await test_db.execute(
        "INSERT INTO sessions (session_id, ux_state) VALUES (?, ?)",
        ("test-session-123", json.dumps(existing_data)),
    )
    await test_db.commit()

    # Update with only polling_active (output_message_id not provided = _UNSET)
    await update_session_ux_state(test_db, "test-session-123", polling_active=False)

    state = await get_session_ux_state(test_db, "test-session-123")
    assert state.output_message_id == "msg-123"  # Not touched
    assert state.polling_active is False  # Updated


@pytest.mark.asyncio
async def test_update_session_ux_state_allows_none_values(test_db):
    """Test that update_session_ux_state can set fields to None."""
    from teleclaude.core.ux_state import get_session_ux_state, update_session_ux_state

    # Insert session with existing state
    existing_data = {
        "output_message_id": "msg-123",
    }
    await test_db.execute(
        "INSERT INTO sessions (session_id, ux_state) VALUES (?, ?)",
        ("test-session-123", json.dumps(existing_data)),
    )
    await test_db.commit()

    # Explicitly set to None (not _UNSET)
    await update_session_ux_state(test_db, "test-session-123", output_message_id=None)

    state = await get_session_ux_state(test_db, "test-session-123")
    assert state.output_message_id is None  # Now None


@pytest.mark.asyncio
async def test_get_system_ux_state_loads_from_system_settings(test_db):
    """Test that get_system_ux_state loads from system_settings table."""
    from teleclaude.core.ux_state import get_system_ux_state

    # Insert system UX state
    system_data = {
        "registry": {
            "topic_id": 123,
            "ping_message_id": 456,
            "pong_message_id": 789,
        }
    }
    await test_db.execute(
        "INSERT INTO system_settings (key, value) VALUES (?, ?)",
        ("ux_state", json.dumps(system_data)),
    )
    await test_db.commit()

    state = await get_system_ux_state(test_db)

    assert state.registry.topic_id == 123
    assert state.registry.ping_message_id == 456
    assert state.registry.pong_message_id == 789


@pytest.mark.asyncio
async def test_update_system_ux_state_merges_registry_fields(test_db):
    """Test that update_system_ux_state merges registry fields."""
    from teleclaude.core.ux_state import get_system_ux_state, update_system_ux_state

    # Insert existing system state
    existing_data = {
        "registry": {
            "topic_id": 100,
            "ping_message_id": 200,
            "pong_message_id": 300,
        }
    }
    await test_db.execute(
        "INSERT INTO system_settings (key, value) VALUES (?, ?)",
        ("ux_state", json.dumps(existing_data)),
    )
    await test_db.commit()

    # Update only topic_id
    await update_system_ux_state(test_db, registry_topic_id=999)

    state = await get_system_ux_state(test_db)
    assert state.registry.topic_id == 999  # Updated
    assert state.registry.ping_message_id == 200  # Preserved
    assert state.registry.pong_message_id == 300  # Preserved


def test_session_ux_state_from_dict_handles_missing_fields():
    """Test that SessionUXState.from_dict handles missing fields gracefully."""
    from teleclaude.core.ux_state import SessionUXState

    # Partial dict with only some fields
    partial_data = {
        "output_message_id": "msg-123",
        # Missing: polling_active, notification_sent, etc.
    }

    state = SessionUXState.from_dict(partial_data)

    assert state.output_message_id == "msg-123"
    assert state.polling_active is False  # Default
    assert state.notification_sent is False  # Default
    assert state.pending_deletions == []  # Default


def test_session_ux_state_to_dict_serializes_all_fields():
    """Test that SessionUXState.to_dict includes all fields."""
    from teleclaude.core.ux_state import SessionUXState

    state = SessionUXState(
        output_message_id="msg-123",
        polling_active=True,
        idle_notification_message_id="idle-456",
        pending_deletions=["del-1", "del-2"],
        pending_feedback_deletions=["fb-1"],
        notification_sent=True,
        claude_session_id="claude-789",
        claude_session_file="/path/to/session.jsonl",
    )

    data = state.to_dict()

    assert data["output_message_id"] == "msg-123"
    assert data["polling_active"] is True
    assert data["idle_notification_message_id"] == "idle-456"
    assert data["pending_deletions"] == ["del-1", "del-2"]
    assert data["pending_feedback_deletions"] == ["fb-1"]
    assert data["notification_sent"] is True
    assert data["claude_session_id"] == "claude-789"
    assert data["claude_session_file"] == "/path/to/session.jsonl"
