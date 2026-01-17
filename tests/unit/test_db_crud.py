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
            project_path="~",
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


@pytest.mark.unit
async def test_api_outbox_enqueue_and_fetch(tmp_path):
    """Test API outbox enqueue, fetch, and deliver flow."""
    from datetime import datetime, timezone

    db_path = tmp_path / "teleclaude_test_api_outbox.db"
    session_mgr = Db(str(db_path))

    try:
        await session_mgr.initialize()

        row_id = await session_mgr.enqueue_api_event(
            request_id="req-123",
            event_type="new_session",
            payload={"session_id": "", "args": ["Test"]},
            metadata={"adapter_type": "api"},
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        rows = await session_mgr.fetch_api_outbox_batch(now_iso, 10, now_iso)
        assert len(rows) == 1
        assert rows[0]["id"] == row_id
        assert rows[0]["request_id"] == "req-123"

        claimed = await session_mgr.claim_api_outbox(row_id, now_iso, now_iso)
        assert claimed is True

        await session_mgr.mark_api_outbox_delivered(row_id, '{"status":"success"}')

        rows_after = await session_mgr.fetch_api_outbox_batch(now_iso, 10, now_iso)
        assert rows_after == []

    finally:
        await session_mgr.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
