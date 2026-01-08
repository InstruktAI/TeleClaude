"""Integration test for feedback message cleanup on new feedback."""

from unittest.mock import patch

import pytest

from teleclaude.core import terminal_bridge
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import (
    MessageMetadata,
    SessionAdapterMetadata,
    TelegramAdapterMetadata,
)


@pytest.mark.integration
async def test_feedback_messages_cleaned_on_new_feedback(daemon_with_mocked_telegram):
    """Test that feedback messages are deleted when new feedback is sent.

    Feedback cleanup happens in send_feedback, NOT on user input.
    This ensures download messages stay until the next feedback (like summary).
    """
    daemon = daemon_with_mocked_telegram

    # Create session with proper nested adapter_metadata for topic_id lookup
    session = await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="test-feedback-cleanup",
        origin_adapter="telegram",
        title="Test Feedback Cleanup",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=67890)),
    )

    # Simulate a previous feedback message (like download message)
    old_feedback_msg_id = "old-feedback-456"
    await daemon.db.add_pending_feedback_deletion(session.session_id, old_feedback_msg_id)

    # Verify old feedback message is tracked
    pending_feedback = await daemon.db.get_pending_feedback_deletions(session.session_id)
    assert old_feedback_msg_id in pending_feedback

    # Get telegram adapter to check delete_message calls
    telegram_adapter = daemon.client.adapters["telegram"]
    initial_delete_calls = telegram_adapter.delete_message.call_count

    # Restore real send_feedback so cleanup logic runs
    # (the fixture mocks it which bypasses UiAdapter.send_feedback's cleanup)
    from teleclaude.adapters.ui_adapter import UiAdapter

    original_send_feedback = UiAdapter.send_feedback

    async def real_send_feedback(self, sess, msg, meta, persistent=False):
        return await original_send_feedback(self, sess, msg, meta, persistent)

    telegram_adapter.send_feedback = lambda s, m, meta, persistent=False: real_send_feedback(
        telegram_adapter, s, m, meta, persistent
    )

    # Send new feedback (like summary) - this should cleanup old feedback
    await daemon.client.send_feedback(session, "New summary message", MessageMetadata())

    # Verify delete_message was called for old feedback
    assert telegram_adapter.delete_message.call_count > initial_delete_calls, (
        "delete_message should have been called to clean up old feedback"
    )

    # Verify our old feedback message was deleted
    delete_calls = [call[0] for call in telegram_adapter.delete_message.call_args_list]
    assert any(old_feedback_msg_id in str(call) for call in delete_calls), (
        f"Old feedback message {old_feedback_msg_id} should have been deleted"
    )


@pytest.mark.integration
async def test_feedback_messages_not_cleaned_on_user_input(daemon_with_mocked_telegram):
    """Test that feedback messages are NOT deleted on user input.

    Download messages should stay until the next feedback arrives,
    not disappear when user sends input.
    """
    daemon = daemon_with_mocked_telegram

    # Create session
    session = await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="test-feedback-no-cleanup",
        origin_adapter="telegram",
        title="Test No Cleanup On Input",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=67891)),
    )

    # Add a feedback message (like download message)
    feedback_msg_id = "download-msg-789"
    await daemon.db.add_pending_feedback_deletion(session.session_id, feedback_msg_id)

    # Verify it's tracked
    pending_feedback = await daemon.db.get_pending_feedback_deletions(session.session_id)
    assert feedback_msg_id in pending_feedback

    # Get telegram adapter
    telegram_adapter = daemon.client.adapters["telegram"]
    initial_delete_calls = telegram_adapter.delete_message.call_count

    # Mock session_exists to return True
    async def mock_session_exists(name: str, log_missing: bool = True) -> bool:
        return True

    with patch.object(terminal_bridge, "session_exists", mock_session_exists):
        # Simulate user input
        await daemon.client.handle_event(
            event=TeleClaudeEvents.MESSAGE,
            payload={"text": "hello", "message_id": "user-msg-123"},
            metadata=MessageMetadata(
                adapter_type="telegram",
                message_thread_id=67891,
            ),
        )

    # Verify delete_message was NOT called for feedback
    # (only user input messages should be cleaned, not feedback)
    feedback_delete_calls = [
        call
        for call in telegram_adapter.delete_message.call_args_list[initial_delete_calls:]
        if feedback_msg_id in str(call)
    ]
    assert len(feedback_delete_calls) == 0, "Feedback message should NOT be deleted on user input"

    # Verify feedback is still in pending_feedback_deletions
    pending_feedback = await daemon.db.get_pending_feedback_deletions(session.session_id)
    assert feedback_msg_id in pending_feedback, "Feedback should still be tracked"
