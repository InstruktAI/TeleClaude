"""Integration test for ephemeral message cleanup.

With the unified ephemeral message design, ALL tracked messages
(user input and feedback) are cleaned on next user input.
"""

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core import terminal_bridge
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import (
    MessageMetadata,
    SessionAdapterMetadata,
    TelegramAdapterMetadata,
)


@pytest.mark.integration
async def test_ephemeral_messages_cleaned_on_user_input(daemon_with_mocked_telegram):
    """Test that all ephemeral messages are deleted on next user input.

    Unified design: All messages tracked via add_pending_deletion are
    cleaned when user sends new input (pre-handler cleanup).
    """
    daemon = daemon_with_mocked_telegram

    # Create session with proper nested adapter_metadata for topic_id lookup
    session = await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="test-ephemeral-cleanup",
        origin_adapter="telegram",
        title="Test Ephemeral Cleanup",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=67890)),
    )

    # Simulate some ephemeral messages (feedback, errors, etc.)
    feedback_msg_id = "feedback-456"
    error_msg_id = "error-789"
    await daemon.db.add_pending_deletion(session.session_id, feedback_msg_id)
    await daemon.db.add_pending_deletion(session.session_id, error_msg_id)

    # Verify messages are tracked
    pending = await daemon.db.get_pending_deletions(session.session_id)
    assert feedback_msg_id in pending
    assert error_msg_id in pending

    # Get telegram adapter to check delete_message calls
    telegram_adapter = daemon.client.adapters["telegram"]

    # Mock session_exists to return True
    async def mock_session_exists(name: str, log_missing: bool = True) -> bool:
        return True

    with patch.object(terminal_bridge, "session_exists", mock_session_exists):
        # Simulate user input - this triggers pre-handler cleanup
        await daemon.client.handle_event(
            event=TeleClaudeEvents.MESSAGE,
            payload={"text": "hello", "message_id": "user-msg-123"},
            metadata=MessageMetadata(
                adapter_type="telegram",
                message_thread_id=67890,
            ),
        )

    # System boundary: verify the adapter attempted deletes for the tracked message ids.
    from unittest.mock import call

    telegram_adapter.delete_message.assert_has_calls(
        [
            call(session, feedback_msg_id),
            call(session, error_msg_id),
        ],
        any_order=True,
    )

    # Verify pending deletions were cleared
    pending_after = await daemon.db.get_pending_deletions(session.session_id)
    assert feedback_msg_id not in pending_after
    assert error_msg_id not in pending_after


@pytest.mark.integration
async def test_send_message_ephemeral_auto_tracks(daemon_with_mocked_telegram):
    """Test that send_message with ephemeral=True auto-tracks for deletion."""
    daemon = daemon_with_mocked_telegram

    # Create session
    session = await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="test-auto-track",
        origin_adapter="telegram",
        title="Test Auto Track",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=67891)),
    )

    # Send ephemeral message (default)
    msg_id = await daemon.client.send_message(session, "Ephemeral feedback", metadata=MessageMetadata())

    # Verify it was auto-tracked
    pending = await daemon.db.get_pending_deletions(session.session_id)
    assert msg_id in pending, "Ephemeral message should be auto-tracked"


@pytest.mark.integration
async def test_send_message_persistent_not_tracked(daemon_with_mocked_telegram):
    """Test that send_message with ephemeral=False is NOT tracked."""
    daemon = daemon_with_mocked_telegram

    # Create session
    session = await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="test-persistent",
        origin_adapter="telegram",
        title="Test Persistent",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=67892)),
    )

    # Send persistent message
    msg_id = await daemon.client.send_message(
        session, "Persistent message", metadata=MessageMetadata(), ephemeral=False
    )

    # Verify it was NOT tracked
    pending = await daemon.db.get_pending_deletions(session.session_id)
    assert msg_id not in pending, "Persistent message should NOT be tracked"
