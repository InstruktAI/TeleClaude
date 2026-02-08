"""Integration tests for file upload flow."""

import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from teleclaude.core import file_handler, tmux_io
from teleclaude.core.db import Db
from teleclaude.core.events import FileEventContext
from teleclaude.core.models import MessageMetadata, SessionAdapterMetadata, TelegramAdapterMetadata
from teleclaude.core.origins import InputOrigin


@pytest.fixture
async def session_manager():
    """Create temporary session manager."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    manager = Db(db_path)
    await manager.initialize()

    try:
        yield manager
    finally:
        await manager.close()
        Path(db_path).unlink(missing_ok=True)


@pytest.fixture
async def test_session(session_manager):
    """Create test session with proper adapter metadata including output_message_id."""
    session = await session_manager.create_session(
        computer_name="test-computer",
        tmux_session_name="tmux_test",
        last_input_origin=InputOrigin.TELEGRAM.value,
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=12345)),
        title="Test Session",
        project_path="/tmp",
    )
    # Set output_message_id via dedicated column (not adapter_metadata blob)
    await session_manager.set_output_message_id(session.session_id, "msg_out")
    session = await session_manager.get_session(session.session_id)
    return session


class TestFileUploadFlow:
    """Test end-to-end file upload flow."""

    @pytest.mark.asyncio
    async def test_file_upload_with_claude_code(self, session_manager, test_session):
        """Test complete file upload flow with Claude Code running."""
        sent_keys = []
        sent_messages = []

        async def mock_send_keys(session, text: str, **kwargs: object) -> bool:  # type: ignore[no-untyped-def]
            sent_keys.append((session, text))
            return True

        async def mock_send_message(sid: str, msg: str, metadata: MessageMetadata) -> Optional[str]:
            sent_messages.append((sid, msg))
            return "msg_123"

        with (
            patch("teleclaude.core.file_handler.db", session_manager),
            patch("teleclaude.core.file_handler.is_agent_running", return_value=True),
            patch("teleclaude.core.file_handler.tmux_bridge.is_process_running", return_value=True),
            patch("teleclaude.core.file_handler.tmux_io.process_text", side_effect=mock_send_keys),
        ):
            await file_handler.handle_file(
                session_id=test_session.session_id,
                file_path="/tmp/document.pdf",
                filename="document.pdf",
                context=FileEventContext(
                    session_id=test_session.session_id,
                    file_path="/tmp/document.pdf",
                    filename="document.pdf",
                    file_size=5242880,
                ),
                send_message=mock_send_message,
            )

        assert len(sent_keys) == 1
        # Path is resolved to absolute path (on macOS /tmp -> /private/tmp)
        expected_path = str(Path("/tmp/document.pdf").resolve())
        expected_text = tmux_io.wrap_bracketed_paste(f"@{expected_path}")
        assert sent_keys[0][1] == expected_text

        assert len(sent_messages) == 1
        assert "document.pdf" in sent_messages[0][1]
        assert "5.00 MB" in sent_messages[0][1]

    @pytest.mark.asyncio
    async def test_file_upload_without_claude_code(self, session_manager, test_session):
        """Test file upload flow with generic process."""
        sent_keys = []

        async def mock_send_keys(session, text: str, **kwargs: object) -> bool:  # type: ignore[no-untyped-def]
            sent_keys.append((session, text))
            return True

        async def mock_send_message(sid: str, msg: str, metadata: MessageMetadata) -> Optional[str]:
            return "msg_123"

        with (
            patch("teleclaude.core.file_handler.db", session_manager),
            patch("teleclaude.core.file_handler.is_agent_running", return_value=False),
            patch("teleclaude.core.file_handler.tmux_bridge.is_process_running", return_value=True),
            patch("teleclaude.core.file_handler.tmux_io.process_text", side_effect=mock_send_keys),
        ):
            await file_handler.handle_file(
                session_id=test_session.session_id,
                file_path="/tmp/image.jpg",
                filename="image.jpg",
                context=FileEventContext(
                    session_id=test_session.session_id,
                    file_path="/tmp/image.jpg",
                    filename="image.jpg",
                    file_size=1048576,
                ),
                send_message=mock_send_message,
            )

        assert len(sent_keys) == 1
        expected_path = str(Path("/tmp/image.jpg").resolve())
        expected_text = tmux_io.wrap_bracketed_paste(expected_path)
        assert sent_keys[0][1] == expected_text

    @pytest.mark.asyncio
    async def test_rejection_when_no_process_active(self, session_manager, test_session):
        """Test file is rejected when no process running."""
        sent_messages = []

        async def mock_send_message(sid: str, msg: str, metadata: MessageMetadata) -> Optional[str]:
            sent_messages.append((sid, msg))
            return "msg_123"

        with (
            patch("teleclaude.core.file_handler.db", session_manager),
            patch("teleclaude.core.file_handler.tmux_bridge.is_process_running", return_value=False),
        ):
            await file_handler.handle_file(
                session_id=test_session.session_id,
                file_path="/tmp/file.pdf",
                filename="file.pdf",
                context=FileEventContext(
                    session_id=test_session.session_id,
                    file_path="/tmp/file.pdf",
                    filename="file.pdf",
                ),
                send_message=mock_send_message,
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
