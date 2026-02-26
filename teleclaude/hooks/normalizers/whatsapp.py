"""Normalizer for WhatsApp Cloud API webhook payloads."""

from __future__ import annotations

from datetime import datetime, timezone

from teleclaude.hooks.webhook_models import HookEvent


def _normalize_phone(raw_phone: object) -> str:
    if raw_phone is None:
        return ""
    return "".join(ch for ch in str(raw_phone) if ch.isdigit())


def _to_event_timestamp(raw_timestamp: object) -> str:
    if isinstance(raw_timestamp, str) and raw_timestamp.isdigit():
        unix_seconds = int(raw_timestamp)
        return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _message_type(message: dict[str, object]) -> str:  # guard: loose-dict - Raw webhook message JSON is dynamic.
    msg_type = str(message.get("type") or "unknown")
    if msg_type == "text":
        return "message.text"
    if msg_type == "image":
        return "message.image"
    if msg_type == "document":
        return "message.document"
    if msg_type == "video":
        return "message.video"
    if msg_type in {"voice", "audio"}:
        audio_payload = message.get("audio")
        mime_type = ""
        if isinstance(audio_payload, dict):
            mime_type = str(audio_payload.get("mime_type") or "")
        if "ogg" in mime_type or msg_type == "voice":
            return "message.voice"
        return "message.audio"
    return f"message.{msg_type}"


def normalize_whatsapp_webhook(
    payload: dict[str, object],  # guard: loose-dict - webhook payload is dynamic
    headers: dict[str, str],
) -> list[HookEvent]:
    """Normalize WhatsApp webhook payload into HookEvent list."""
    _ = headers

    events: list[HookEvent] = []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return events

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

            messages = value.get("messages")
            if isinstance(messages, list):
                for message in messages:
                    if not isinstance(message, dict):
                        continue

                    message_type = _message_type(message)
                    phone_number = _normalize_phone(message.get("from"))
                    message_id = str(message.get("id") or "")
                    timestamp = _to_event_timestamp(message.get("timestamp"))

                    properties: dict[str, str | int | float | bool | list[str] | None] = {
                        "phone_number": phone_number,
                        "message_id": message_id,
                    }

                    if message_type == "message.text":
                        text_payload = message.get("text")
                        if isinstance(text_payload, dict):
                            properties["text"] = str(text_payload.get("body") or "")

                    for media_key in ("audio", "image", "document", "video"):
                        media_payload = message.get(media_key)
                        if isinstance(media_payload, dict):
                            if media_payload.get("id") is not None:
                                properties["media_id"] = str(media_payload.get("id"))
                            if media_payload.get("mime_type") is not None:
                                properties["mime_type"] = str(media_payload.get("mime_type"))

                    events.append(
                        HookEvent(
                            source="whatsapp",
                            type=message_type,
                            timestamp=timestamp,
                            properties=properties,
                            payload=message,
                        )
                    )

    return events
