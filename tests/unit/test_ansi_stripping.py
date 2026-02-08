"""Unit tests for ANSI stripping in UI adapters."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config


class StubUiAdapter(UiAdapter):
    """Stub implementation of UiAdapter for testing."""

    async def create_channel(self, *args, **kwargs):
        return "topic_123"

    async def delete_channel(self, *args, **kwargs):
        return True

    async def close_channel(self, *args, **kwargs):
        return True

    async def reopen_channel(self, *args, **kwargs):
        return True

    async def send_message(self, *args, **kwargs):
        return "msg_123"

    async def edit_message(self, *args, **kwargs):
        return True

    async def delete_message(self, *args, **kwargs):
        return True

    async def send_file(self, *args, **kwargs):
        return "file_123"

    async def discover_peers(self, *args, **kwargs):
        return []

    async def poll_output_stream(self, *args, **kwargs):
        yield ""

    async def start(self, *args, **kwargs):
        pass

    async def stop(self, *args, **kwargs):
        pass

    async def update_channel_title(self, *args, **kwargs):
        return True


@pytest.mark.asyncio
async def test_ui_adapter_send_output_update_strips_ansi(monkeypatch):
    """Verify that UiAdapter.send_output_update strips ANSI codes when enabled."""
    # Mock config
    monkeypatch.setattr(config.terminal, "strip_ansi", True)

    # Mock client and DB
    client = MagicMock()
    with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
        mock_db.update_session = AsyncMock()
        adapter = StubUiAdapter(client)
        adapter.ADAPTER_KEY = "test"

        # Mock edit/send methods to capture what is actually sent
        adapter.edit_message = AsyncMock(return_value=True)
        adapter._get_output_message_id = AsyncMock(return_value="msg_123")

        # ANSI colored output
        raw_output = "\x1b[31mRed Text\x1b[0m"

        # Call send_output_update
        await adapter.send_output_update(
            session=MagicMock(session_id="sess_123", last_output_digest=None, adapter_metadata=MagicMock()),
            output=raw_output,
            started_at=1000.0,
            last_output_changed_at=1000.0,
        )

        # Verify that the message sent to edit_message has no ANSI codes
        args, kwargs = adapter.edit_message.call_args
        sent_text = args[2]
        assert "Red Text" in sent_text
        assert "\x1b[" not in sent_text


@pytest.mark.asyncio
async def test_ui_adapter_send_output_update_preserves_ansi_when_disabled(monkeypatch):
    """Verify that UiAdapter.send_output_update preserves ANSI codes when disabled."""
    # Mock config
    monkeypatch.setattr(config.terminal, "strip_ansi", False)

    # Mock client and DB
    client = MagicMock()
    with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
        mock_db.update_session = AsyncMock()
        adapter = StubUiAdapter(client)
        adapter.ADAPTER_KEY = "test"

        adapter.edit_message = AsyncMock(return_value=True)
        adapter._get_output_message_id = AsyncMock(return_value="msg_123")

        # ANSI colored output
        raw_output = "\x1b[31mRed Text\x1b[0m"

        await adapter.send_output_update(
            session=MagicMock(session_id="sess_123", last_output_digest=None, adapter_metadata=MagicMock()),
            output=raw_output,
            started_at=1000.0,
            last_output_changed_at=1000.0,
        )

        args, kwargs = adapter.edit_message.call_args
        sent_text = args[2]
        assert "\x1b[31mRed Text\x1b[0m" in sent_text


@pytest.mark.asyncio
async def test_ui_adapter_strips_various_ansi_variants(monkeypatch):
    """Verify stripping of CSI, OSC, and simple escape sequences."""
    monkeypatch.setattr(config.terminal, "strip_ansi", True)
    client = MagicMock()
    with patch("teleclaude.adapters.ui_adapter.db") as mock_db:
        mock_db.update_session = AsyncMock()
        adapter = StubUiAdapter(client)
        adapter.ADAPTER_KEY = "test"
        adapter.edit_message = AsyncMock(return_value=True)
        adapter._get_output_message_id = AsyncMock(return_value="msg_123")

        variants = [
            ("\x1b[31;1mComplex CSI\x1b[0m", "Complex CSI"),
            ("\x1b]0;Title\x07OSC Sequence", "OSC Sequence"),
            ("\x1b=Simple\x1b>Sequence", "SimpleSequence"),
            ("Normal \x1b[KClear Line", "Normal Clear Line"),
        ]

        for raw, expected in variants:
            await adapter.send_output_update(
                session=MagicMock(session_id="sess_123", last_output_digest=None, adapter_metadata=MagicMock()),
                output=raw,
                started_at=1000.0,
                last_output_changed_at=1000.0,
            )
            args, _ = adapter.edit_message.call_args
            assert expected in args[2]
            assert "\x1b" not in args[2]


@pytest.mark.asyncio
async def test_agent_coordinator_handle_agent_stop_strips_ansi(monkeypatch):
    """Verify that AgentCoordinator strips ANSI codes from agent feedback before storage."""
    from teleclaude.core.agent_coordinator import AgentCoordinator
    from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload

    monkeypatch.setattr(config.terminal, "strip_ansi", True)

    client = MagicMock()
    tts = MagicMock()
    headless = MagicMock()
    coordinator = AgentCoordinator(client, tts, headless)

    # Mock DB and extraction
    raw_ansi_output = "\x1b[32mSuccess!\x1b[0m"
    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch.object(coordinator, "_extract_and_summarize", return_value=(raw_ansi_output, "Summary")),
    ):
        mock_db.get_session = AsyncMock(
            return_value=MagicMock(active_agent="claude", last_after_model_at=None, last_checkpoint_at=None)
        )
        mock_db.update_session = AsyncMock()

        payload = AgentStopPayload(source_computer="local", transcript_path="/tmp/log")
        context = AgentEventContext(session_id="sess_123", event_type=AgentHookEvents.AGENT_STOP, data=payload)

        await coordinator.handle_agent_stop(context)

        # Verify stored value is clean (check first call which contains last_feedback_received)
        calls = mock_db.update_session.call_args_list
        # Find the call that has last_feedback_received
        feedback_call = next((c for c in calls if "last_feedback_received" in c.kwargs), None)
        assert feedback_call is not None, "Expected update_session call with last_feedback_received"
        assert feedback_call.kwargs["last_feedback_received"] == "Success!"
        assert "\x1b[" not in feedback_call.kwargs["last_feedback_received"]


@pytest.mark.asyncio
async def test_polling_coordinator_detects_styled_suggestions():
    """Verify that polling_coordinator detects dim/italic suggestions."""
    from teleclaude.core.polling_coordinator import _find_prompt_input, _is_suggestion_styled

    # Dim styled suggestion
    dim_output = "\x1b[2mSuggestion\x1b[0m"
    assert _is_suggestion_styled(dim_output) is True

    # Italic styled suggestion
    italic_output = "\x1b[3mSuggestion\x1b[0m"
    assert _is_suggestion_styled(italic_output) is True

    # Normal output
    normal_output = "Normal Text"
    assert _is_suggestion_styled(normal_output) is False

    # Test _find_prompt_input skips styled suggestions
    codex_output = "› \x1b[2mCaptured Suggestion\x1b[0m"
    assert _find_prompt_input(codex_output) == ""

    # Test _find_prompt_input captures normal input
    codex_real_input = "› Real Input"
    assert _find_prompt_input(codex_real_input) == "Real Input"


@pytest.mark.asyncio
async def test_output_poller_preserves_raw_ansi_internally(tmp_path):
    """Verify that OutputPoller does NOT strip ANSI codes during its internal poll loop."""
    from teleclaude.core.output_poller import OutputChanged, OutputPoller

    poller = OutputPoller()
    output_file = tmp_path / "output.txt"

    # Raw output with ANSI codes
    raw_ansi = "\x1b[31mRaw\x1b[0m"

    with patch("teleclaude.core.output_poller.tmux_bridge") as mock_tb:
        mock_tb.session_exists = AsyncMock(side_effect=[True, False])
        mock_tb.capture_pane = AsyncMock(return_value=raw_ansi)
        mock_tb.is_pane_dead = AsyncMock(return_value=False)

        with patch("teleclaude.core.output_poller.asyncio.sleep", new_callable=AsyncMock):
            events = []
            async for event in poller.poll("sess_123", "tmux_123", output_file):
                events.append(event)

            # OutputChanged event should contain RAW ANSI codes
            output_events = [e for e in events if isinstance(e, OutputChanged)]
            assert output_events
            assert output_events[0].output == raw_ansi
            assert "\x1b[31m" in output_events[0].output
