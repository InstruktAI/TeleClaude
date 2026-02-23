"""Unit tests for UiAdapter base class."""

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.origins import InputOrigin

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.adapters.ui_adapter import UiAdapter
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

    def _build_metadata_for_thread(self) -> MessageMetadata:
        """Use MarkdownV2 to exercise escape-aware splitting in tests."""
        return MessageMetadata(parse_mode="MarkdownV2")


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
        assert len(adapter._send_calls) >= 1
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

        # Set output_message_id via dedicated top-level column
        await test_db.set_output_message_id(session.session_id, "msg-456")

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
        """render_markdown sends output without code block wrapper."""
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
        sent_text, _metadata = adapter._send_calls[0]
        assert "```" not in sent_text

    async def test_render_markdown_preserves_content(self, test_db):
        """render_markdown passes through content without platform conversion in base class."""
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

        sent_text, _ = adapter._send_calls[0]
        # Base class passes through without transformation
        assert "# Title" in sent_text
        assert "Body text" in sent_text

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

        # Set output_message_id via dedicated top-level column
        await test_db.set_output_message_id(session.session_id, "msg-stale")

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

        # Verify stale message_id was cleared and new one stored via top-level column
        session = await test_db.get_session(session.session_id)
        assert session.output_message_id == "msg-123"

    async def test_includes_exit_code_in_footer(self, test_db):
        """Final message puts exit code in footer, not in output."""
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

        assert len(adapter._send_calls) >= 2
        # Output message: code block with tmux output
        output_text, _ = adapter._send_calls[0]
        assert "```" in output_text
        assert "command output" in output_text
        # Footer message: status line with exit code + session IDs
        footer_text, _ = adapter._send_calls[1]
        assert "✅" in footer_text or "0" in footer_text

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
        assert len(adapter._send_calls) >= 1

    async def test_send_footer_edits_existing(self, test_db):
        """Footer edits existing footer message in place."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        if not session.adapter_metadata:
            session.adapter_metadata = SessionAdapterMetadata()
        session.adapter_metadata = SessionAdapterMetadata(
            telegram=TelegramAdapterMetadata(footer_message_id="old-footer")
        )
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        session = await test_db.get_session(session.session_id)

        result = await adapter._send_footer(session)

        # Should edit in place, not delete and re-send
        assert result == "old-footer"
        adapter._delete_message_mock.assert_not_awaited()
        assert len(adapter._edit_calls) == 1
        assert "📋 tc:" in adapter._edit_calls[0]

    async def test_standard_output_sends_footer(self, test_db):
        """Standard output should send a separate footer message."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        if not session.adapter_metadata:
            session.adapter_metadata = SessionAdapterMetadata()
        session.adapter_metadata = SessionAdapterMetadata(telegram=TelegramAdapterMetadata())
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

        # Output + footer = at least 2 sends
        assert len(adapter._send_calls) >= 2
        latest = await test_db.get_session(session.session_id)
        assert latest.get_metadata().get_ui().get_telegram() is not None
        assert latest.get_metadata().get_ui().get_telegram().footer_message_id is not None

    async def test_standard_output_wraps_in_code_block(self, test_db):
        """Standard output is wrapped in code fences by base format_message."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        await test_db.update_session(session.session_id, active_agent="codex")
        session = await test_db.get_session(session.session_id)

        output = "simple tmux output line"
        await adapter.send_output_update(
            session,
            output,
            time.time(),
            time.time(),
        )

        assert adapter._send_calls
        sent_text, _metadata = adapter._send_calls[0]
        assert sent_text.startswith("```")
        assert "\n```" in sent_text
        assert "simple tmux output line" in sent_text

    async def test_footer_places_status_line_last(self, test_db):
        """Footer should place timer/status information at the bottom."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        status_line = "🟡 started 10:00:00 · active 10:00:08 · 1.2KB"
        footer_text = adapter._build_footer_text(session, status_line=status_line)
        lines = footer_text.splitlines()

        assert lines[-1] == status_line
        assert any(line.startswith("📋 tc:") for line in lines[:-1])


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


class TestFormatOutput:
    """Test format_output method — base UiAdapter produces plain text code block."""

    def test_wraps_output_in_code_block(self):
        """Base format_output wraps tmux output in code fences without escaping."""
        adapter = MockUiAdapter()
        output = "Here is code:\n```python\nprint('hello')\n```\nEnd"

        result = adapter.format_output(output)

        assert result.startswith("```\n")
        # Internal ``` should NOT be escaped (base class is platform-agnostic)
        assert "```python" in result

    def test_preserves_output_without_code_blocks(self):
        """Normal output without ``` is unchanged."""
        adapter = MockUiAdapter()
        output = "Simple tmux output\nNo code blocks here"

        result = adapter.format_output(output)

        assert "```\nSimple tmux output\nNo code blocks here\n```" in result

    def test_no_escaping_in_base_class(self):
        """Base class does not escape backslashes or special chars."""
        adapter = MockUiAdapter()
        output = "path C:\\repo\\teleclaude"

        result = adapter.format_output(output)

        # Backslashes should pass through unmodified
        assert "C:\\repo\\teleclaude" in result

    def test_empty_output_returns_empty(self):
        """Empty input returns empty string."""
        adapter = MockUiAdapter()
        assert adapter.format_output("") == ""


@pytest.mark.asyncio
class TestSendThreadedOutput:
    """Test send_threaded_output smart pagination and overflow handling."""

    @pytest.fixture(autouse=True)
    def _enable_threaded_output(self):
        with patch("teleclaude.adapters.ui_adapter.is_threaded_output_enabled", return_value=True):
            yield

    async def test_normal_sends_new_message(self, test_db):
        """Text fits in limit with no existing message → sends new."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        session.adapter_metadata = SessionAdapterMetadata(telegram=TelegramAdapterMetadata())
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        session = await test_db.get_session(session.session_id)

        result = await adapter.send_threaded_output(session, "Hello world")

        assert result == "msg-123"
        assert len(adapter._send_calls) >= 1
        # The output message should contain "Hello world"
        assert any("Hello world" in text for text, _ in adapter._send_calls)

    async def test_edits_existing_message(self, test_db):
        """Text fits in limit with existing output_message_id → edits."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        await test_db.set_output_message_id(session.session_id, "msg-456")
        session = await test_db.get_session(session.session_id)

        result = await adapter.send_threaded_output(session, "Updated text")

        assert result == "msg-456"
        assert len(adapter._edit_calls) == 1
        assert "Updated text" in adapter._edit_calls[0]

    async def test_digest_noop_skips_edit(self, test_db):
        """Same content digest → returns early without edit."""
        from hashlib import sha256

        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        text = "Same text"
        digest = sha256(text.encode("utf-8")).hexdigest()
        await test_db.set_output_message_id(session.session_id, "msg-789")
        await test_db.update_session(
            session.session_id,
            last_output_digest=digest,
        )
        session = await test_db.get_session(session.session_id)

        result = await adapter.send_threaded_output(session, text)

        assert result == "msg-789"
        assert len(adapter._edit_calls) == 0
        assert len(adapter._send_calls) == 0

    async def test_no_active_text_returns_existing_id(self, test_db):
        """No new text after char_offset → returns existing message_id."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        # Set char_offset and output_message_id in adapter metadata (not session-level columns)
        session.adapter_metadata = SessionAdapterMetadata(telegram=TelegramAdapterMetadata(char_offset=10))
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        await test_db.set_output_message_id(session.session_id, "msg-existing")
        session = await test_db.get_session(session.session_id)

        result = await adapter.send_threaded_output(session, "0123456789")  # exactly 10 chars

        assert result == "msg-existing"
        assert len(adapter._send_calls) == 0
        assert len(adapter._edit_calls) == 0

    async def test_resets_offset_when_text_shorter(self, test_db):
        """Text shorter than char_offset → resets offset and continues."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        # Set char_offset in adapter metadata
        session.adapter_metadata = SessionAdapterMetadata(telegram=TelegramAdapterMetadata(char_offset=1000))
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        session = await test_db.get_session(session.session_id)

        result = await adapter.send_threaded_output(session, "short")

        assert result == "msg-123"
        # Offset should have been reset in adapter metadata
        refreshed = await test_db.get_session(session.session_id)
        assert refreshed.get_metadata().get_ui().get_telegram().char_offset == 0

    async def test_nonzero_offset_slices_text_correctly(self, test_db):
        """Text with nonzero char_offset → only the portion after offset is sent."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        # Set char_offset in adapter metadata
        session.adapter_metadata = SessionAdapterMetadata(telegram=TelegramAdapterMetadata(char_offset=5))
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        session = await test_db.get_session(session.session_id)

        result = await adapter.send_threaded_output(session, "Hello World!")

        assert result == "msg-123"
        # Should send only the text after offset (no structural continuation prefix for plain text)
        assert len(adapter._send_calls) >= 1
        sent_text = adapter._send_calls[0][0]
        assert " World!" in sent_text

    async def test_overflow_splits_into_multiple_messages(self, test_db):
        """Text exceeding limit → seals first chunk, sends new for remainder."""
        adapter = MockUiAdapter()
        # Set a small limit for testing
        adapter.max_message_size = 100
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        session.adapter_metadata = SessionAdapterMetadata(telegram=TelegramAdapterMetadata())
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        session = await test_db.get_session(session.session_id)

        # Create text that will overflow the 100-char limit (limit - 10 = 90 effective)
        long_text = "word " * 30  # 150 chars

        result = await adapter.send_threaded_output(session, long_text)

        # Should have sent at least 2 messages (sealed + remainder)
        assert len(adapter._send_calls) >= 2
        assert result is not None

        # Verify char_offset was advanced in adapter metadata
        refreshed = await test_db.get_session(session.session_id)
        assert refreshed.get_metadata().get_ui().get_telegram().char_offset > 0

    async def test_overflow_preserves_markdown_escape_boundaries(self, test_db):
        """MarkdownV2 threaded overflow should not split between backslash and escaped char."""
        adapter = MockUiAdapter()
        # Keep room tight so chunking happens at problematic boundaries.
        adapter.max_message_size = 30
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        session.adapter_metadata = SessionAdapterMetadata(telegram=TelegramAdapterMetadata())
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        session = await test_db.get_session(session.session_id)

        # Pre-escaped MarkdownV2 payload (same shape coordinator sends to threaded output).
        escaped_text = "a\\." * 20
        result = await adapter.send_threaded_output(session, escaped_text)
        assert result is not None

        # Inspect threaded content messages (footer has no escaped dots).
        content_chunks = [text for text, _meta in adapter._send_calls if "\\.\\.\\." in text or "a\\." in text]
        assert content_chunks, "Expected threaded content chunks to be sent"

        for chunk in content_chunks:
            for idx, char in enumerate(chunk):
                if char == ".":
                    assert idx > 0 and chunk[idx - 1] == "\\", f"Found unescaped dot in chunk: {chunk!r}"

    async def test_overflow_reopens_code_block_in_next_chunk(self, test_db):
        """When a chunk is closed for balance, next chunk should reopen the fence."""
        adapter = MockUiAdapter()
        adapter.max_message_size = 70
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        session.adapter_metadata = SessionAdapterMetadata(telegram=TelegramAdapterMetadata())
        await test_db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        session = await test_db.get_session(session.session_id)

        text = "```python\n" + ("x" * 180) + "\n```"
        result = await adapter.send_threaded_output(session, text)
        assert result is not None

        content_chunks = [chunk for chunk, _meta in adapter._send_calls if "x" in chunk]
        assert len(content_chunks) >= 2
        # Continuation chunks reopen the code fence (structural prefix from MarkdownV2 state)
        assert any(chunk.startswith("```\n") for chunk in content_chunks[1:])


@pytest.mark.asyncio
class TestSendOutputUpdateSuppression:
    """Test send_output_update suppression fallback for threaded output."""

    async def test_suppressed_when_threaded_active(self, test_db):
        """Threaded output experiment on → suppressed immediately."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        await test_db.update_session(session.session_id, active_agent="gemini")
        session = await test_db.get_session(session.session_id)

        with patch("teleclaude.adapters.ui_adapter.is_threaded_output_enabled", return_value=True):
            result = await adapter.send_output_update(session, "output text", time.time(), time.time())

        assert result is None
        assert len(adapter._send_calls) == 0
        assert len(adapter._edit_calls) == 0

    async def test_suppressed_when_threaded_active_no_output_message_id(self, test_db):
        """Threaded experiment on but no output_message_id → still suppressed."""
        adapter = MockUiAdapter()
        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        session.adapter_metadata = SessionAdapterMetadata(telegram=TelegramAdapterMetadata())  # No output_message_id
        await test_db.update_session(
            session.session_id, adapter_metadata=session.adapter_metadata, active_agent="gemini"
        )
        session = await test_db.get_session(session.session_id)

        with patch("teleclaude.adapters.ui_adapter.is_threaded_output_enabled", return_value=True):
            result = await adapter.send_output_update(session, "output text", time.time(), time.time())

        assert result is None
        assert len(adapter._send_calls) == 0
        assert len(adapter._edit_calls) == 0


@pytest.mark.asyncio
class TestTypingIndicator:
    """Test typing indicator call site and behavior."""

    async def test_dispatch_command_calls_typing_indicator_for_normal_session(self, test_db):
        """_dispatch_command calls send_typing_indicator when lifecycle_status != 'headless'."""
        adapter = MockUiAdapter()
        # Mock client methods that _dispatch_command calls
        adapter.client.pre_handle_command = AsyncMock()
        adapter.client.post_handle_command = AsyncMock()
        adapter.client.broadcast_command_action = AsyncMock()
        adapter.client.adapters = {"telegram": adapter}

        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        # Ensure lifecycle_status is NOT headless
        await test_db.update_session(session.session_id, lifecycle_status="active")
        session = await test_db.get_session(session.session_id)

        # Mock send_typing_indicator to track calls
        typing_called = False

        async def mock_typing(s):
            nonlocal typing_called
            typing_called = True

        adapter.send_typing_indicator = mock_typing

        # Mock handler
        handler_called = False

        async def mock_handler():
            nonlocal handler_called
            handler_called = True
            return "handler-result"

        # Patch db module to use test_db
        with patch("teleclaude.adapters.ui_adapter.db", test_db):
            # Call _dispatch_command
            result = await adapter._dispatch_command(
                session,
                "msg-123",
                MessageMetadata(origin="telegram"),
                "test_command",
                {"test": "payload"},
                mock_handler,
            )

        assert typing_called, "send_typing_indicator should be called for normal sessions"
        assert handler_called, "Handler should be executed"
        assert result == "handler-result"

    async def test_dispatch_command_skips_typing_indicator_for_headless_session(self, test_db):
        """_dispatch_command skips send_typing_indicator when lifecycle_status == 'headless'."""
        adapter = MockUiAdapter()
        # Mock client methods that _dispatch_command calls
        adapter.client.pre_handle_command = AsyncMock()
        adapter.client.post_handle_command = AsyncMock()
        adapter.client.broadcast_command_action = AsyncMock()
        adapter.client.adapters = {"telegram": adapter}

        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        # Set lifecycle_status to headless
        await test_db.update_session(session.session_id, lifecycle_status="headless")
        session = await test_db.get_session(session.session_id)

        # Mock send_typing_indicator to track calls
        typing_called = False

        async def mock_typing(s):
            nonlocal typing_called
            typing_called = True

        adapter.send_typing_indicator = mock_typing

        # Mock handler
        handler_called = False

        async def mock_handler():
            nonlocal handler_called
            handler_called = True
            return "handler-result"

        # Patch db module to use test_db
        with patch("teleclaude.adapters.ui_adapter.db", test_db):
            # Call _dispatch_command
            result = await adapter._dispatch_command(
                session,
                "msg-123",
                MessageMetadata(origin="telegram"),
                "test_command",
                {"test": "payload"},
                mock_handler,
            )

        assert not typing_called, "send_typing_indicator should NOT be called for headless sessions"
        assert handler_called, "Handler should still be executed"
        assert result == "handler-result"

    async def test_dispatch_command_continues_on_typing_indicator_failure(self, test_db):
        """_dispatch_command continues executing handler even if send_typing_indicator raises exception."""
        adapter = MockUiAdapter()
        # Mock client methods that _dispatch_command calls
        adapter.client.pre_handle_command = AsyncMock()
        adapter.client.post_handle_command = AsyncMock()
        adapter.client.broadcast_command_action = AsyncMock()
        adapter.client.adapters = {"telegram": adapter}

        session = await test_db.create_session(
            computer_name="TestPC",
            tmux_session_name="test",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )
        await test_db.update_session(session.session_id, lifecycle_status="active")
        session = await test_db.get_session(session.session_id)

        # Mock send_typing_indicator to raise exception
        async def failing_typing(s):
            raise RuntimeError("Typing indicator failed")

        adapter.send_typing_indicator = failing_typing

        # Mock handler
        handler_called = False

        async def mock_handler():
            nonlocal handler_called
            handler_called = True
            return "handler-result"

        # Patch db module to use test_db
        with patch("teleclaude.adapters.ui_adapter.db", test_db):
            # Call _dispatch_command - should not raise exception
            result = await adapter._dispatch_command(
                session,
                "msg-123",
                MessageMetadata(origin="telegram"),
                "test_command",
                {"test": "payload"},
                mock_handler,
            )

        assert handler_called, "Handler should execute despite typing indicator failure"
        assert result == "handler-result"
