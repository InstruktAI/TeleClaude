#!/usr/bin/env python3
"""Unit tests for Db CRUD operations."""

from pathlib import Path

import pytest

from teleclaude.core.db import Db


@pytest.mark.unit
async def test_session_manager_crud():
    """Test Db CRUD operations."""
    db_path = "/tmp/teleclaude_test_core.db"

    # Clean up old test database
    Path(db_path).unlink(missing_ok=True)

    session_mgr = Db(db_path)

    try:
        # Initialize
        await session_mgr.initialize()

        # Create session
        session = await session_mgr.create_session(
            computer_name="TestMac",
            tmux_session_name="test-session-crud",
            origin_adapter="telegram",
            title="Test Session",
            terminal_size="80x24",
            working_directory="~",
        )

        assert session.session_id is not None
        assert session.title == "Test Session"

        # Get session
        retrieved = await session_mgr.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == session.session_id
        assert retrieved.title == session.title

        # List sessions
        sessions = await session_mgr.list_sessions()
        assert len(sessions) >= 1
        assert any(s.session_id == session.session_id for s in sessions)

        # Update session
        await session_mgr.update_session(session.session_id, title="Updated Title")
        updated = await session_mgr.get_session(session.session_id)
        assert updated.title == "Updated Title"

        # Update activity
        await session_mgr.update_last_activity(session.session_id)

        # Delete session
        await session_mgr.delete_session(session.session_id)
        deleted = await session_mgr.get_session(session.session_id)
        assert deleted is None

    finally:
        await session_mgr.close()


@pytest.mark.unit
async def test_session_manager_with_metadata():
    """Test Db adapter metadata queries."""
    import os

    from teleclaude.core.models import SessionAdapterMetadata, TelegramAdapterMetadata

    db_path = "/tmp/teleclaude_test_metadata.db"

    # Clean up old database if exists
    if os.path.exists(db_path):
        os.remove(db_path)

    session_mgr = Db(db_path)

    try:
        await session_mgr.initialize()

        # Create session with metadata
        metadata = SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123, output_message_id="456"))
        session = await session_mgr.create_session(
            computer_name="TestMac",
            tmux_session_name="test-metadata",
            origin_adapter="telegram",
            adapter_metadata=metadata,
            title="Metadata Test",
        )

        # Query by metadata
        results = await session_mgr.get_sessions_by_adapter_metadata("telegram", "topic_id", 123)
        assert len(results) == 1
        assert results[0].session_id == session.session_id

        # Cleanup
        await session_mgr.delete_session(session.session_id)

    finally:
        await session_mgr.close()
        # Remove test database
        if os.path.exists(db_path):
            os.remove(db_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
