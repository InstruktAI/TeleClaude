"""Integration test for feedback message cleanup on user input."""

import json

import pytest


@pytest.mark.integration
async def test_feedback_messages_cleaned_on_user_input(daemon_with_mocked_telegram):
    """Test that feedback messages are deleted when user sends new input."""
    daemon = daemon_with_mocked_telegram

    # Create session
    session = await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="test-feedback-cleanup",
        origin_adapter="telegram",
        title="Test Feedback Cleanup",
        adapter_metadata={"channel_id": "12345"},
    )

    # Simulate sending a feedback message (like "Transcribing...")
    # This would normally be done by daemon code, so we simulate it
    feedback_msg_id = "feedback-msg-456"
    await daemon.db.add_pending_deletion(session.session_id, feedback_msg_id)

    # Verify feedback message is in pending_deletions
    ux_state = await daemon.db.get_ux_state(session.session_id)
    assert feedback_msg_id in ux_state.pending_deletions
    initial_count = len(ux_state.pending_deletions)

    # Get telegram adapter to check delete_message calls
    telegram_adapter = daemon.client.adapters["telegram"]
    initial_delete_calls = telegram_adapter.delete_message.call_count

    # Simulate user input (MESSAGE event) via AdapterClient
    await daemon.client.handle_event(
        event="message",
        payload={"session_id": session.session_id, "text": "hello"},
        metadata={"adapter_type": "telegram", "message_id": "user-msg-789"},
    )

    # Verify delete_message was called (feedback message should be deleted)
    assert (
        telegram_adapter.delete_message.call_count > initial_delete_calls
    ), "delete_message should have been called to clean up feedback message"

    # Verify our feedback message was deleted (check call args)
    delete_calls = [call[0] for call in telegram_adapter.delete_message.call_args_list]
    assert any(
        feedback_msg_id in str(call) for call in delete_calls
    ), f"Feedback message {feedback_msg_id} should have been deleted"
