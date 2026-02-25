"""Unit tests for AdapterClient pre/post handler gating."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.models import MessageMetadata, Session, SessionAdapterMetadata
from teleclaude.core.origins import InputOrigin


class PrePostUiAdapter(UiAdapter):
    """UI adapter that records pre/post handler calls."""

    ADAPTER_KEY = "telegram"

    def __init__(self, client: AdapterClient) -> None:
        # Skip UiAdapter.__init__ event wiring for unit tests
        self.client = client
        self.pre_calls: list[str] = []
        self.post_calls: list[tuple[str, str]] = []

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

    async def _pre_handle_user_input(self, session: Session) -> None:
        self.pre_calls.append(session.session_id)

    async def _post_handle_user_input(self, session: Session, message_id: str) -> None:
        self.post_calls.append((session.session_id, message_id))


def _make_session() -> Session:
    return Session(
        session_id="sess-1",
        computer_name="TestPC",
        tmux_session_name="tc_sess_1",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test",
        adapter_metadata=SessionAdapterMetadata(),
    )


@pytest.mark.asyncio
async def test_pre_post_handlers_run_with_message_id():
    """Pre/post handlers should run when payload has message_id."""
    client = AdapterClient()
    adapter = PrePostUiAdapter(client)
    client.register_adapter("telegram", adapter)

    session = _make_session()

    mock_db = AsyncMock()
    mock_db.update_session = AsyncMock()

    with patch("teleclaude.adapters.ui_adapter.db", mock_db):
        await adapter._dispatch_command(
            session,
            "123",
            MessageMetadata(origin=InputOrigin.TELEGRAM.value),
            "send_message",
            {"text": "hello"},
            AsyncMock(),
        )

    assert adapter.pre_calls == [session.session_id]
    assert adapter.post_calls == [(session.session_id, "123")]


@pytest.mark.asyncio
async def test_pre_post_handlers_skip_without_message_id():
    """Pre/post handlers should not run when payload has no message_id."""
    client = AdapterClient()
    adapter = PrePostUiAdapter(client)
    client.register_adapter("telegram", adapter)

    session = _make_session()

    mock_db = AsyncMock()
    mock_db.update_session = AsyncMock()

    with patch("teleclaude.adapters.ui_adapter.db", mock_db):
        await adapter._dispatch_command(
            session,
            None,
            MessageMetadata(origin=InputOrigin.TELEGRAM.value),
            "send_message",
            {"text": "hello"},
            AsyncMock(),
        )

    assert adapter.pre_calls == []
    assert adapter.post_calls == []


@pytest.mark.asyncio
async def test_ui_lane_error_log_identifies_adapter_and_session(caplog):
    """ERROR log from a lane failure must include adapter key and session ID (R5.1).

    R5.1: Error logs must identify adapter lane and session for ingress/provisioning failures.
    A regression dropping adapter type or session ID from the error log must be caught.
    """

    class FailingAdapter(PrePostUiAdapter):
        async def send_message(  # type: ignore[override]
            self, session: Session, text: str, *, metadata: MessageMetadata | None = None
        ) -> str:
            raise RuntimeError("simulated lane failure")

    client = AdapterClient()
    adapter = FailingAdapter(client)
    session = _make_session()  # session_id="sess-1"

    with patch(
        "teleclaude.core.adapter_client.get_display_title_for_session",
        AsyncMock(return_value="Test Session"),
    ):
        with caplog.at_level(logging.ERROR, logger="teleclaude.core.adapter_client"):
            result = await client._run_ui_lane(
                session,
                "telegram",
                adapter,
                lambda a, s: a.send_message(s, "test text"),
            )

    assert result is None, "Lane must return None after unrecoverable failure"

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert error_records, "Expected at least one ERROR log record from lane failure"

    error_msg = error_records[0].getMessage()
    # R5.1: log must identify the adapter lane
    assert "telegram" in error_msg, f"Adapter key missing from error log: {error_msg!r}"
    # R5.1: log must identify the session
    assert session.session_id[:8] in error_msg, f"Session ID missing from error log: {error_msg!r}"
