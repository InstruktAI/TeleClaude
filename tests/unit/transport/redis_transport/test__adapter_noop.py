"""Characterization tests for teleclaude.transport.redis_transport._adapter_noop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.transport.redis_transport._transport import RedisTransport


@pytest.fixture
def adapter_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def transport(adapter_client: MagicMock) -> RedisTransport:
    with patch("teleclaude.transport.redis_transport._connection.Redis"):
        t = RedisTransport(adapter_client)
        t.redis = AsyncMock()
        return t


@pytest.fixture
def session() -> MagicMock:
    s = MagicMock()
    s.session_id = "sess-001"
    redis_meta = MagicMock()
    s.get_metadata.return_value.get_transport.return_value.get_redis.return_value = redis_meta
    return s


class TestSendMessage:
    @pytest.mark.unit
    async def test_returns_empty_string(self, transport: RedisTransport, session: MagicMock) -> None:
        result = await transport.send_message(session, "hello")
        assert result == ""

    @pytest.mark.unit
    async def test_returns_empty_string_with_metadata(self, transport: RedisTransport, session: MagicMock) -> None:
        result = await transport.send_message(session, "hello", metadata=MagicMock())
        assert result == ""


class TestEditMessage:
    @pytest.mark.unit
    async def test_returns_true(self, transport: RedisTransport, session: MagicMock) -> None:
        result = await transport.edit_message(session, "msg-1", "new text")
        assert result is True


class TestDeleteMessage:
    @pytest.mark.unit
    async def test_returns_true(self, transport: RedisTransport, session: MagicMock) -> None:
        result = await transport.delete_message(session, "msg-1")
        assert result is True


class TestSendErrorFeedback:
    @pytest.mark.unit
    async def test_returns_none(self, transport: RedisTransport) -> None:
        result = await transport.send_error_feedback("session-id", "some error")
        assert result is None


class TestSendFile:
    @pytest.mark.unit
    async def test_returns_empty_string(self, transport: RedisTransport, session: MagicMock) -> None:
        result = await transport.send_file(session, "/tmp/file.txt")
        assert result == ""

    @pytest.mark.unit
    async def test_returns_empty_string_with_caption(self, transport: RedisTransport, session: MagicMock) -> None:
        result = await transport.send_file(session, "/tmp/file.txt", caption="cap")
        assert result == ""


class TestSendGeneralMessage:
    @pytest.mark.unit
    async def test_returns_empty_string(self, transport: RedisTransport) -> None:
        result = await transport.send_general_message("broadcast text")
        assert result == ""


class TestCreateChannel:
    @pytest.mark.unit
    async def test_returns_empty_string(self, transport: RedisTransport, session: MagicMock) -> None:
        channel_metadata = MagicMock()
        channel_metadata.target_computer = None
        with patch("teleclaude.transport.redis_transport._adapter_noop.db") as mock_db:
            mock_db.update_session = AsyncMock()
            result = await transport.create_channel(session, "title", channel_metadata)
        assert result == ""

    @pytest.mark.unit
    async def test_records_target_computer_when_set(self, transport: RedisTransport, session: MagicMock) -> None:
        channel_metadata = MagicMock()
        channel_metadata.target_computer = "remote-computer"
        redis_meta = MagicMock()
        session.get_metadata.return_value.get_transport.return_value.get_redis.return_value = redis_meta
        with patch("teleclaude.transport.redis_transport._adapter_noop.db") as mock_db:
            mock_db.update_session = AsyncMock()
            await transport.create_channel(session, "title", channel_metadata)
        assert redis_meta.target_computer == "remote-computer"


class TestUpdateChannelTitle:
    @pytest.mark.unit
    async def test_returns_true(self, transport: RedisTransport, session: MagicMock) -> None:
        result = await transport.update_channel_title(session, "new title")
        assert result is True


class TestCloseChannel:
    @pytest.mark.unit
    async def test_returns_true(self, transport: RedisTransport, session: MagicMock) -> None:
        result = await transport.close_channel(session)
        assert result is True


class TestReopenChannel:
    @pytest.mark.unit
    async def test_returns_true(self, transport: RedisTransport, session: MagicMock) -> None:
        result = await transport.reopen_channel(session)
        assert result is True


class TestDeleteChannel:
    @pytest.mark.unit
    async def test_returns_true(self, transport: RedisTransport, session: MagicMock) -> None:
        result = await transport.delete_channel(session)
        assert result is True
