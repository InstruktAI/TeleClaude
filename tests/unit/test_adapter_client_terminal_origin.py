"""Unit tests for AdapterClient terminal-origin routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.models import MessageMetadata, Session, SessionAdapterMetadata


class DummyUiAdapter(UiAdapter):
    """Minimal UI adapter for routing tests."""

    ADAPTER_KEY = "telegram"

    def __init__(self, client: AdapterClient) -> None:
        # Skip UiAdapter.__init__ event wiring for unit tests
        self.client = client
        self.sent_messages: list[tuple[str, str]] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def create_channel(self, session: Session, title: str, metadata) -> str:  # type: ignore[override]
        return "topic-1"

    async def update_channel_title(self, session: Session, title: str) -> bool:
        return True

    async def close_channel(self, session: Session) -> bool:
        return True

    async def reopen_channel(self, session: Session) -> bool:
        return True

    async def delete_channel(self, session: Session) -> bool:
        return True

    async def send_message(self, session: Session, text: str, *, metadata: MessageMetadata | None = None) -> str:
        self.sent_messages.append((session.session_id, text))
        return "msg-1"

    async def edit_message(
        self, session: Session, message_id: str, text: str, *, metadata: MessageMetadata | None = None
    ) -> bool:
        return True

    async def delete_message(self, session: Session, message_id: str) -> bool:
        return True

    async def send_file(
        self, session: Session, file_path: str, *, caption: str | None = None, metadata: MessageMetadata | None = None
    ) -> str:
        return "file-1"

    async def discover_peers(self):
        return []

    async def poll_output_stream(self, session: Session, timeout: float = 300.0):
        if False:
            yield ""
        return


def _make_terminal_session() -> Session:
    return Session(
        session_id="sess-1",
        computer_name="TestPC",
        tmux_session_name="terminal:deadbeef",
        origin_adapter="rest",
        title="Terminal",
        adapter_metadata=SessionAdapterMetadata(),
        created_at=None,
        last_activity=None,
        working_directory="~",
        description=None,
        initiated_by_ai=False,
    )


@pytest.mark.asyncio
async def test_terminal_origin_send_message_broadcasts_to_ui():
    client = AdapterClient()
    adapter = DummyUiAdapter(client)
    client.register_adapter("telegram", adapter)

    session = _make_terminal_session()

    # Mock db.add_pending_deletion since send_message auto-tracks ephemeral messages
    with patch("teleclaude.core.adapter_client.db", new=AsyncMock()):
        message_id = await client.send_message(session, "hello")

    assert message_id == "msg-1"
    assert adapter.sent_messages == [(session.session_id, "hello")]


@pytest.mark.asyncio
async def test_terminal_origin_send_message_ephemeral_tracks_deletion():
    """Test that ephemeral messages are auto-tracked for deletion."""
    client = AdapterClient()
    adapter = DummyUiAdapter(client)
    client.register_adapter("telegram", adapter)
    session = _make_terminal_session()

    mock_db = AsyncMock()
    with patch("teleclaude.core.adapter_client.db", mock_db):
        await client.send_message(session, "ephemeral message")

    # Verify auto-tracking was called with user_input deletion type
    mock_db.add_pending_deletion.assert_called_once_with("sess-1", "msg-1", deletion_type="user_input")
