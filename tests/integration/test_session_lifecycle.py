"""Integration test for complete session lifecycle (hard delete on close)."""

import asyncio
import os

import pytest

from teleclaude.constants import MAIN_MODULE
from teleclaude.core.models import SessionAdapterMetadata, TelegramAdapterMetadata
from teleclaude.core.origins import InputOrigin

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core import session_cleanup, tmux_bridge
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionLifecycleContext
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
            try:
                import shutil

                shutil.rmtree(workspace_dir, ignore_errors=True)
            except Exception:
                pass


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


# =========================================================================
# Event-driven chain tests: session_closed → daemon → terminate → delete_channel
# =========================================================================


def _telegram_metadata(topic_id: int = 12345) -> SessionAdapterMetadata:
    """Create proper SessionAdapterMetadata with telegram topic_id."""
    return SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=topic_id))


async def _wait_for_event_tasks(max_wait: float = 0.5, step: float = 0.05) -> None:
    """Yield control to let fire-and-forget event_bus tasks complete."""
    elapsed = 0.0
    while elapsed < max_wait:
        await asyncio.sleep(step)
        elapsed += step


@pytest.mark.integration
async def test_session_closed_event_triggers_channel_deletion(daemon_with_mocked_telegram):
    """Emitting session_closed via event_bus triggers delete_channel on the adapter.

    This is the critical chain that was never tested:
    event_bus.emit("session_closed") → daemon._handle_session_closed
    → terminate_session → cleanup_session_resources → adapter_client.delete_channel
    → telegram_adapter.delete_channel
    """
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    session = await test_db.create_session(
        computer_name="TestPC",
        tmux_session_name="tc_event_chain",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Event Chain Test",
        adapter_metadata=_telegram_metadata(topic_id=99001),
    )

    await tmux_bridge.ensure_tmux_session(name="tc_event_chain", working_dir="/tmp")

    telegram_adapter = daemon.client.adapters["telegram"]
    telegram_adapter.delete_channel.reset_mock()

    # Fire session_closed via event bus (same path as _handle_topic_closed)
    event_bus.emit("session_closed", SessionLifecycleContext(session_id=session.session_id))
    await _wait_for_event_tasks()

    # The chain must have called delete_channel on the telegram adapter.
    # Expected: called twice due to db.close_session feedback loop
    # (terminate_session → db.close_session → emits session_closed → terminate again)
    assert telegram_adapter.delete_channel.call_count == 2

    # Session must be closed in DB
    updated = await test_db.get_session(session.session_id)
    assert updated is not None
    assert updated.closed_at is not None


@pytest.mark.integration
async def test_session_closed_event_for_already_closed_session(daemon_with_mocked_telegram):
    """Re-emitting session_closed for an already-closed session still triggers delete_channel.

    This covers UC1 (topic closed for closed session): the session has closed_at set,
    but the topic was never deleted. Re-emitting session_closed should still clean up.
    """
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    session = await test_db.create_session(
        computer_name="TestPC",
        tmux_session_name="tc_already_closed",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Already Closed Test",
        adapter_metadata=_telegram_metadata(topic_id=99002),
    )

    # Close the session first (simulates a session that was closed but topic not deleted)
    await test_db.close_session(session.session_id)
    await _wait_for_event_tasks()  # close_session also emits session_closed

    telegram_adapter = daemon.client.adapters["telegram"]
    telegram_adapter.delete_channel.reset_mock()

    # Re-emit session_closed (simulates topic_closed handler or maintenance replay)
    event_bus.emit("session_closed", SessionLifecycleContext(session_id=session.session_id))
    await _wait_for_event_tasks()

    # delete_channel must still be called for already-closed sessions
    telegram_adapter.delete_channel.assert_called_once()


@pytest.mark.integration
async def test_terminate_session_calls_delete_channel(daemon_with_mocked_telegram):
    """terminate_session with proper telegram metadata calls delete_channel on adapter.

    Strengthens existing test_close_session_full_cleanup by:
    - Using proper SessionAdapterMetadata (not a raw dict)
    - Asserting delete_channel was actually called
    """
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    session = await test_db.create_session(
        computer_name="TestPC",
        tmux_session_name="tc_terminate_delete",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Terminate Delete Test",
        adapter_metadata=_telegram_metadata(topic_id=99003),
    )

    await tmux_bridge.ensure_tmux_session(name="tc_terminate_delete", working_dir="/tmp")

    telegram_adapter = daemon.client.adapters["telegram"]
    telegram_adapter.delete_channel.reset_mock()

    result = await session_cleanup.terminate_session(
        session.session_id,
        daemon.client,
        reason="exit",
        session=session,
    )
    assert result is True

    # Verify delete_channel was called
    telegram_adapter.delete_channel.assert_called_once()

    # Verify session closed
    updated = await test_db.get_session(session.session_id)
    assert updated is not None
    assert updated.closed_at is not None

    # Verify tmux killed
    exists = await tmux_bridge.session_exists("tc_terminate_delete")
    assert not exists


@pytest.mark.integration
async def test_session_closed_event_full_cleanup_chain(daemon_with_mocked_telegram):
    """Event-driven session close performs full cleanup: tmux, workspace, channel, DB."""
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    session = await test_db.create_session(
        computer_name="TestPC",
        tmux_session_name="tc_full_chain",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Full Chain Test",
        adapter_metadata=_telegram_metadata(topic_id=99004),
    )

    await tmux_bridge.ensure_tmux_session(name="tc_full_chain", working_dir="/tmp", session_id=session.session_id)

    workspace_dir = get_session_output_dir(session.session_id)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "tmux.txt").write_text("test output")

    telegram_adapter = daemon.client.adapters["telegram"]
    telegram_adapter.delete_channel.reset_mock()

    # Trigger via event bus
    event_bus.emit("session_closed", SessionLifecycleContext(session_id=session.session_id))
    await _wait_for_event_tasks()

    # All cleanup must have happened (called twice due to db.close_session feedback loop)
    assert telegram_adapter.delete_channel.call_count == 2

    updated = await test_db.get_session(session.session_id)
    assert updated is not None
    assert updated.closed_at is not None

    exists = await tmux_bridge.session_exists("tc_full_chain")
    assert not exists, "tmux session should be killed"

    assert not workspace_dir.exists(), "workspace should be deleted"


@pytest.mark.integration
async def test_session_closed_idempotent_via_event_bus(daemon_with_mocked_telegram):
    """Emitting session_closed twice is safe and idempotent."""
    daemon = daemon_with_mocked_telegram
    test_db = daemon.db

    session = await test_db.create_session(
        computer_name="TestPC",
        tmux_session_name="tc_idempotent_event",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Idempotent Event Test",
        adapter_metadata=_telegram_metadata(topic_id=99005),
    )

    telegram_adapter = daemon.client.adapters["telegram"]
    telegram_adapter.delete_channel.reset_mock()

    # First emission
    event_bus.emit("session_closed", SessionLifecycleContext(session_id=session.session_id))
    await _wait_for_event_tasks()

    # Second emission (should not raise)
    event_bus.emit("session_closed", SessionLifecycleContext(session_id=session.session_id))
    await _wait_for_event_tasks()

    # delete_channel called at least twice (idempotent cleanup)
    assert telegram_adapter.delete_channel.call_count >= 2


if __name__ == MAIN_MODULE:
    pytest.main([__file__, "-v", "-s"])
