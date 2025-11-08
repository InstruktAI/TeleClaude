"""Integration test for idle notification during long-running commands.

Tests UC-H3: Long-Running Command with Idle Notification
"""

import asyncio
from pathlib import Path

import pytest

from teleclaude.core import terminal_bridge


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idle_notification_stored_in_ux_state(daemon_with_mocked_telegram):
    """Test idle notification message_id is stored in ux_state.

    Use Case: UC-H3
    Flow:
    1. Create session
    2. Simulate idle notification by setting message_id
    3. Verify message_id stored in ux_state
    4. Verify can retrieve notification_id
    """
    daemon = daemon_with_mocked_telegram

    # Create session
    session = await daemon.db.create_session(
        computer_name="TestPC",
        tmux_session_name="test-idle-storage",
        origin_adapter="telegram",
        title="Idle Storage Test",
    )

    # Initially no idle notification
    ux_state = await daemon.db.get_ux_state(session.session_id)
    assert ux_state.idle_notification_message_id is None

    # Simulate idle notification sent (polling_coordinator would do this)
    await daemon.db.set_idle_notification(session.session_id, "idle-msg-789")

    # Verify notification_id stored
    ux_state = await daemon.db.get_ux_state(session.session_id)
    assert ux_state.idle_notification_message_id == "idle-msg-789"

    # Verify can retrieve it
    retrieved_id = await daemon.db.get_idle_notification(session.session_id)
    assert retrieved_id == "idle-msg-789"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idle_notification_cleared_when_output_resumes(daemon_with_mocked_telegram):
    """Test idle notification_id cleared from ux_state when output resumes.

    Use Case: UC-H3
    Flow:
    1. Set idle notification message_id
    2. Clear notification (simulating output resume)
    3. Verify notification_id is None
    """
    daemon = daemon_with_mocked_telegram

    # Create session
    session = await daemon.db.create_session(
        computer_name="TestPC",
        tmux_session_name="test-idle-clear",
        origin_adapter="telegram",
        title="Idle Clear Test",
    )

    # Set idle notification
    await daemon.db.set_idle_notification(session.session_id, "idle-msg-456")
    ux_state = await daemon.db.get_ux_state(session.session_id)
    assert ux_state.idle_notification_message_id == "idle-msg-456"

    # Simulate output resuming - clear notification
    await daemon.db.remove_idle_notification(session.session_id)

    # Verify cleared
    ux_state = await daemon.db.get_ux_state(session.session_id)
    assert ux_state.idle_notification_message_id is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idle_notification_persists_across_restarts(daemon_with_mocked_telegram):
    """Test idle notification_id persists in database across daemon restarts.

    Use Case: UC-H3 (persistence)
    Flow:
    1. Set idle notification message_id
    2. Simulate daemon restart (new Db instance)
    3. Verify notification_id still present
    """
    daemon = daemon_with_mocked_telegram

    # Create session
    session = await daemon.db.create_session(
        computer_name="TestPC",
        tmux_session_name="test-idle-persist",
        origin_adapter="telegram",
        title="Idle Persist Test",
    )

    # Set idle notification
    await daemon.db.set_idle_notification(session.session_id, "idle-msg-persist")

    # Verify stored
    ux_state = await daemon.db.get_ux_state(session.session_id)
    assert ux_state.idle_notification_message_id == "idle-msg-persist"

    # Simulate daemon restart - create new Db instance
    from teleclaude.core.db import Db

    db_path = daemon.db.db_path
    new_db = Db(db_path)
    await new_db.initialize()

    try:
        # Verify notification_id persists
        ux_state = await new_db.get_ux_state(session.session_id)
        assert ux_state.idle_notification_message_id == "idle-msg-persist"

        # Verify can still retrieve it
        retrieved_id = await new_db.get_idle_notification(session.session_id)
        assert retrieved_id == "idle-msg-persist"

    finally:
        await new_db.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_has_idle_notification_check(daemon_with_mocked_telegram):
    """Test has_idle_notification() helper method.

    Use Case: UC-H3
    Flow:
    1. Create session (no idle notification)
    2. Verify has_idle_notification() returns False
    3. Set idle notification
    4. Verify has_idle_notification() returns True
    """
    daemon = daemon_with_mocked_telegram

    # Create session
    session = await daemon.db.create_session(
        computer_name="TestPC",
        tmux_session_name="test-has-idle",
        origin_adapter="telegram",
        title="Has Idle Test",
    )

    # Initially no idle notification
    has_idle = await daemon.db.has_idle_notification(session.session_id)
    assert has_idle is False

    # Set idle notification
    await daemon.db.set_idle_notification(session.session_id, "idle-msg-check")

    # Now has idle notification
    has_idle = await daemon.db.has_idle_notification(session.session_id)
    assert has_idle is True

    # Clear notification
    await daemon.db.remove_idle_notification(session.session_id)

    # No longer has idle notification
    has_idle = await daemon.db.has_idle_notification(session.session_id)
    assert has_idle is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
