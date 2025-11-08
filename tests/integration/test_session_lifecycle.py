"""Integration test for complete session lifecycle.

Tests UC-S2: Close Session
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import terminal_bridge
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.db import db, Db
from teleclaude.core.models import Session


@pytest.mark.integration
async def test_close_session_full_cleanup():
    """Test /exit command performs complete cleanup.

    Use Case: UC-S2
    Flow:
    1. Create session with active tmux session
    2. Create output file
    3. Send /exit command
    4. Verify tmux session killed
    5. Verify output file deleted
    6. Verify session marked closed in DB
    7. Verify channel deleted
    """
    # Setup test database
    db_path = "/tmp/test_session_lifecycle.db"
    Path(db_path).unlink(missing_ok=True)

    test_db = Db(db_path)
    await test_db.initialize()

    tmux_session_name = "test-session-cleanup"
    output_file_path = Path(f"/tmp/session_output/{tmux_session_name}.txt")
    output_file_path.parent.mkdir(exist_ok=True)

    try:
        with patch("teleclaude.core.db.db", test_db):
            # Create session in DB
            session = await test_db.create_session(
                computer_name="TestPC",
                tmux_session_name=tmux_session_name,
                origin_adapter="telegram",
                title="Cleanup Test",
                adapter_metadata={"channel_id": "test-channel-123"},
            )

            # Create tmux session
            success = await terminal_bridge.create_tmux_session(
                name=tmux_session_name,
                shell="/bin/sh",
                working_dir="/tmp",
                cols=80,
                rows=24,
            )
            assert success, "tmux session should be created"

            # Create output file
            output_file_path.write_text("Test output content")
            assert output_file_path.exists(), "Output file should exist"

            # Mock adapter_client
            adapter_client = Mock(spec=AdapterClient)
            adapter_client.delete_channel = AsyncMock()
            adapter_client.send_message = AsyncMock()

            # Simulate /exit command handling
            # (In real code, this is in daemon.py handle_command("exit"))

            # 1. Stop polling if active
            await test_db.unmark_polling(session.session_id)

            # 2. Kill tmux session
            await terminal_bridge.kill_session(tmux_session_name)

            # 3. Delete output file
            if output_file_path.exists():
                output_file_path.unlink()

            # 4. Mark session as closed
            await test_db.update_session(session.session_id, closed=True)

            # 5. Delete channel
            await adapter_client.delete_channel(session.session_id)

            # 6. Send confirmation message
            await adapter_client.send_message(session.session_id, "Session closed")

            # Verify tmux session killed
            exists = await terminal_bridge.session_exists(tmux_session_name)
            assert not exists, "tmux session should be killed"

            # Verify output file deleted
            assert not output_file_path.exists(), "Output file should be deleted"

            # Verify session marked closed
            updated_session = await test_db.get_session(session.session_id)
            assert updated_session.closed is True, "Session should be marked closed"

            # Verify delete_channel called
            adapter_client.delete_channel.assert_called_once_with(session.session_id)

            # Verify confirmation message sent
            adapter_client.send_message.assert_called_once()

    finally:
        # Cleanup
        await test_db.close()
        Path(db_path).unlink(missing_ok=True)
        if output_file_path.exists():
            output_file_path.unlink()
        if output_file_path.parent.exists() and not list(output_file_path.parent.iterdir()):
            output_file_path.parent.rmdir()


@pytest.mark.integration
async def test_close_session_with_active_polling():
    """Test closing session while command is running.

    Use Case: UC-S2
    Flow:
    1. Start long-running command (polling active)
    2. Mark session as polling in DB
    3. Send /exit command
    4. Verify polling stopped gracefully
    5. Verify cleanup completed
    """
    # Setup test database
    db_path = "/tmp/test_close_while_polling.db"
    Path(db_path).unlink(missing_ok=True)

    test_db = Db(db_path)
    await test_db.initialize()

    tmux_session_name = "test-session-polling"

    try:
        with patch("teleclaude.core.db.db", test_db):
            # Create session
            session = await test_db.create_session(
                computer_name="TestPC",
                tmux_session_name=tmux_session_name,
                origin_adapter="telegram",
                title="Polling Test",
            )

            # Create tmux session
            await terminal_bridge.create_tmux_session(
                name=tmux_session_name,
                shell="/bin/sh",
                working_dir="/tmp",
                cols=80,
                rows=24,
            )

            # Mark as polling (simulate active polling)
            await test_db.mark_polling(session.session_id)
            is_polling = await test_db.is_polling(session.session_id)
            assert is_polling is True, "Session should be marked as polling"

            # Simulate /exit command
            # 1. Unmark polling (stops polling loop)
            await test_db.unmark_polling(session.session_id)

            # 2. Kill tmux session
            await terminal_bridge.kill_session(tmux_session_name)

            # 3. Mark session closed
            await test_db.update_session(session.session_id, closed=True)

            # Verify polling stopped
            is_polling_after = await test_db.is_polling(session.session_id)
            assert is_polling_after is False, "Polling should be stopped"

            # Verify tmux killed
            exists = await terminal_bridge.session_exists(tmux_session_name)
            assert not exists, "tmux session should be killed"

            # Verify session closed
            updated = await test_db.get_session(session.session_id)
            assert updated.closed is True

    finally:
        # Cleanup
        await test_db.close()
        Path(db_path).unlink(missing_ok=True)


@pytest.mark.integration
async def test_close_session_idempotent():
    """Test closing already-closed session is safe (idempotent).

    Use Case: UC-S2 (edge case)
    Flow:
    1. Close session once
    2. Attempt to close again
    3. Verify no errors raised
    4. Verify session remains closed
    """
    # Setup test database
    db_path = "/tmp/test_close_idempotent.db"
    Path(db_path).unlink(missing_ok=True)

    test_db = Db(db_path)
    await test_db.initialize()

    tmux_session_name = "test-session-idempotent"

    try:
        with patch("teleclaude.core.db.db", test_db):
            # Create and close session
            session = await test_db.create_session(
                computer_name="TestPC",
                tmux_session_name=tmux_session_name,
                origin_adapter="telegram",
                title="Idempotent Test",
            )

            # First close
            await test_db.update_session(session.session_id, closed=True)
            await terminal_bridge.kill_session(tmux_session_name)  # Safe if doesn't exist

            # Second close (should not raise)
            await test_db.update_session(session.session_id, closed=True)
            await terminal_bridge.kill_session(tmux_session_name)  # Safe if doesn't exist

            # Verify still closed
            updated = await test_db.get_session(session.session_id)
            assert updated.closed is True

    finally:
        await test_db.close()
        Path(db_path).unlink(missing_ok=True)


@pytest.mark.integration
async def test_close_session_does_not_delete_from_db():
    """Test closing session marks as closed but does not delete record.

    Use Case: UC-S2
    Flow:
    1. Create session
    2. Close session
    3. Verify session still exists in DB
    4. Verify session.closed == True
    5. Verify can retrieve closed session
    """
    # Setup test database
    db_path = "/tmp/test_close_no_delete.db"
    Path(db_path).unlink(missing_ok=True)

    test_db = Db(db_path)
    await test_db.initialize()

    try:
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test-no-delete",
            origin_adapter="telegram",
            title="No Delete Test",
        )

        session_id = session.session_id

        # Close session
        await test_db.update_session(session_id, closed=True)

        # Verify still exists in DB
        retrieved = await test_db.get_session(session_id)
        assert retrieved is not None, "Session should still exist in DB"
        assert retrieved.closed is True, "Session should be marked closed"
        assert retrieved.session_id == session_id

        # Verify appears in closed sessions list
        closed_sessions = await test_db.list_sessions(closed=True)
        assert any(s.session_id == session_id for s in closed_sessions)

    finally:
        await test_db.close()
        Path(db_path).unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
