"""Normalization helpers for agent hook payloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


def _coerce_str(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _find_str_in_value(value: Any, keys: Iterable[str]) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            found = _coerce_str(value.get(key))
            if found:
                return found
        for nested in value.values():
            found = _find_str_in_value(nested, keys)
            if found:
                return found
        return None

    if isinstance(value, list):
        for item in value:
            found = _find_str_in_value(item, keys)
            if found:
                return found
    return None


def _find_str(data: dict[str, object], keys: Iterable[str]) -> str | None:
    for key in keys:
        found = _coerce_str(data.get(key))
        if found:
            return found
    for value in data.values():
        found = _find_str_in_value(value, keys)
        if found:
            return found
    return None


def normalize_session_start_payload(data: dict[str, object]) -> tuple[str | None, str | None]:
    """Normalize SessionStart payload to include session_id and transcript_path."""
    session_id_keys = (
        "session_id",
        "sessionId",
        "native_session_id",
        "conversation_id",
        "conversationId",
        "id",
    )
    transcript_keys = (
        "transcript_path",
        "transcriptPath",
        "transcript_file",
        "transcriptFile",
        "log_file",
        "logFile",
        "log_path",
        "logPath",
        "transcript",
    )

    session_id = _find_str(data, session_id_keys)
    transcript_path = _find_str(data, transcript_keys)

    if transcript_path and not session_id:
        session_id = Path(transcript_path).stem

    if session_id:
        data["session_id"] = session_id
    if transcript_path:
        data["transcript_path"] = transcript_path

    return session_id, transcript_path


def normalize_notification_payload(data: dict[str, object]) -> None:
    """Ensure notification payload has original_message when possible."""
    if "original_message" in data:
        return
    message = _find_str(data, ("message", "notification_message", "text"))
    if message:
        data["original_message"] = message
