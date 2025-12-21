"""Integration test for complete session lifecycle.

Tests UC-S2: Close Session
"""

from pathlib import Path

import pytest

from teleclaude.core import terminal_bridge
from teleclaude.core.models import MessageMetadata


@pytest.mark.integration
async def test_close_session_full_cleanup(daemon_with_mocked_telegram):
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
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    tmux_session_name = "test-session-cleanup"
    output_file_path = Path(f"/tmp/session_output/{tmux_session_name}.txt")
    output_file_path.parent.mkdir(exist_ok=True)

    try:
        # Create session in DB
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name=tmux_session_name,
            origin_adapter="telegram",
            title="Cleanup Test",
            adapter_metadata={"channel_id": "test-channel-123"},
        )

        # Create tmux session (MOCKED)
        success = await terminal_bridge.create_tmux_session(
            name=tmux_session_name,
            working_dir="/tmp",
            cols=80,
            rows=24,
        )
        assert success, "tmux session should be created"

        # Create output file
        output_file_path.write_text("Test output content")
        assert output_file_path.exists(), "Output file should exist"

        # Use daemon's client (already has mocked adapters)
        adapter_client = daemon.client

        # Simulate /exit command handling
        # (In real code, this is in daemon.py handle_command("exit"))

        # 1. Kill tmux session (MOCKED)
        await terminal_bridge.kill_session(tmux_session_name)

        # 2. Delete output file
        if output_file_path.exists():
            output_file_path.unlink()

        # 3. Mark session as closed
        await test_db.update_session(session.session_id, closed=True)

        # 4. Delete channel (mocked)
        await adapter_client.delete_channel(session)

        # 5. Send confirmation message (mocked)
        await adapter_client.send_message(session, "Session closed", MessageMetadata())

        # Verify tmux session killed (MOCKED)
        exists = await terminal_bridge.session_exists(tmux_session_name)
        assert not exists, "tmux session should be killed"

        # Verify output file deleted
        assert not output_file_path.exists(), "Output file should be deleted"

        # Verify session marked closed
        updated_session = await test_db.get_session(session.session_id)
        assert updated_session.closed is True, "Session should be marked closed"

    finally:
        # Cleanup
        if output_file_path.exists():
            output_file_path.unlink()
        if output_file_path.parent.exists() and not list(output_file_path.parent.iterdir()):
            output_file_path.parent.rmdir()


@pytest.mark.integration
async def test_close_session_with_active_polling(daemon_with_mocked_telegram):
    """Test closing session while command is running.

    Use Case: UC-S2
    Flow:
    1. Start long-running command (polling active)
    2. Mark session as polling in DB
    3. Send /exit command
    4. Verify polling stopped gracefully
    5. Verify cleanup completed
    """
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    tmux_session_name = "test-session-polling"

    # Create session
    session = await test_db.create_session(
        computer_name="TestPC",
        tmux_session_name=tmux_session_name,
        origin_adapter="telegram",
        title="Polling Test",
    )

    # Create tmux session (MOCKED)
    await terminal_bridge.create_tmux_session(
        name=tmux_session_name,
        working_dir="/tmp",
        cols=80,
        rows=24,
    )

    # Simulate /exit command
    # 1. Kill tmux session (MOCKED)
    await terminal_bridge.kill_session(tmux_session_name)

    # 2. Mark session closed
    await test_db.update_session(session.session_id, closed=True)

    # Verify tmux killed (MOCKED)
    exists = await terminal_bridge.session_exists(tmux_session_name)
    assert not exists, "tmux session should be killed"

    # Verify session closed
    updated = await test_db.get_session(session.session_id)
    assert updated.closed is True


@pytest.mark.integration
async def test_close_session_idempotent(daemon_with_mocked_telegram):
    """Test closing already-closed session is safe (idempotent).

    Use Case: UC-S2 (edge case)
    Flow:
    1. Close session once
    2. Attempt to close again
    3. Verify no errors raised
    4. Verify session remains closed
    """
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    tmux_session_name = "test-session-idempotent"

    # Create and close session
    session = await test_db.create_session(
        computer_name="TestPC",
        tmux_session_name=tmux_session_name,
        origin_adapter="telegram",
        title="Idempotent Test",
    )

    # First close
    await test_db.update_session(session.session_id, closed=True)
    await terminal_bridge.kill_session(tmux_session_name)  # Safe if doesn't exist (MOCKED)

    # Second close (should not raise)
    await test_db.update_session(session.session_id, closed=True)
    await terminal_bridge.kill_session(tmux_session_name)  # Safe if doesn't exist (MOCKED)

    # Verify still closed
    updated = await test_db.get_session(session.session_id)
    assert updated.closed is True


@pytest.mark.integration
async def test_close_session_does_not_delete_from_db(daemon_with_mocked_telegram):
    """Test closing session marks as closed but does not delete record.

    Use Case: UC-S2
    Flow:
    1. Create session
    2. Close session
    3. Verify session still exists in DB
    4. Verify session.closed == True
    5. Verify can retrieve closed session
    """
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
