"""Normalizer for WhatsApp Cloud API webhook payloads."""

from __future__ import annotations

from datetime import UTC, datetime

from teleclaude.hooks.webhook_models import HookEvent


def _normalize_phone(raw_phone: object) -> str:
    if raw_phone is None:
        return ""
    return "".join(ch for ch in str(raw_phone) if ch.isdigit())


def _to_event_timestamp(raw_timestamp: object) -> str:
    if isinstance(raw_timestamp, str) and raw_timestamp.isdigit():
        unix_seconds = int(raw_timestamp)
        return datetime.fromtimestamp(unix_seconds, tz=UTC).isoformat()
    return datetime.now(UTC).isoformat()


def _message_type(
    message: dict[str, object],  # guard: loose-dict - Raw webhook message JSON is dynamic.
) -> str:
    msg_type = str(message.get("type") or "unknown")
    mapped_type = {
        "text": "message.text",
        "image": "message.image",
        "document": "message.document",
        "video": "message.video",
    }.get(msg_type)
    if mapped_type is not None:
        return mapped_type
    if msg_type in {"voice", "audio"}:
        audio_payload = message.get("audio")
        mime_type = ""
        if isinstance(audio_payload, dict):
            mime_type = str(audio_payload.get("mime_type") or "")
        return "message.voice" if "ogg" in mime_type or msg_type == "voice" else "message.audio"
    return f"message.{msg_type}"


def _iter_whatsapp_messages(payload: dict[str, object]) -> list[dict[str, object]]:
    """Yield message dictionaries found in a WhatsApp webhook payload."""
    messages: list[dict[str, object]] = []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return messages
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            nested_messages = value.get("messages")
            if not isinstance(nested_messages, list):
                continue
            for message in nested_messages:
                if isinstance(message, dict):
                    messages.append(message)
    return messages


def _extract_media_properties(message: dict[str, object]) -> dict[str, str]:
    """Extract media identifiers from a WhatsApp message payload."""
    properties: dict[str, str] = {}
    for media_key in ("audio", "image", "document", "video"):
        media_payload = message.get(media_key)
        if not isinstance(media_payload, dict):
            continue
        media_id = media_payload.get("id")
        mime_type = media_payload.get("mime_type")
        if media_id is not None:
            properties["media_id"] = str(media_id)
        if mime_type is not None:
            properties["mime_type"] = str(mime_type)
    return properties


def _build_message_properties(
    message: dict[str, object],
    message_type: str,
) -> dict[str, str | int | float | bool | list[str] | None]:
    """Build normalized HookEvent properties for a WhatsApp message."""
    properties: dict[str, str | int | float | bool | list[str] | None] = {
        "phone_number": _normalize_phone(message.get("from")),
        "message_id": str(message.get("id") or ""),
    }
    if message_type == "message.text":
        text_payload = message.get("text")
        if isinstance(text_payload, dict):
            properties["text"] = str(text_payload.get("body") or "")
    properties.update(_extract_media_properties(message))
    return properties


def normalize_whatsapp_webhook(
    payload: dict[str, object],  # guard: loose-dict - webhook payload is dynamic
    headers: dict[str, str],
) -> list[HookEvent]:
    """Normalize WhatsApp webhook payload into HookEvent list."""
    _ = headers

    return [
        HookEvent(
            source="whatsapp",
            type=message_type,
            timestamp=_to_event_timestamp(message.get("timestamp")),
            properties=_build_message_properties(message, message_type),
            payload=message,
        )
        for message in _iter_whatsapp_messages(payload)
        for message_type in [_message_type(message)]
    ]
