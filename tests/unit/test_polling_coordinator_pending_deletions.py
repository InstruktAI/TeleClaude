"""Unit test to verify polling_coordinator does not clear pending_deletions.

Regression test for bug where polling_coordinator.clear_pending_deletions()
was wiping tracked message IDs before they could be deleted on next user input.
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import polling_coordinator
from teleclaude.core.db import db
from teleclaude.core.models import Session


@pytest.mark.asyncio
async def test_polling_does_not_clear_pending_deletions():
    """Test that poll_and_send_output does NOT call clear_pending_deletions in finally block.

    This is critical for message deletion flow:
    1. User sends message → _post_handle_user_input tracks message_id in pending_deletions
    2. Polling runs and completes
    3. User sends next message → _pre_handle_user_input deletes previous message

    If polling clears pending_deletions, step 3 finds empty list and nothing gets deleted.
    """
    # Mock session
    mock_session = Session(
        session_id="test-123",
        computer_name="test",
        tmux_session_name="test-tmux",
        origin_adapter="telegram",
        title="Test Session",
    )

    # Mock all db methods
    db.get_session = AsyncMock(return_value=mock_session)
    db.update_ux_state = AsyncMock()
    db.clear_pending_deletions = AsyncMock()  # THIS is what we're testing

    # Mock adapter client
    adapter_client = Mock()
    adapter_client.send_output_update = AsyncMock()

    # Mock output poller to yield ProcessExited event immediately
    async def mock_poll(session_id, tmux_session_name, output_file):
        from teleclaude.core.output_poller import ProcessExited

        yield ProcessExited(
            session_id="test-123",
            final_output="test output",
            exit_code=0,
            started_at=1000.0,
        )

    output_poller = Mock()
    output_poller.poll = mock_poll

    output_file = Path("/tmp/output.txt")
    get_output_file = Mock(return_value=output_file)

    # Run polling
    with patch(
        "teleclaude.core.tmux_bridge.session_exists",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await polling_coordinator.poll_and_send_output(
            session_id="test-123",
            tmux_session_name="test-tmux",
            output_poller=output_poller,
            adapter_client=adapter_client,
            get_output_file=get_output_file,
            _skip_register=True,
        )

    # CRITICAL ASSERTION: clear_pending_deletions should NOT have been called
    # The finally block should not touch deletion tracking; that's handled by
    # _pre_handle_user_input on the next user message.
    db.clear_pending_deletions.assert_not_called()

    # update_ux_state may be called for notification flags, etc.
    assert db.update_ux_state.call_count >= 0
