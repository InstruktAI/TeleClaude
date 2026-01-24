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
