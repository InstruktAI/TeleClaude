"""Unit tests for UiAdapter base class."""

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.origins import InputOrigin

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.db import Db
from teleclaude.core.models import (
    CleanupTrigger,
    MessageMetadata,
    Session,
    SessionAdapterMetadata,
    TelegramAdapterMetadata,
)


class MockUiAdapter(UiAdapter):
    """Paranoid concrete implementation of UiAdapter for testing."""

    ADAPTER_KEY = "telegram"  # Use telegram key for testing (reuses existing metadata structure)

    def __init__(self):
        # Create mock client with async send_message for notice delegation
        mock_client = MagicMock()
        mock_client.on = MagicMock()  # Mock event registration
        mock_client.send_message = AsyncMock(return_value="msg-123")
        super().__init__(mock_client)
        self._send_calls = []
        self._edit_calls = []
        self._send_message_mock = AsyncMock(return_value="msg-123")
        self._edit_message_mock = AsyncMock(return_value=True)
        self._delete_message_mock = AsyncMock(return_value=True)

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_message(
        self,
        session: Session,
        text: str,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        _ = multi_message
        self._send_calls.append((text, metadata))
        return await self._send_message_mock(session, text, metadata, multi_message)

    async def edit_message(self, session: Session, message_id: str, text: str, metadata: MessageMetadata) -> bool:
        self._edit_calls.append(text)
        return await self._edit_message_mock(session, message_id, text, metadata)

    async def delete_message(self, session: Session, message_id: str) -> bool:
        return await self._delete_message_mock(session, message_id)

    async def close_channel(self, session_id: str) -> bool:
        return True

    async def reopen_channel(self, session_id: str) -> bool:
        return True

    async def send_file(self, session_id: str, file_path: str, caption: str = "") -> str:
        return "file-msg-123"

    async def poll_output_stream(self, session_id: str, timeout: float = 300.0):
        if False:
            yield
        return

    async def create_channel(self, session_id: str, title: str, metadata: dict) -> str:
        return "test-channel"

    async def update_channel_title(self, session_id: str, title: str) -> bool:
        return True

    async def delete_channel(self, session_id: str) -> bool:
        return True

    async def send_general_message(self, text: str, metadata=None) -> str:
        return "msg-general"

    async def discover_peers(self):
        return []


@pytest.fixture
async def test_db(tmp_path):
    """Paranoid temporary database for testing."""
    db_path = str(tmp_path / "test.db")
    test_db_instance = Db(db_path)
    await test_db_instance.initialize()

    # Patch module-level db with test instance
    with patch("teleclaude.adapters.ui_adapter.db", test_db_instance):
        yield test_db_instance

    await test_db_instance.close()


@pytest.mark.asyncio
class TestSendOutputUpdate:
    """Paranoid test send_output_update method."""

    async def test_creates_new_message_when_no_message_id(self, test_db):
        """Paranoid test creating new output message when no message_id exists."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        result = await adapter.send_output_update(
            session,
            "test output",
            time.time(),
            time.time(),
        )

        assert result == "msg-123"
        assert len(adapter._send_calls) == 1
        assert "test output" in adapter._send_calls[0][0]
        assert adapter._edit_calls == []

    async def test_edits_existing_message_when_message_id_exists(self, test_db):
        """Paranoid test editing existing message when message_id exists."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        # Set output_message_id in adapter namespace
        if not session.adapter_metadata:
            session.adapter_metadata = SessionAdapterMetadata()
        session.adapter_metadata.telegram = TelegramAdapterMetadata(output_message_id="msg-456")
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

        # Refresh session from DB
        session = await test_db.get_session(session.session_id)

        result = await adapter.send_output_update(
            session,
            "updated output",
            time.time(),
            time.time(),
        )

        assert result == "msg-456"
        assert len(adapter._edit_calls) == 1
        assert "updated output" in adapter._edit_calls[0]

    async def test_render_markdown_skips_code_block(self, test_db):
        """Paranoid test that render_markdown sends output without code block wrapper."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        result = await adapter.send_output_update(
            session,
            "markdown output",
            time.time(),
            time.time(),
            render_markdown=True,
        )

        assert result == "msg-123"
        assert adapter._send_calls
        sent_text, metadata = adapter._send_calls[-1]
        assert "```" not in sent_text
        assert metadata.parse_mode == "MarkdownV2"

    async def test_render_markdown_strips_heading_icons(self, test_db):
        """Paranoid test that render_markdown renders headings without emoji prefixes."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        output = "# Title\n\n## 23:03:31 · 🤖 Assistant\n\nBody text"

        await adapter.send_output_update(
            session,
            output,
            time.time(),
            time.time(),
            render_markdown=True,
        )

        sent_text, _ = adapter._send_calls[-1]
        assert "## " not in sent_text
        assert "📌" not in sent_text
        assert "✏" not in sent_text
        assert "*Title*" in sent_text
        assert "*23:03:31 · 🤖 Assistant*" in sent_text

    async def test_creates_new_when_edit_fails(self, test_db):
        """Paranoid test creating new message when edit fails (stale message_id)."""
        adapter = MockUiAdapter()
        adapter._edit_message_mock = AsyncMock(return_value=False)
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        # Set output_message_id in adapter namespace
        if not session.adapter_metadata:
            session.adapter_metadata = SessionAdapterMetadata()
        session.adapter_metadata.telegram = TelegramAdapterMetadata(output_message_id="msg-stale")
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

        # Refresh session from DB
        session = await test_db.get_session(session.session_id)

        result = await adapter.send_output_update(
            session,
            "output after edit fail",
            time.time(),
            time.time(),
        )

        assert result == "msg-123"
        assert len(adapter._edit_calls) == 1
        assert "output after edit fail" in adapter._edit_calls[0]
        assert len(adapter._send_calls) >= 1

        # Verify stale message_id was cleared and new one stored
        session = await test_db.get_session(session.session_id)
        assert session.adapter_metadata.telegram is not None
        assert session.adapter_metadata.telegram.output_message_id == "msg-123"

    async def test_includes_exit_code_in_final_message(self, test_db):
        """Paranoid test final message includes exit code."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        started_at = time.time() - 10  # 10 seconds ago
        await adapter.send_output_update(
            session,
            "command output",
            started_at,
            time.time(),
            is_final=True,
            exit_code=0,
        )

        assert adapter._send_calls
        message_text, _ = adapter._send_calls[-1]

        assert "✅" in message_text or "0" in message_text
        assert "```" in message_text

    async def test_non_gemini_not_suppressed_when_experiment_globally_enabled(self, test_db):
        """Threaded suppression applies only to Gemini sessions."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        await test_db.update_session(session.session_id, active_agent="codex")
        session = await test_db.get_session(session.session_id)

        with patch("teleclaude.adapters.ui_adapter.is_threaded_output_enabled", return_value=False):
            result = await adapter.send_output_update(
                session,
                "codex output",
                time.time(),
                time.time(),
            )

        assert result == "msg-123"
        assert len(adapter._send_calls) == 1

    async def test_send_threaded_footer_replaces_previous(self, test_db):
        """Threaded footer keeps only latest footer message."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        if not session.adapter_metadata:
            session.adapter_metadata = SessionAdapterMetadata()
        session.adapter_metadata.telegram = TelegramAdapterMetadata(threaded_footer_message_id="old-footer")
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        session = await test_db.get_session(session.session_id)

        await adapter.send_threaded_footer(session, "📋 tc: abc")

        adapter._delete_message_mock.assert_awaited_once_with(session, "old-footer")
        latest = await test_db.get_session(session.session_id)
        assert latest.adapter_metadata.telegram is not None
        assert latest.adapter_metadata.telegram.threaded_footer_message_id == "msg-123"

    async def test_standard_output_cleans_stale_threaded_footer(self, test_db):
        """Non-threaded output should remove stale threaded footer state/messages."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        if not session.adapter_metadata:
            session.adapter_metadata = SessionAdapterMetadata()
        session.adapter_metadata.telegram = TelegramAdapterMetadata(threaded_footer_message_id="stale-footer")
        await test_db.update_session(
            session.session_id, adapter_metadata=session.adapter_metadata, active_agent="codex"
        )
        session = await test_db.get_session(session.session_id)

        with patch("teleclaude.adapters.ui_adapter.is_threaded_output_enabled", return_value=False):
            await adapter.send_output_update(
                session,
                "normal output",
                time.time(),
                time.time(),
            )

        adapter._delete_message_mock.assert_awaited_once_with(session, "stale-footer")
        latest = await test_db.get_session(session.session_id)
        assert latest.adapter_metadata.telegram is not None
        assert latest.adapter_metadata.telegram.threaded_footer_message_id is None

    async def test_standard_output_is_fitted_upstream_before_send(self, test_db):
        """Standard output payload should already fit Telegram limit when sent."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        await test_db.update_session(session.session_id, active_agent="codex")
        session = await test_db.get_session(session.session_id)

        # Simulate tmux content with dense markdown-like patterns and long body.
        output = ("line with ```fence``` and symbols [](){}!.\n" * 300) + ("x" * 1500)
        await adapter.send_output_update(
            session,
            output,
            time.time(),
            time.time(),
        )

        assert adapter._send_calls
        sent_text, _metadata = adapter._send_calls[-1]
        assert len(sent_text) <= UI_MESSAGE_MAX_CHARS
        assert sent_text.startswith("```")
        assert "\n```" in sent_text


@pytest.mark.asyncio
class TestSendMessageNotice:
    """Paranoid test notice messages (ephemeral message tracking)."""

    async def test_tracks_notice_for_deletion(self, test_db):
        """Paranoid test that send_message tracks notice for deletion via AdapterClient."""
        from teleclaude.core.adapter_client import AdapterClient

        # Create real AdapterClient and adapter
        client = AdapterClient()
        adapter = MockUiAdapter()
        # Re-wire adapter to use real client instead of mock
        adapter.client = client
        client.register_adapter("telegram", adapter)

        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        # Patch adapter_client's db reference to use test_db
        with patch("teleclaude.core.adapter_client.db", test_db):
            msg_id = await client.send_message(session, "Ephemeral notice", cleanup_trigger=CleanupTrigger.NEXT_NOTICE)

        # Notices use deletion_type="feedback", not "user_input"
        pending = await test_db.get_pending_deletions(session.session_id, deletion_type="feedback")
        assert msg_id in pending, "Notice message should be tracked for deletion"


class TestFormatMessage:
    """Paranoid test format_message method and markdown sanitization."""

    def test_sanitizes_internal_code_blocks(self):
        """Paranoid test that internal ``` markers are escaped to prevent nested code blocks."""
        adapter = MockUiAdapter()
        output_with_code = "Here is code:\n```python\nprint('hello')\n```\nEnd"

        result = adapter.format_message(output_with_code, "status line")

        # Should have outer code block markers
        assert result.startswith("```\n")
        # Internal ``` should be escaped with zero-width space
        assert "`\u200b``python" in result
        assert "`\u200b``\n" in result  # Closing marker also escaped

    def test_handles_multiple_code_blocks(self):
        """Paranoid test multiple internal code blocks are all escaped."""
        adapter = MockUiAdapter()
        output = "```js\ncode1\n```\ntext\n```py\ncode2\n```"

        result = adapter.format_message(output, "status")

        # Count escaped markers (should be 4 - two opening, two closing)
        assert result.count("`\u200b``") == 4
        # Should only have 2 real ``` markers (outer wrapper)
        assert result.count("```") == 2

    def test_preserves_output_without_code_blocks(self):
        """Paranoid test normal output without ``` is unchanged."""
        adapter = MockUiAdapter()
        output = "Simple tmux output\nNo code blocks here"

        result = adapter.format_message(output, "status line")

        assert "```\nSimple tmux output\nNo code blocks here\n```" in result
        assert "status line" in result
