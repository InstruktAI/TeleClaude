"""WhatsApp Cloud API adapter."""

from __future__ import annotations

import mimetypes
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.models import ChannelMetadata, MessageMetadata

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from teleclaude.core.models import PeerInfo, Session

logger = get_logger(__name__)


class WhatsAppAdapter(UiAdapter):
    """UI adapter for WhatsApp Business Cloud API."""

    ADAPTER_KEY = "whatsapp"
    max_message_size = 4096
    _CAPTION_MAX_CHARS = 1024

    def __init__(self, client: "Any") -> None:
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
            await self._http.aclose()
            self._http = None

    async def create_channel(self, session: "Session", title: str, metadata: ChannelMetadata) -> str:
        _ = (title, metadata)
        phone_number = session.get_metadata().get_ui().get_whatsapp().phone_number
        if phone_number:
            return phone_number
        return session.session_id

    async def update_channel_title(self, session: "Session", title: str) -> bool:
        _ = (session, title)
        return True

    async def close_channel(self, session: "Session") -> bool:
        session.get_metadata().get_ui().get_whatsapp().closed = True
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        return True

    async def reopen_channel(self, session: "Session") -> bool:
        session.get_metadata().get_ui().get_whatsapp().closed = False
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        return True

    async def delete_channel(self, session: "Session") -> bool:
        _ = session
        return True

    async def ensure_channel(self, session: "Session") -> "Session":
        if session.human_role != "customer":
            return session
        return session

    async def _get_output_message_id(self, session: "Session") -> str | None:
        fresh = await db.get_session(session.session_id)
        if fresh:
            return fresh.get_metadata().get_ui().get_whatsapp().output_message_id
        return session.get_metadata().get_ui().get_whatsapp().output_message_id

    async def _store_output_message_id(self, session: "Session", message_id: str) -> None:
        meta = session.get_metadata().get_ui().get_whatsapp()
        meta.output_message_id = message_id
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

    async def _clear_output_message_id(self, session: "Session") -> None:
        meta = session.get_metadata().get_ui().get_whatsapp()
        meta.output_message_id = None
        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

    async def _post_json(
        self,
        url: str,
        payload: dict[str, object],  # guard: loose-dict - WhatsApp API payloads are dynamic by message type.
    ) -> dict[str, object]:  # guard: loose-dict - WhatsApp API responses are unstructured JSON.
        if self._http is None:
            raise RuntimeError("WhatsApp adapter is not started")
        response = await self._http.post(url, json=payload, headers=self._auth_headers())
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

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
            ts = ts.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ts <= timedelta(hours=24)

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
        session: "Session",
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        _ = (metadata, multi_message)

        whatsapp_meta = session.get_metadata().get_ui().get_whatsapp()
        if not whatsapp_meta.phone_number:
            raise ValueError(f"Session {session.session_id} missing WhatsApp phone number")

        chunks = self._chunk_message(text, self.max_message_size)
        last_message_id = ""

        for chunk in chunks:
            if self._is_within_customer_window(whatsapp_meta.last_customer_message_at):
                last_message_id = await self._send_text_message(whatsapp_meta.phone_number, chunk)
            else:
                last_message_id = await self._send_template_message(whatsapp_meta.phone_number)
                break

        return last_message_id

    async def edit_message(
        self,
        session: "Session",
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        _ = (session, message_id, text, metadata)
        return False

    async def delete_message(self, session: "Session", message_id: str) -> bool:
        _ = (session, message_id)
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
        with open(file_path, "rb") as fh:
            response = await self._http.post(
                self._media_url,
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": (Path(file_path).name, fh, mime_type)},
                headers=self._auth_headers(),
            )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("id"):
            return str(payload["id"])
        raise RuntimeError("WhatsApp media upload response missing media id")

    async def send_file(
        self,
        session: "Session",
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        _ = metadata
        whatsapp_meta = session.get_metadata().get_ui().get_whatsapp()
        if not whatsapp_meta.phone_number:
            raise ValueError(f"Session {session.session_id} missing WhatsApp phone number")

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
            "to": whatsapp_meta.phone_number,
            "type": media_type,
            media_type: media_payload,
        }
        response = await self._post_json(self._messages_url, payload)
        return self._extract_message_id(response)

    async def discover_peers(self) -> list["PeerInfo"]:
        return []

    async def poll_output_stream(  # type: ignore[override,misc]
        self,
        session: "Session",
        timeout: float = 300.0,
    ) -> "AsyncIterator[str]":
        _ = (session, timeout)
        raise NotImplementedError("WhatsApp adapter does not support poll_output_stream")
        yield ""  # pragma: no cover

    def _convert_markdown_for_platform(self, text: str) -> str:
        converted = text
        converted = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", r"\1", converted)
        converted = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r"\1 (\2)", converted)
        converted = re.sub(r"(?m)^#{1,6}\s+", "", converted)
        converted = re.sub(r"\*\*(.+?)\*\*", r"*\1*", converted)
        converted = re.sub(r"~~(.+?)~~", r"~\1~", converted)
        converted = re.sub(r"`([^`\n]+)`", r"```\1```", converted)
        return converted

    def _fit_output_to_limit(self, tmux_output: str) -> str:
        converted = self._convert_markdown_for_platform(tmux_output)
        if len(converted) <= self.max_message_size:
            return converted
        suffix = "\n\n[message truncated]"
        reserve = max(self.max_message_size - len(suffix), 0)
        return f"{converted[:reserve]}{suffix}" if reserve > 0 else converted[: self.max_message_size]

    def _build_output_metadata(self, _session: "Session", _is_truncated: bool) -> MessageMetadata:
        return MessageMetadata(parse_mode=None)

    def format_output(self, tmux_output: str) -> str:
        return self._convert_markdown_for_platform(tmux_output)

    async def send_typing_indicator(self, session: "Session") -> None:
        whatsapp_meta = session.get_metadata().get_ui().get_whatsapp()
        if not whatsapp_meta.last_received_message_id:
            return

        payload: dict[str, object] = {  # guard: loose-dict - Read receipt payload mirrors provider API.
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": whatsapp_meta.last_received_message_id,
        }
        try:
            await self._post_json(self._messages_url, payload)
        except Exception:
            logger.debug("WhatsApp read receipt failed for session %s", session.session_id[:8], exc_info=True)

    def get_max_message_length(self) -> int:
        return self.max_message_size

    def get_ai_session_poll_interval(self) -> float:
        return 1.0
