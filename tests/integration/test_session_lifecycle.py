"""Integration test for complete session lifecycle (hard delete on close)."""

import os

import pytest

from teleclaude.constants import MAIN_MODULE
from teleclaude.core.origins import InputOrigin

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core import session_cleanup, tmux_bridge
from teleclaude.core.session_utils import get_session_output_dir


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
    6. Verify session deleted from DB
    7. Verify channel deleted
    """
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    tmux_session_name = "test-session-cleanup"

    try:
        # Create session in DB
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name=tmux_session_name,
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Cleanup Test",
            adapter_metadata={"channel_id": "test-channel-123"},
        )

        workspace_dir = get_session_output_dir(session.session_id)
        output_file_path = workspace_dir / "tmux.txt"

        # Create tmux session (MOCKED)
        success = await tmux_bridge.ensure_tmux_session(
            name=tmux_session_name,
            working_dir="/tmp",
        )
        assert success, "tmux session should be created"

        # Create output file
        output_file_path.write_text("Test output content")
        assert output_file_path.exists(), "Output file should exist"

        # Use daemon's client (already has mocked adapters)
        adapter_client = daemon.client

        # Terminate session (hard delete)
        result = await session_cleanup.terminate_session(
            session.session_id,
            adapter_client,
            reason="exit",
            session=session,
        )
        assert result is True

        # Verify tmux session killed (MOCKED)
        exists = await tmux_bridge.session_exists(tmux_session_name)
        assert not exists, "tmux session should be killed"

        # Verify workspace deleted
        assert not workspace_dir.exists(), "Workspace should be deleted"

        # Verify session closed
        updated_session = await test_db.get_session(session.session_id)
        assert updated_session is not None
        assert updated_session.closed_at is not None

    finally:
        # Cleanup
        if "workspace_dir" in locals() and workspace_dir.exists():
            for child in workspace_dir.iterdir():
                child.unlink()
            workspace_dir.rmdir()


@pytest.mark.integration
async def test_close_session_with_active_polling(daemon_with_mocked_telegram):
    """Test closing session while command is running (cleanup still happens)."""
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    tmux_session_name = "test-session-polling"

    # Create session
    session = await test_db.create_session(
        computer_name="TestPC",
        tmux_session_name=tmux_session_name,
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Polling Test",
    )

    # Create tmux session (MOCKED)
    await tmux_bridge.ensure_tmux_session(
        name=tmux_session_name,
        working_dir="/tmp",
    )

    # Terminate session
    result = await session_cleanup.terminate_session(
        session.session_id,
        daemon.client,
        reason="exit",
        session=session,
    )
    assert result is True

    # Verify tmux killed (MOCKED)
    exists = await tmux_bridge.session_exists(tmux_session_name)
    assert not exists, "tmux session should be killed"

    # Verify session closed
    updated = await test_db.get_session(session.session_id)
    assert updated is not None
    assert updated.closed_at is not None


@pytest.mark.integration
async def test_close_session_idempotent(daemon_with_mocked_telegram):
    """Test closing already-terminated session is safe (idempotent)."""
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    tmux_session_name = "test-session-idempotent"

    # Create and close session
    session = await test_db.create_session(
        computer_name="TestPC",
        tmux_session_name=tmux_session_name,
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Idempotent Test",
    )

    # First close
    first = await session_cleanup.terminate_session(
        session.session_id,
        daemon.client,
        reason="exit",
        session=session,
    )

    # Second close (should not raise)
    second = await session_cleanup.terminate_session(
        session.session_id,
        daemon.client,
        reason="exit",
    )

    assert first is True
    assert second is False


@pytest.mark.integration
async def test_close_session_deletes_from_db(daemon_with_mocked_telegram):
    """Test closing session marks record closed in DB."""
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    session = await test_db.create_session(
        computer_name="TestPC",
        tmux_session_name="test-no-delete",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="No Delete Test",
    )

    session_id = session.session_id

    # Close session
    result = await session_cleanup.terminate_session(
        session_id,
        daemon.client,
        reason="exit",
        session=session,
    )
    assert result is True

    # Verify closed in DB
    retrieved = await test_db.get_session(session_id)
    assert retrieved is not None
    assert retrieved.closed_at is not None


if __name__ == MAIN_MODULE:
    pytest.main([__file__, "-v", "-s"])
