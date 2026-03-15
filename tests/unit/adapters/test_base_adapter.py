from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.core.models import Session
from teleclaude.core.models._adapter import PeerInfo

pytestmark = pytest.mark.unit


async def _empty_output_stream() -> AsyncIterator[str]:
    if False:
        yield ""


class DummyAdapter(BaseAdapter):
    ADAPTER_KEY = "dummy"

    async def poll_output_stream(self, session: Session, timeout: float = 300.0) -> AsyncIterator[str]:
        return _empty_output_stream()

    async def send_general_message(self, text: str, *, metadata: object | None = None) -> str:
        return text

    async def send_message(
        self,
        session: Session,
        text: str,
        *,
        metadata: object | None = None,
        multi_message: bool = False,
    ) -> str:
        return text

    async def send_file(
        self,
        session: Session,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: object | None = None,
    ) -> str:
        return file_path

    async def edit_message(
        self,
        session: Session,
        message_id: str,
        text: str,
        *,
        metadata: object | None = None,
    ) -> bool:
        return True

    async def delete_message(self, session: Session, message_id: str) -> bool:
        return True

    async def create_channel(self, session: Session, title: str, metadata: object) -> str:
        return title

    async def update_channel_title(self, session: Session, title: str) -> bool:
        return True

    async def close_channel(self, session: Session) -> bool:
        return True

    async def reopen_channel(self, session: Session) -> bool:
        return True

    async def delete_channel(self, session: Session) -> bool:
        return True

    async def discover_peers(self) -> list[PeerInfo]:
        return []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _make_session(session_id: str = "session-1") -> Session:
    return Session(
        session_id=session_id,
        computer_name="machine",
        tmux_session_name="tmux-session",
        title="Session",
    )


def test_metadata_uses_adapter_key_as_origin() -> None:
    adapter = DummyAdapter()

    metadata = adapter._metadata(parse_mode=None, title="Observed Title")

    assert metadata.origin == "dummy"
    assert metadata.title == "Observed Title"


def test_default_polling_methods_raise_not_implemented() -> None:
    adapter = DummyAdapter()

    with pytest.raises(NotImplementedError):
        adapter.get_ai_session_poll_interval()

    with pytest.raises(NotImplementedError):
        adapter.get_max_message_length()


@pytest.mark.asyncio
async def test_get_session_returns_db_lookup_result() -> None:
    adapter = DummyAdapter()
    session = _make_session()

    with patch("teleclaude.adapters.base_adapter.db") as db:
        db.get_session = AsyncMock(return_value=session)

        result = await adapter._get_session("session-1")

    assert result is session
    db.get_session.assert_awaited_once_with("session-1")


@pytest.mark.asyncio
async def test_get_session_raises_value_error_when_lookup_is_empty() -> None:
    adapter = DummyAdapter()

    with patch("teleclaude.adapters.base_adapter.db") as db:
        db.get_session = AsyncMock(return_value=None)

        with pytest.raises(ValueError):
            await adapter._get_session("missing-session")

    db.get_session.assert_awaited_once_with("missing-session")


@pytest.mark.asyncio
async def test_send_error_feedback_leaves_dependencies_untouched() -> None:
    adapter = DummyAdapter()

    with patch("teleclaude.adapters.base_adapter.db") as db:
        with patch.object(adapter, "send_message", new=AsyncMock()) as send_message:
            await adapter.send_error_feedback("session-1", "boom")

    db.get_session.assert_not_called()
    send_message.assert_not_awaited()
