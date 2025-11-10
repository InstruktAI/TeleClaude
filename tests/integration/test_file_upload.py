"""Integration tests for file upload flow."""

import asyncio
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core import file_handler
from teleclaude.core.db import Db


@pytest.fixture
async def session_manager():
    """Create temporary session manager."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    manager = Db(db_path)
    await manager.initialize()

    yield manager

    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
async def test_session(session_manager):
    """Create test session."""
    session = await session_manager.create_session(
        computer_name="test-computer",
        tmux_session_name="tmux_test",
        origin_adapter="telegram",
        adapter_metadata={"channel_id": "123"},
        title="Test Session",
    )
    return session


class TestFileUploadFlow:
    """Test end-to-end file upload flow."""

    @pytest.mark.asyncio
    async def test_file_upload_with_claude_code(self, session_manager, test_session):
        """Test complete file upload flow with Claude Code running."""
        sent_keys = []
        sent_messages = []

        async def mock_send_keys(session_name: str, text: str, append_exit_marker: bool) -> bool:
            sent_keys.append((session_name, text, append_exit_marker))
            return True

        async def mock_send_feedback(sid: str, msg: str, append: bool) -> Optional[str]:
            sent_messages.append((sid, msg, append))
            return "msg_123"

        await session_manager.mark_polling(test_session.session_id)
        # Update UX state with output message
        await session_manager.update_ux_state(test_session.session_id, output_message_id="msg_out")

        with (
            patch("teleclaude.core.file_handler.db", session_manager),
            patch("teleclaude.core.file_handler.is_claude_code_running", return_value=True),
            patch("teleclaude.core.file_handler.terminal_bridge.send_keys", side_effect=mock_send_keys),
        ):
            await file_handler.handle_file(
                session_id=test_session.session_id,
                file_path="/tmp/document.pdf",
                filename="document.pdf",
                context={"file_size": 5242880, "upload_type": "document"},
                send_feedback=mock_send_feedback,
            )

        assert len(sent_keys) == 1
        assert sent_keys[0][0] == "tmux_test"
        assert sent_keys[0][1] == "@/tmp/document.pdf"
        assert sent_keys[0][2] is False

        assert len(sent_messages) == 1
        assert "document.pdf" in sent_messages[0][1]
        assert "5.00 MB" in sent_messages[0][1]

    @pytest.mark.asyncio
    async def test_file_upload_without_claude_code(self, session_manager, test_session):
        """Test file upload flow with generic process."""
        sent_keys = []

        async def mock_send_keys(session_name: str, text: str, append_exit_marker: bool) -> bool:
            sent_keys.append((session_name, text, append_exit_marker))
            return True

        async def mock_send_feedback(sid: str, msg: str, append: bool) -> Optional[str]:
            return "msg_123"

        await session_manager.mark_polling(test_session.session_id)
        # Update UX state with output message
        await session_manager.update_ux_state(test_session.session_id, output_message_id="msg_out")

        with (
            patch("teleclaude.core.file_handler.db", session_manager),
            patch("teleclaude.core.file_handler.is_claude_code_running", return_value=False),
            patch("teleclaude.core.file_handler.terminal_bridge.send_keys", side_effect=mock_send_keys),
        ):
            await file_handler.handle_file(
                session_id=test_session.session_id,
                file_path="/tmp/image.jpg",
                filename="image.jpg",
                context={"file_size": 1048576, "upload_type": "photo"},
                send_feedback=mock_send_feedback,
            )

        assert len(sent_keys) == 1
        assert sent_keys[0][1] == "/tmp/image.jpg"

    @pytest.mark.asyncio
    async def test_rejection_when_no_process_active(self, session_manager, test_session):
        """Test file is rejected when no process running."""
        sent_messages = []

        async def mock_send_feedback(sid: str, msg: str, append: bool) -> Optional[str]:
            sent_messages.append((sid, msg, append))
            return "msg_123"

        await session_manager.set_polling_inactive(test_session.session_id)

        with patch("teleclaude.core.file_handler.db", session_manager):
            await file_handler.handle_file(
                session_id=test_session.session_id,
                file_path="/tmp/file.pdf",
                filename="file.pdf",
                context={},
                send_feedback=mock_send_feedback,
            )

        assert len(sent_messages) == 1
        assert "requires an active process" in sent_messages[0][1]
        assert "File saved: file.pdf" in sent_messages[0][1]

    @pytest.mark.asyncio
    async def test_session_cleanup_deletes_files(self, session_manager, test_session):
        """Test session cleanup removes uploaded files."""
        import shutil

        session_dir = Path("session_files") / test_session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        test_file = session_dir / "test_document.pdf"
        test_file.write_text("test content")

        assert test_file.exists()

        try:
            shutil.rmtree(session_dir)

            assert not session_dir.exists()
            assert not test_file.exists()
        finally:
            if session_dir.exists():
                shutil.rmtree(session_dir)
