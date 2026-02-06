"""Unit tests for polling_coordinator module."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import polling_coordinator
from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.output_poller import OutputChanged, ProcessExited


@pytest.mark.asyncio
class TestPollAndSendOutput:
    """Test poll_and_send_output function."""

    async def test_duplicate_polling_prevention(self):
        """Test polling request ignored when already polling."""
        session_id = "test-123"
        await polling_coordinator._register_polling(session_id)
        try:
            # Should return False and not start polling
            result = await polling_coordinator.schedule_polling(
                session_id=session_id,
                tmux_session_name="tmux",
                output_poller=Mock(),
                adapter_client=Mock(),
                get_output_file=Mock(),
            )
            assert result is False
        finally:
            await polling_coordinator._unregister_polling(session_id)

    async def test_output_changed_event(self):
        """Test OutputChanged event handling."""
        # Mock session
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        # Mock poller to yield OutputChanged event
        async def mock_poll(session_id, tmux_session_name, output_file):
            yield OutputChanged(
                session_id="test-123",
                output="test output",
                started_at=1000.0,
                last_changed_at=1001.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        adapter_client = Mock()
        adapter_client.send_output_update = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        with (
            patch("teleclaude.core.polling_coordinator.db.get_session", new_callable=AsyncMock) as mock_get,
            patch("teleclaude.core.polling_coordinator.event_bus.emit") as mock_emit,
        ):
            mock_get.return_value = mock_session
            await polling_coordinator.poll_and_send_output(
                session_id="test-123",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
                _skip_register=True,
            )

        # Verify send_output_update was called
        assert adapter_client.send_output_update.called
        args, _ = adapter_client.send_output_update.call_args
        assert args[1] == "test output"

    async def test_process_exited_with_exit_code(self):
        """Test ProcessExited event with exit code."""
        # Mock session
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        async def mock_poll(session_id, tmux_session_name, output_file):
            yield ProcessExited(
                session_id="test-123",
                final_output="command output",
                exit_code=0,
                started_at=1000.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        adapter_client = Mock()
        adapter_client.send_output_update = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        with (
            patch("teleclaude.core.polling_coordinator.db.get_session", new_callable=AsyncMock) as mock_get,
            patch("teleclaude.core.tmux_bridge.session_exists", new_callable=AsyncMock, return_value=True),
        ):
            mock_get.return_value = mock_session
            await polling_coordinator.poll_and_send_output(
                session_id="test-123",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
                _skip_register=True,
            )

        # Verify final update sent
        assert adapter_client.send_output_update.called
        args, kwargs = adapter_client.send_output_update.call_args
        assert kwargs["is_final"] is True
        assert kwargs["exit_code"] == 0

    async def test_process_exited_without_exit_code(self, tmp_path):
        """Test ProcessExited event without exit code (session died)."""
        # Mock session with human-readable title
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        # Create real temp file
        output_file = tmp_path / "output.txt"
        output_file.write_text("test output")

        # Mock poller to yield ProcessExited event without exit code
        async def mock_poll(session_id, tmux_session_name, output_file):
            yield ProcessExited(
                session_id="test-123",
                final_output="partial output",
                exit_code=None,
                started_at=1000.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        adapter_client = Mock()
        adapter_client.send_output_update = AsyncMock()

        get_output_file = Mock(return_value=output_file)

        with (
            patch("teleclaude.core.polling_coordinator.db.get_session", new_callable=AsyncMock) as mock_get,
            patch("teleclaude.core.session_cleanup.terminate_session", new_callable=AsyncMock) as mock_terminate,
        ):
            mock_get.return_value = mock_session
            await polling_coordinator.poll_and_send_output(
                session_id="test-123",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
                _skip_register=True,
            )

        mock_terminate.assert_not_called()

    async def test_process_exited_with_exit_code_and_missing_tmux(self, tmp_path):
        """Exit code with missing tmux should terminate the session."""
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        output_file = tmp_path / "output.txt"
        output_file.write_text("test output")

        async def mock_poll(session_id, tmux_session_name, output_file):
            yield ProcessExited(
                session_id="test-123",
                final_output="command output",
                exit_code=0,
                started_at=1000.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        adapter_client = Mock()
        adapter_client.send_output_update = AsyncMock()

        get_output_file = Mock(return_value=output_file)

        with (
            patch("teleclaude.core.polling_coordinator.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.tmux_bridge.session_exists", new_callable=AsyncMock, return_value=False
            ) as mock_exists,
            patch("teleclaude.core.session_cleanup.terminate_session", new_callable=AsyncMock) as mock_terminate,
        ):
            mock_get.return_value = mock_session
            await polling_coordinator.poll_and_send_output(
                session_id="test-123",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
                _skip_register=True,
            )

        assert mock_exists.call_args == (("test-tmux",), {"log_missing": False})
        assert mock_terminate.call_args is not None
        _, kwargs = mock_terminate.call_args
        assert kwargs["kill_tmux"] is False

    async def test_cleanup_in_finally_block(self):
        """Test cleanup always happens in finally block."""
        session_id = "test-123"
        mock_session = Session(
            session_id=session_id,
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        # Mock poller to raise exception
        async def mock_poll(session_id, tmux_session_name, output_file):
            raise RuntimeError("Polling error")
            yield  # Never reached

        output_poller = Mock()
        output_poller.poll = mock_poll

        adapter_client = Mock()
        adapter_client.send_error_feedback = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        with (
            patch("teleclaude.core.polling_coordinator.db.get_session", new_callable=AsyncMock) as mock_get,
            patch("teleclaude.core.polling_coordinator._unregister_polling", new_callable=AsyncMock) as mock_unreg,
        ):
            mock_get.return_value = mock_session
            with pytest.raises(RuntimeError, match="Polling error"):
                await polling_coordinator.poll_and_send_output(
                    session_id=session_id,
                    tmux_session_name="test-tmux",
                    output_poller=output_poller,
                    adapter_client=adapter_client,
                    get_output_file=get_output_file,
                    _skip_register=True,
                )

        # Verify cleanup was called even on error
        assert mock_unreg.called
        assert mock_unreg.call_args == ((session_id,),)
        # Verify error feedback sent
        assert adapter_client.send_error_feedback.called
