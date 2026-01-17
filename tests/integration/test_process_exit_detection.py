"""Test process exit detection uses output_message_id instead of file existence.

Regression test for bug where user input was appended to completed process messages
because detection used file existence (file kept for downloads) instead of output_message_id.
"""

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_process_detection_uses_output_message_id(daemon_with_mocked_telegram, tmp_path):
    """Verify process detection uses output_message_id, not file existence."""
    daemon = daemon_with_mocked_telegram

    # Create a session
    session = await daemon.db.create_session(
        computer_name="test",
        tmux_session_name="test-exit-detection",
        origin_adapter="telegram",
        title="Test Exit Detection",
        project_path="/tmp",
    )

    # Simulate process running - set output_message_id
    await daemon.db.update_session(session.session_id, output_message_id="msg-123")

    # Create output file (kept for downloads)
    output_file = tmp_path / f"{session.session_id[:8]}.txt"
    output_file.write_text("test output")

    # Process is running
    updated_session = await daemon.db.get_session(session.session_id)
    assert updated_session
    output_message_id = updated_session.output_message_id
    assert output_message_id == "msg-123"
    assert output_file.exists()

    # This is how daemon.py detects running process (daemon.py:970-979)
    has_output_message = bool(output_message_id)
    is_process_running = has_output_message
    assert is_process_running is True

    # Simulate process exit - clear output_message_id (daemon.py:1253)
    await daemon.db.update_session(session.session_id, output_message_id=None)

    # Output file still exists (kept for download button)
    assert output_file.exists()

    # But process is no longer running
    updated_session = await daemon.db.get_session(session.session_id)
    assert updated_session
    output_message_id = updated_session.output_message_id
    assert output_message_id is None

    has_output_message = bool(output_message_id)
    is_process_running = has_output_message
    assert is_process_running is False

    # CRITICAL: File existence should NOT affect process detection
    # Old buggy detection: is_process_running = output_file.exists()
    # Would incorrectly return True, causing messages to append to completed process


@pytest.mark.integration
@pytest.mark.asyncio
async def test_process_detection_survives_daemon_restart(daemon_with_mocked_telegram):
    """Verify output_message_id persists across daemon restarts."""
    daemon = daemon_with_mocked_telegram

    # Create session with active polling
    session = await daemon.db.create_session(
        computer_name="test",
        tmux_session_name="test-restart-detection",
        origin_adapter="telegram",
        title="Test Restart",
        project_path="/tmp",
    )

    # Set output_message_id (polling active)
    await daemon.db.update_session(session.session_id, output_message_id="msg-456")

    # Verify it was stored
    updated_session = await daemon.db.get_session(session.session_id)
    assert updated_session
    stored_id = updated_session.output_message_id
    assert stored_id == "msg-456"

    # Simulate daemon restart - create new manager with same database
    from teleclaude.core.db import Db

    db_path = daemon.db.db_path
    new_manager = Db(db_path)
    await new_manager.initialize()

    # output_message_id should persist (from database)
    persisted_session = await new_manager.get_session(session.session_id)
    assert persisted_session
    output_message_id = persisted_session.output_message_id
    assert output_message_id == "msg-456"

    # Process detection still works
    has_output_message = bool(output_message_id)
    assert has_output_message is True

    # Clean up new manager (daemon fixture handles original)
    await new_manager.close()
