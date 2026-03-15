"""Characterization tests for teleclaude.adapters.whatsapp_adapter."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from teleclaude.adapters.whatsapp_adapter import WhatsAppAdapter
from teleclaude.core.models import ChannelMetadata, Session

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session(phone_number: str = "+1234567890", **kwargs: object) -> Session:
    session = Session(
        session_id="wa-sess-1",
        computer_name="local",
        tmux_session_name="test",
        title="Test",
        **kwargs,
    )
    meta = session.get_metadata().get_ui().get_whatsapp()
    meta.phone_number = phone_number
    return session


@pytest.fixture
def adapter() -> Iterator[WhatsAppAdapter]:
    with (
        patch("teleclaude.adapters.whatsapp_adapter.config") as mock_cfg,
        patch("teleclaude.adapters.ui_adapter.event_bus"),
    ):
        mock_cfg.whatsapp.phone_number_id = "12345"
        mock_cfg.whatsapp.access_token = "token-abc"
        mock_cfg.whatsapp.api_version = "v20.0"
        mock_cfg.whatsapp.template_name = "hello_world"
        mock_cfg.whatsapp.template_language = "en"
        yield WhatsAppAdapter(MagicMock())


# ---------------------------------------------------------------------------
# Class-level attributes
# ---------------------------------------------------------------------------


class TestWhatsAppAdapterClassAttributes:
    @pytest.mark.unit
    def test_adapter_key_is_whatsapp(self) -> None:
        assert WhatsAppAdapter.ADAPTER_KEY == "whatsapp"

    @pytest.mark.unit
    def test_max_message_size_is_4096(self) -> None:
        assert WhatsAppAdapter.max_message_size == 4096

    @pytest.mark.unit
    def test_threaded_output_is_false(self) -> None:
        assert WhatsAppAdapter.THREADED_OUTPUT is False


# ---------------------------------------------------------------------------
# URL properties
# ---------------------------------------------------------------------------


class TestUrlProperties:
    @pytest.mark.unit
    def test_messages_url_contains_phone_number_id(self, adapter: WhatsAppAdapter) -> None:
        url = adapter._messages_url
        assert "12345" in url
        assert "messages" in url

    @pytest.mark.unit
    def test_media_url_contains_phone_number_id(self, adapter: WhatsAppAdapter) -> None:
        url = adapter._media_url
        assert "12345" in url
        assert "media" in url

    @pytest.mark.unit
    def test_messages_url_contains_api_version(self, adapter: WhatsAppAdapter) -> None:
        url = adapter._messages_url
        assert "v20.0" in url


# ---------------------------------------------------------------------------
# _auth_headers
# ---------------------------------------------------------------------------


class TestAuthHeaders:
    @pytest.mark.unit
    def test_returns_bearer_token(self, adapter: WhatsAppAdapter) -> None:
        headers = adapter._auth_headers()
        assert headers["Authorization"] == "Bearer token-abc"

    @pytest.mark.unit
    def test_missing_token_raises(self, adapter: WhatsAppAdapter) -> None:
        adapter._access_token = None
        with pytest.raises(ValueError, match="WHATSAPP_ACCESS_TOKEN"):
            adapter._auth_headers()


# ---------------------------------------------------------------------------
# _parse_retry_after_seconds
# ---------------------------------------------------------------------------


class TestParseRetryAfterSeconds:
    @pytest.mark.unit
    def test_none_input_returns_none(self):
        assert WhatsAppAdapter._parse_retry_after_seconds(None) is None

    @pytest.mark.unit
    def test_positive_number_string_returns_float(self):
        assert WhatsAppAdapter._parse_retry_after_seconds("2.5") == pytest.approx(2.5)

    @pytest.mark.unit
    def test_zero_returns_none(self):
        assert WhatsAppAdapter._parse_retry_after_seconds("0") is None

    @pytest.mark.unit
    def test_negative_returns_none(self):
        assert WhatsAppAdapter._parse_retry_after_seconds("-1") is None

    @pytest.mark.unit
    def test_non_numeric_returns_none(self):
        assert WhatsAppAdapter._parse_retry_after_seconds("abc") is None


# ---------------------------------------------------------------------------
# _extract_message_id
# ---------------------------------------------------------------------------


class TestExtractMessageId:
    @pytest.mark.unit
    def test_extracts_id_from_valid_response(self):
        data = {"messages": [{"id": "wamid.abc123"}]}
        assert WhatsAppAdapter._extract_message_id(data) == "wamid.abc123"

    @pytest.mark.unit
    def test_missing_messages_key_raises(self):
        with pytest.raises(RuntimeError, match="missing message id"):
            WhatsAppAdapter._extract_message_id({})

    @pytest.mark.unit
    def test_empty_messages_list_raises(self):
        with pytest.raises(RuntimeError, match="missing message id"):
            WhatsAppAdapter._extract_message_id({"messages": []})

    @pytest.mark.unit
    def test_non_dict_first_message_raises(self):
        with pytest.raises(RuntimeError):
            WhatsAppAdapter._extract_message_id({"messages": ["invalid"]})


# ---------------------------------------------------------------------------
# _chunk_message
# ---------------------------------------------------------------------------


class TestChunkMessage:
    @pytest.mark.unit
    def test_short_text_returns_single_chunk(self):
        chunks = WhatsAppAdapter._chunk_message("hello", 100)
        assert chunks == ["hello"]

    @pytest.mark.unit
    def test_long_text_splits_into_multiple_chunks(self):
        text = "a" * 150
        chunks = WhatsAppAdapter._chunk_message(text, 100)
        assert len(chunks) > 1
        assert all(len(c) <= 100 for c in chunks)

    @pytest.mark.unit
    def test_text_at_exact_limit_is_single_chunk(self):
        text = "x" * 100
        chunks = WhatsAppAdapter._chunk_message(text, 100)
        assert chunks == [text]

    @pytest.mark.unit
    def test_splits_on_word_boundary_when_possible(self):
        text = "hello " + "w" * 95 + " world"
        chunks = WhatsAppAdapter._chunk_message(text, 100)
        # First chunk should end at a space boundary, not mid-word
        assert not chunks[0].endswith("w")

    @pytest.mark.unit
    def test_chunks_preserve_content(self):
        text = "a b " * 30  # 120 chars
        chunks = WhatsAppAdapter._chunk_message(text, 50)
        rejoined = "".join(chunks)
        assert rejoined.replace(" ", "") == text.replace(" ", "")


# ---------------------------------------------------------------------------
# _is_within_customer_window
# ---------------------------------------------------------------------------


class TestIsWithinCustomerWindow:
    @pytest.mark.unit
    def test_none_timestamp_returns_true(self):
        assert WhatsAppAdapter._is_within_customer_window(None) is True

    @pytest.mark.unit
    def test_recent_timestamp_within_window(self):
        recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        assert WhatsAppAdapter._is_within_customer_window(recent) is True

    @pytest.mark.unit
    def test_old_timestamp_outside_window(self):
        old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        assert WhatsAppAdapter._is_within_customer_window(old) is False

    @pytest.mark.unit
    def test_invalid_timestamp_treated_as_within_window(self):
        assert WhatsAppAdapter._is_within_customer_window("not-a-date") is True


# ---------------------------------------------------------------------------
# _resolve_media_type
# ---------------------------------------------------------------------------


class TestResolveMediaType:
    @pytest.mark.unit
    def test_image_mime_returns_image(self):
        assert WhatsAppAdapter._resolve_media_type("image/png") == "image"

    @pytest.mark.unit
    def test_audio_mime_returns_audio(self):
        assert WhatsAppAdapter._resolve_media_type("audio/ogg") == "audio"

    @pytest.mark.unit
    def test_unknown_mime_returns_document(self):
        assert WhatsAppAdapter._resolve_media_type("application/pdf") == "document"


# ---------------------------------------------------------------------------
# edit_message (always returns False for WhatsApp)
# ---------------------------------------------------------------------------


class TestEditMessage:
    @pytest.mark.unit
    async def test_edit_message_always_returns_false(self, adapter: WhatsAppAdapter) -> None:
        session = _make_session()
        result = await adapter.edit_message(session, "msg-1", "new text", metadata=None)
        assert result is False


# ---------------------------------------------------------------------------
# delete_message (always returns False for WhatsApp)
# ---------------------------------------------------------------------------


class TestDeleteMessage:
    @pytest.mark.unit
    async def test_delete_message_always_returns_false(self, adapter: WhatsAppAdapter) -> None:
        session = _make_session()
        result = await adapter.delete_message(session, "msg-1")
        assert result is False


# ---------------------------------------------------------------------------
# update_channel_title (no-op, returns True)
# ---------------------------------------------------------------------------


class TestUpdateChannelTitle:
    @pytest.mark.unit
    async def test_returns_true_without_action(self, adapter: WhatsAppAdapter) -> None:
        session = _make_session()
        result = await adapter.update_channel_title(session, "new title")
        assert result is True


# ---------------------------------------------------------------------------
# create_channel
# ---------------------------------------------------------------------------


class TestCreateChannel:
    @pytest.mark.unit
    async def test_returns_phone_number_when_set(self, adapter: WhatsAppAdapter) -> None:
        session = _make_session(phone_number="+9876543210")
        result = await adapter.create_channel(session, "title", ChannelMetadata())
        assert result == "+9876543210"

    @pytest.mark.unit
    async def test_returns_session_id_when_no_phone(self, adapter: WhatsAppAdapter) -> None:
        session = _make_session(phone_number="")
        result = await adapter.create_channel(session, "title", ChannelMetadata())
        assert result == session.session_id


# ---------------------------------------------------------------------------
# lifecycle helpers
# ---------------------------------------------------------------------------


class TestLifecycleHelpers:
    @pytest.mark.unit
    def test_get_max_message_length_returns_4096(self, adapter: WhatsAppAdapter) -> None:
        assert adapter.get_max_message_length() == 4096

    @pytest.mark.unit
    def test_get_ai_session_poll_interval_returns_one(self, adapter: WhatsAppAdapter) -> None:
        assert adapter.get_ai_session_poll_interval() == 1.0

    @pytest.mark.unit
    async def test_close_channel_marks_closed(self, adapter: WhatsAppAdapter) -> None:
        session = _make_session()
        with patch("teleclaude.adapters.whatsapp_adapter.db") as mock_db:
            mock_db.update_session = AsyncMock()
            result = await adapter.close_channel(session)
        assert result is True
        assert session.get_metadata().get_ui().get_whatsapp().closed is True

    @pytest.mark.unit
    async def test_reopen_channel_marks_not_closed(self, adapter: WhatsAppAdapter) -> None:
        session = _make_session()
        session.get_metadata().get_ui().get_whatsapp().closed = True
        with patch("teleclaude.adapters.whatsapp_adapter.db") as mock_db:
            mock_db.update_session = AsyncMock()
            result = await adapter.reopen_channel(session)
        assert result is True
        assert session.get_metadata().get_ui().get_whatsapp().closed is False


# ---------------------------------------------------------------------------
# Public boundary: start / stop
# ---------------------------------------------------------------------------


class TestStart:
    @pytest.mark.unit
    async def test_start_raises_when_missing_credentials(self, adapter: WhatsAppAdapter) -> None:
        adapter._phone_number_id = None
        with pytest.raises(ValueError, match="phone_number_id"):
            await adapter.start()

    @pytest.mark.unit
    async def test_start_creates_http_client(self, adapter: WhatsAppAdapter) -> None:
        with patch("teleclaude.adapters.whatsapp_adapter.httpx.AsyncClient") as client_cls:
            await adapter.start()

        client_cls.assert_called_once_with(timeout=15.0)
        assert adapter._http is client_cls.return_value


class TestStop:
    @pytest.mark.unit
    async def test_stop_closes_http_client(self, adapter: WhatsAppAdapter) -> None:
        adapter._http = httpx.AsyncClient()
        with patch.object(adapter._http, "aclose", AsyncMock()) as aclose:
            await adapter.stop()

        aclose.assert_awaited_once()
        assert adapter._http is None

    @pytest.mark.unit
    async def test_stop_is_safe_when_not_started(self, adapter: WhatsAppAdapter) -> None:
        adapter._http = None
        await adapter.stop()  # should not raise


# ---------------------------------------------------------------------------
# Public boundary: send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    @pytest.mark.unit
    async def test_raises_when_no_phone_number(self, adapter: WhatsAppAdapter) -> None:
        session = _make_session(phone_number="")
        with pytest.raises(ValueError, match="phone number"):
            await adapter.send_message(session, "hello")

    @pytest.mark.unit
    async def test_chunks_text_within_customer_window(self, adapter: WhatsAppAdapter) -> None:
        session = _make_session()
        adapter.max_message_size = 4
        with (
            patch.object(adapter, "_send_text_message", AsyncMock(side_effect=["wamid.1", "wamid.2"])) as send_text,
            patch.object(adapter, "_send_template_message", AsyncMock()) as send_template,
            patch(
                "teleclaude.adapters.whatsapp_adapter.WhatsAppAdapter._is_within_customer_window",
                return_value=True,
            ),
        ):
            result = await adapter.send_message(session, "abcdefgh")

        assert result == "wamid.2"
        assert [call.args[1] for call in send_text.await_args_list] == ["abcd", "efgh"]
        send_template.assert_not_awaited()

    @pytest.mark.unit
    async def test_uses_template_outside_customer_window(self, adapter: WhatsAppAdapter) -> None:
        session = _make_session()
        with (
            patch.object(adapter, "_send_text_message", AsyncMock()) as send_text,
            patch.object(adapter, "_send_template_message", AsyncMock(return_value="wamid.2")) as send_template,
            patch(
                "teleclaude.adapters.whatsapp_adapter.WhatsAppAdapter._is_within_customer_window",
                return_value=False,
            ),
        ):
            result = await adapter.send_message(session, "hello")

        assert result == "wamid.2"
        send_text.assert_not_awaited()
        send_template.assert_awaited_once_with("+1234567890")


# ---------------------------------------------------------------------------
# Public boundary: send_file
# ---------------------------------------------------------------------------


class TestSendFile:
    @pytest.mark.unit
    async def test_raises_when_no_phone_number(self, adapter: WhatsAppAdapter) -> None:
        session = _make_session(phone_number="")
        with pytest.raises(ValueError, match="phone number"):
            await adapter.send_file(session, "/tmp/any.txt")

    @pytest.mark.unit
    async def test_raises_for_missing_file(self, adapter: WhatsAppAdapter, tmp_path: Path) -> None:
        session = _make_session()
        missing_file = tmp_path / "missing.txt"
        with pytest.raises(FileNotFoundError):
            await adapter.send_file(session, str(missing_file))

    @pytest.mark.unit
    async def test_posts_media_payload_and_returns_message_id(self, adapter: WhatsAppAdapter, tmp_path: Path) -> None:
        session = _make_session()
        file_path = tmp_path / "image.png"
        file_path.write_bytes(b"image-bytes")
        with (
            patch.object(adapter, "_upload_media", AsyncMock(return_value="media-1")) as upload_media,
            patch.object(
                adapter,
                "_post_json",
                AsyncMock(return_value={"messages": [{"id": "wamid.file"}]}),
            ) as post_json,
        ):
            result = await adapter.send_file(session, str(file_path), caption="caption")

        assert result == "wamid.file"
        upload_media.assert_awaited_once()
        payload = post_json.await_args.args[1]
        assert isinstance(payload, dict)
        assert payload["type"] == "image"
        media_payload = payload["image"]
        assert isinstance(media_payload, dict)
        assert media_payload["id"] == "media-1"
        assert "caption" in media_payload
