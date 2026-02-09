"""Integration tests for output truncation + transcript download flow."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Optional, TypedDict
from unittest.mock import MagicMock

import pytest
from telegram import InlineKeyboardButton

from teleclaude.adapters.telegram.callback_handlers import CallbackHandlersMixin
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.agents import AgentName
from teleclaude.core.db import Db
from teleclaude.core.models import MessageMetadata, SessionAdapterMetadata, TelegramAdapterMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.utils.transcript import parse_session_transcript


class TestTelegramAdapter(UiAdapter):
    """Minimal Telegram adapter for output truncation tests."""

    ADAPTER_KEY = "telegram"
    max_message_size = 500
    __test__ = False

    def __init__(self, client: object) -> None:
        super().__init__(client)  # registers event listeners
        self.sent: list[tuple[str, MessageMetadata]] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def create_channel(self, session: object, title: str, metadata: object) -> str:
        _ = (session, title, metadata)
        return "channel-1"

    async def update_channel_title(self, session: object, title: str) -> bool:
        _ = (session, title)
        return True

    async def close_channel(self, session: object) -> bool:
        _ = session
        return True

    async def reopen_channel(self, session: object) -> bool:
        _ = session
        return True

    async def delete_channel(self, session: object) -> bool:
        _ = session
        return True

    async def send_message(
        self,
        session: object,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> Optional[str]:
        self.sent.append((text, metadata or MessageMetadata()))
        return "msg-1"

    async def edit_message(
        self,
        _session: object,
        _message_id: str,
        _text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        _ = metadata
        return False

    async def delete_message(self, session: object, message_id: str) -> bool:
        _ = (session, message_id)
        return True

    async def send_file(
        self,
        session: object,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        _ = (session, file_path, caption, metadata)
        return "file-1"

    async def discover_peers(self) -> list[object]:
        return []

    async def poll_output_stream(self, session: object, timeout: float = 300.0):
        _ = (session, timeout)
        if False:
            yield ""

    def get_max_message_length(self) -> int:
        return self.max_message_size

    def get_ai_session_poll_interval(self) -> float:
        return 0.1

    def format_message(self, tmux_output: str, status_line: str) -> str:
        return UiAdapter.format_message(self, tmux_output, status_line)

    def _build_output_metadata(self, session: object, is_truncated: bool) -> MessageMetadata:
        metadata = TelegramAdapter._build_output_metadata(self, session, is_truncated)
        if is_truncated and getattr(session, "native_log_file", None):
            metadata.reply_markup = type(
                "MockMarkup",
                (),
                {
                    "inline_keyboard": [
                        [
                            InlineKeyboardButton(
                                "📎 Download Agent session",
                                callback_data=f"download_full:{session.session_id}",
                            )
                        ]
                    ]
                },
            )()
        return metadata


class DummyMessage:
    def __init__(self, *, chat_id: int, message_thread_id: int, message_id: int) -> None:
        self.chat_id = chat_id
        self.message_thread_id = message_thread_id
        self.message_id = message_id


class DummyCallbackQuery:
    def __init__(self, message: DummyMessage) -> None:
        self.message = message
        self.edits: list[str] = []

    async def edit_message_text(self, text: str, **_kwargs: object) -> None:
        self.edits.append(text)


class SentDocumentData(TypedDict):
    """Structure for sent document data."""

    chat_id: int
    message_thread_id: int
    file_path: str
    filename: str
    caption: str | None


class DummyDownloadAdapter(CallbackHandlersMixin):
    """Adapter stub for download callback handling."""

    def __init__(self) -> None:
        self.sent: SentDocumentData | None = None

    async def _send_document_with_retry(
        self,
        *,
        chat_id: int,
        message_thread_id: int,
        file_path: str,
        filename: str,
        caption: str | None = None,
    ) -> DummyMessage:
        self.sent = {
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
            "file_path": file_path,
            "filename": filename,
            "caption": caption,
        }
        return DummyMessage(chat_id=chat_id, message_thread_id=message_thread_id, message_id=777)


@pytest.fixture
async def session_manager(tmp_path: Path):
    db_path = tmp_path / "download-test.db"
    manager = Db(str(db_path))
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.close()
        db_path.unlink(missing_ok=True)


@pytest.mark.integration
async def test_output_truncation_adds_download_button(session_manager: Db, monkeypatch: pytest.MonkeyPatch) -> None:
    """Truncated output should include Telegram download button when transcript exists."""
    from teleclaude.adapters import ui_adapter as ui_adapter_module

    monkeypatch.setattr(ui_adapter_module, "db", session_manager)
    monkeypatch.setattr(ui_adapter_module.config.computer, "timezone", "UTC", raising=False)

    adapter = TestTelegramAdapter(client=MagicMock())

    session = await session_manager.create_session(
        computer_name="TestPC",
        tmux_session_name="tmux-test",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Output Test",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata()),
        project_path="/tmp",
    )
    transcript_path = Path(tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl").name)
    transcript_path.write_text("{}\n")
    await session_manager.update_session(session.session_id, native_log_file=str(transcript_path))
    session = await session_manager.get_session(session.session_id)
    assert session is not None

    output = "HEAD-" + "X" * 2000
    await adapter.send_output_update(
        session,
        output=output,
        started_at=1000.0,
        last_output_changed_at=1000.0,
    )

    assert adapter.sent, "Expected output message to be sent"
    text, metadata = adapter.sent[0]
    assert "HEAD-" not in text
    # Content is truncated (tail-based) — verify some X's survived header formatting
    assert "XXXX" in text
    assert metadata.reply_markup is not None
    keyboard = metadata.reply_markup.inline_keyboard
    assert keyboard[0][0].callback_data == f"download_full:{session.session_id}"
    transcript_path.unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_full_sends_transcript_and_cleans_temp_file(
    session_manager: Db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Download callback should send transcript and clean temp file."""
    from teleclaude.adapters.telegram import callback_handlers as handlers

    transcript_path = Path(tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl").name)
    transcript_entry = {
        "type": "message",
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
    }
    transcript_path.write_text(json.dumps(transcript_entry) + "\n", encoding="utf-8")

    session = await session_manager.create_session(
        computer_name="TestPC",
        tmux_session_name="tmux-test",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Download Test",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata()),
        project_path="/tmp",
    )
    await session_manager.update_session(
        session.session_id,
        active_agent="claude",
        native_log_file=str(transcript_path),
    )

    monkeypatch.setattr(handlers, "db", session_manager)

    # Patch telegram types used for isinstance checks
    import telegram

    monkeypatch.setattr(telegram, "CallbackQuery", DummyCallbackQuery)
    monkeypatch.setattr(telegram, "Message", DummyMessage)
    monkeypatch.setattr(handlers, "Message", DummyMessage)

    adapter = DummyDownloadAdapter()
    query = DummyCallbackQuery(DummyMessage(chat_id=123, message_thread_id=456, message_id=1))

    await adapter._handle_download_full(query, [session.session_id])

    sent = adapter.sent
    assert sent
    tmp_path = Path(str(sent["file_path"]))
    assert not tmp_path.exists(), "Temp file should be cleaned up"
    pending = await session_manager.get_pending_deletions(session.session_id, deletion_type="feedback")
    assert "777" in pending

    # Sanity check: transcript render succeeds
    markdown = parse_session_transcript(str(transcript_path), "Download Test", agent_name=AgentName.CLAUDE)
    assert "hello" in markdown
