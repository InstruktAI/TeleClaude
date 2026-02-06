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
