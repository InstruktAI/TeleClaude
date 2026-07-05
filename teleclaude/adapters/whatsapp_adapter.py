"""WhatsApp Cloud API adapter."""

from __future__ import annotations

import asyncio
import mimetypes
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.delivery import Destination
from teleclaude.core.models import ChannelMetadata, MessageMetadata, WhatsAppAdapterMetadata
from teleclaude.utils.markdown import (
    WA_MARKDOWN_INITIAL_STATE,
    continuation_prefix_for_wa_state,
    scan_wa_state,
    truncate_wa_with_consumed,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from teleclaude.core.models import PeerInfo, Session

logger = get_logger(__name__)


class WhatsAppAdapter(UiAdapter):
    """UI adapter for WhatsApp Business Cloud API."""

    ADAPTER_KEY = "whatsapp"
    OUTPUT_MESSAGE_ID_FIELD = "id"
    max_message_size = 4096
    _CAPTION_MAX_CHARS = 1024
    _MAX_429_RETRIES = 3
    _BASE_429_BACKOFF_SECONDS = 1.0

    # -------------------------------------------------------------------------
    # Markdown strategy — WhatsApp dialect (*bold*, _italic_, ~strike~, ```mono```)
    # -------------------------------------------------------------------------

    def _markdown_initial_state(self) -> object:
        return WA_MARKDOWN_INITIAL_STATE

    def _continuation_prefix_for_state(self, state: object) -> str:
        return continuation_prefix_for_wa_state(state)

    def _truncate_for_overflow(self, body_text: str, max_chars: int) -> tuple[str, int]:
        return truncate_wa_with_consumed(body_text, max_chars=max_chars, suffix="")

    def _scan_markdown_state(self, consumed: str, state: object) -> object:
        return scan_wa_state(consumed, initial_state=state)

    # -------------------------------------------------------------------------

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self._phone_number_id = config.whatsapp.phone_number_id
        self._access_token = config.whatsapp.access_token
        self._api_version = config.whatsapp.api_version
        self._template_name = config.whatsapp.template_name
        self._template_language = config.whatsapp.template_language
        self._http: httpx.AsyncClient | None = None

    @property
    def _messages_url(self) -> str:
        return f"https://graph.facebook.com/{self._api_version}/{self._phone_number_id}/messages"

    @property
    def _media_url(self) -> str:
        return f"https://graph.facebook.com/{self._api_version}/{self._phone_number_id}/media"

    def _auth_headers(self) -> dict[str, str]:
        if not self._access_token:
            raise ValueError("WHATSAPP_ACCESS_TOKEN is not configured")
        return {"Authorization": f"Bearer {self._access_token}"}

    async def start(self) -> None:
        if not self._phone_number_id or not self._access_token:
            raise ValueError("WhatsApp adapter requires phone_number_id and access_token")
        self._http = httpx.AsyncClient(timeout=15.0)

    async def stop(self) -> None:
        if self._http is not None:
            try:
                await self._http.aclose()
            except RuntimeError as exc:
                if str(exc) != "Event loop is closed":
                    raise
                logger.debug("WhatsApp HTTP client closed after event loop shutdown")
            self._http = None

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        _ = (title, metadata)
        phone_number = WhatsAppAdapterMetadata.from_dict(session.get_origin_section("whatsapp")).phone_number
        if phone_number:
            return phone_number
        return session.session_id

    async def update_channel_title(self, session: Session) -> bool:
        _ = session
        return True

    @staticmethod
    def _wa(session: Session) -> WhatsAppAdapterMetadata:
        """Read WhatsApp section from origin_metadata."""
        return WhatsAppAdapterMetadata.from_dict(session.get_origin_section("whatsapp"))

    async def close_channel(self, session: Session) -> bool:
        wa = self._wa(session)
        wa.closed = True
        await db.update_origin_metadata(session.session_id, "whatsapp", wa.to_dict())
        return True

    async def reopen_channel(self, session: Session) -> bool:
        wa = self._wa(session)
        wa.closed = False
        await db.update_origin_metadata(session.session_id, "whatsapp", wa.to_dict())
        return True

    async def delete_channel(self, session: Session) -> bool:
        _ = session
        return True

    async def ensure_channel(self, session: Session) -> Session:
        if session.human_role != "customer":
            return session
        return session

    async def _post_json(
        self,
        url: str,
        payload: dict[str, object],  # guard: loose-dict - WhatsApp API payloads are dynamic by message type.
    ) -> dict[str, object]:  # guard: loose-dict - WhatsApp API responses are unstructured JSON.
        if self._http is None:
            raise RuntimeError("WhatsApp adapter is not started")
        for attempt in range(self._MAX_429_RETRIES + 1):
            response = await self._http.post(url, json=payload, headers=self._auth_headers())
            if response.status_code != 429:
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {}

            if attempt >= self._MAX_429_RETRIES:
                response.raise_for_status()

            retry_after = self._parse_retry_after_seconds(response.headers.get("Retry-After"))
            backoff_seconds = retry_after or (self._BASE_429_BACKOFF_SECONDS * (2**attempt))
            logger.warning(
                "WhatsApp API rate-limited (429); retrying in %.2fs (attempt %d/%d)",
                backoff_seconds,
                attempt + 1,
                self._MAX_429_RETRIES,
            )
            await asyncio.sleep(backoff_seconds)
        raise RuntimeError("WhatsApp request retry loop exited unexpectedly")

    @staticmethod
    def _parse_retry_after_seconds(value: str | None) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _extract_message_id(data: dict[str, object]) -> str:  # guard: loose-dict - API response JSON payload.
        messages = data.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            msg_id = messages[0].get("id")
            if msg_id is not None:
                return str(msg_id)
        raise RuntimeError("WhatsApp response missing message id")

    @staticmethod
    def _chunk_message(text: str, max_len: int) -> list[str]:
        if len(text) <= max_len:
            return [text]

        chunks: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= max_len:
                chunks.append(remaining)
                break
            split_at = remaining.rfind(" ", 0, max_len + 1)
            if split_at <= 0:
                split_at = max_len
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()
        return chunks

    @staticmethod
    def _is_within_customer_window(last_customer_message_at: str | None) -> bool:
        if not last_customer_message_at:
            return True
        try:
            ts = datetime.fromisoformat(last_customer_message_at)
        except ValueError:
            return True
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return datetime.now(UTC) - ts <= timedelta(hours=24)

    async def _send_text_message(self, phone_number: str, text: str) -> str:
        payload: dict[str, object] = {  # guard: loose-dict - Outbound WhatsApp request payload.
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {"body": text},
        }
        response = await self._post_json(self._messages_url, payload)
        return self._extract_message_id(response)

    async def _send_template_message(self, phone_number: str) -> str:
        if not self._template_name:
            raise RuntimeError("No WhatsApp template configured for out-of-window message")
        payload: dict[str, object] = {  # guard: loose-dict - Template payload shape is provider-defined.
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "template",
            "template": {
                "name": self._template_name,
                "language": {"code": self._template_language},
            },
        }
        response = await self._post_json(self._messages_url, payload)
        return self._extract_message_id(response)

    async def send_message(
        self,
        destination: Destination,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        _ = (metadata, multi_message)

        if not destination.phone_number:
            raise ValueError(f"Session {destination.session_id} missing WhatsApp phone number")

        chunks = self._chunk_message(text, self.max_message_size)
        last_message_id = ""

        for chunk in chunks:
            if self._is_within_customer_window(destination.last_customer_message_at):
                last_message_id = await self._send_text_message(destination.phone_number, chunk)
            else:
                last_message_id = await self._send_template_message(destination.phone_number)
                break

        return last_message_id

    async def edit_message(
        self,
        destination: Destination,
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        _ = (destination, message_id, text, metadata)
        return False

    async def delete_message(self, destination: Destination, message_id: str) -> bool:
        _ = (destination, message_id)
        return False

    @staticmethod
    def _resolve_media_type(mime_type: str) -> str:
        if mime_type.startswith("image/"):
            return "image"
        if mime_type.startswith("audio/"):
            return "audio"
        return "document"

    async def _upload_media(self, file_path: str, mime_type: str) -> str:
        if self._http is None:
            raise RuntimeError("WhatsApp adapter is not started")
        for attempt in range(self._MAX_429_RETRIES + 1):
            with open(file_path, "rb") as fh:
                response = await self._http.post(
                    self._media_url,
                    data={"messaging_product": "whatsapp", "type": mime_type},
                    files={"file": (Path(file_path).name, fh, mime_type)},
                    headers=self._auth_headers(),
                )
            if response.status_code != 429:
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and payload.get("id"):
                    return str(payload["id"])
                raise RuntimeError("WhatsApp media upload response missing media id")

            if attempt >= self._MAX_429_RETRIES:
                response.raise_for_status()

            retry_after = self._parse_retry_after_seconds(response.headers.get("Retry-After"))
            backoff_seconds = retry_after or (self._BASE_429_BACKOFF_SECONDS * (2**attempt))
            logger.warning(
                "WhatsApp media upload rate-limited (429); retrying in %.2fs (attempt %d/%d)",
                backoff_seconds,
                attempt + 1,
                self._MAX_429_RETRIES,
            )
            await asyncio.sleep(backoff_seconds)
        raise RuntimeError("WhatsApp media upload retry loop exited unexpectedly")

    async def send_file(
        self,
        destination: Destination,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        _ = metadata
        if not destination.phone_number:
            raise ValueError(f"Session {destination.session_id} missing WhatsApp phone number")

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        media_type = self._resolve_media_type(mime_type)
        media_id = await self._upload_media(str(path), mime_type)

        media_payload: dict[str, object] = {"id": media_id}  # guard: loose-dict - Media body is type-specific.
        if caption and media_type in {"image", "document"}:
            media_payload["caption"] = caption[: self._CAPTION_MAX_CHARS]

        payload: dict[str, object] = {  # guard: loose-dict - Media send payload is dynamic by media type.
            "messaging_product": "whatsapp",
            "to": destination.phone_number,
            "type": media_type,
            media_type: media_payload,
        }
        response = await self._post_json(self._messages_url, payload)
        return self._extract_message_id(response)

    async def discover_peers(self) -> list[PeerInfo]:
        return []

    async def poll_output_stream(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        session: Session,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        _ = (session, timeout)
        yield ""  # pragma: no cover - make this an async generator
        raise NotImplementedError("WhatsApp adapter does not support poll_output_stream")

    def _convert_markdown_for_platform(self, text: str) -> str:
        converted = text
        converted = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", r"\1", converted)
        converted = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r"\1 (\2)", converted)
        converted = re.sub(r"(?m)^#{1,6}\s+", "", converted)
        converted = re.sub(r"\*\*(.+?)\*\*", r"*\1*", converted)
        converted = re.sub(r"~~(.+?)~~", r"~\1~", converted)
        converted = re.sub(r"`([^`\n]+)`", r"```\1```", converted)
        return converted

    def _build_output_metadata(self, _session: Session, _is_truncated: bool) -> MessageMetadata:
        return MessageMetadata(parse_mode=None)

    def format_output(self, tmux_output: str) -> str:
        """Format output with WhatsApp markdown conventions."""
        return self._convert_markdown_for_platform(tmux_output)

    async def send_typing_indicator(self, session: Session) -> None:
        whatsapp_meta = WhatsAppAdapterMetadata.from_dict(session.get_origin_section("whatsapp"))
        if not whatsapp_meta.last_received_message_id:
            return

        payload: dict[str, object] = {  # guard: loose-dict - Read receipt payload mirrors provider API.
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": whatsapp_meta.last_received_message_id,
        }
        try:
            await self._post_json(self._messages_url, payload)
        except (httpx.HTTPError, RuntimeError):
            logger.debug("WhatsApp read receipt failed for session %s", session.session_id, exc_info=True)

    def get_max_message_length(self) -> int:
        return self.max_message_size

    def get_ai_session_poll_interval(self) -> float:
        return 1.0
