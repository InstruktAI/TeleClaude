"""Unit tests for AdapterClient API-origin routing."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.models import MessageMetadata, Session, SessionAdapterMetadata
from teleclaude.core.origins import InputOrigin


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

    async def send_message(
        self, session: Session, text: str, *, metadata: MessageMetadata | None = None, multi_message: bool = False
    ) -> str:
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


def _make_session(last_input_origin: str) -> Session:
    return Session(
        session_id="sess-1",
        computer_name="TestPC",
        tmux_session_name="terminal:deadbeef",
        last_input_origin=last_input_origin,
        title="Tmux",
        adapter_metadata=SessionAdapterMetadata(),
        created_at=None,
        last_activity=None,
        project_path="~",
        description=None,
        initiated_by_ai=False,
    )


@pytest.mark.asyncio
async def test_terminal_origin_send_message_skips_ui():
    """Test that API-origin send_message routes to UI adapter."""
    client = AdapterClient()
    adapter = DummyUiAdapter(client)
    client.register_adapter("telegram", adapter)

    session = _make_session(InputOrigin.API.value)

    # Mock db.add_pending_deletion since send_message auto-tracks ephemeral messages
    with patch("teleclaude.core.adapter_client.db", new=AsyncMock()):
        message_id = await client.send_message(session, "hello")

    assert message_id == "msg-1"
    assert adapter.sent_messages == [("sess-1", "hello")]


@pytest.mark.asyncio
async def test_terminal_origin_send_message_ephemeral_tracks_deletion():
    """Test that ephemeral messages are auto-tracked for deletion."""
    client = AdapterClient()
    adapter = DummyUiAdapter(client)
    client.register_adapter("telegram", adapter)
    session = _make_session("telegram")

    mock_db = AsyncMock()
    with patch("teleclaude.core.adapter_client.db", mock_db):
        await client.send_message(session, "ephemeral message")

    # Verify auto-tracking was called with notice deletion type
    assert mock_db.add_pending_deletion.call_args == (("sess-1", "msg-1"), {"deletion_type": "feedback"})
