"""Shared formatting and classification for TeleClaude conversation bridge messages."""

from __future__ import annotations

from datetime import datetime

from teleclaude.constants import format_system_message

_LINKED_OUTPUT_LABEL_PREFIX = 'Linked output from "'
_HUMAN_IN_THE_LOOP_LABEL_PREFIX = 'Human in the Loop from "'
_DIRECT_CONVERSATION_LABEL = "Direct Conversation"
_BUNDLED_LABEL_PREFIX = 'Conversation update from "'


def is_conversation_bridge_message(text: str) -> bool:
    """Return True when text is a TeleClaude conversation bridge message."""
    stripped = text.lstrip()
    if not stripped.startswith("[TeleClaude "):
        return False
    return (
        stripped.startswith(f"[TeleClaude {_LINKED_OUTPUT_LABEL_PREFIX}")
        or stripped.startswith(f"[TeleClaude {_HUMAN_IN_THE_LOOP_LABEL_PREFIX}")
        or stripped.startswith(f"[TeleClaude {_DIRECT_CONVERSATION_LABEL}]")
        or stripped.startswith(f"[TeleClaude {_BUNDLED_LABEL_PREFIX}")
    )


def format_linked_output_message(
    *,
    sender_label: str,
    sender_session_id: str,
    sender_computer: str,
    content: str,
) -> str:
    """Format mirrored assistant output for a peer session."""
    return format_system_message(
        f'{_LINKED_OUTPUT_LABEL_PREFIX}{sender_label}" ({sender_session_id}) on {sender_computer}',
        content,
    )


def format_human_in_the_loop_message(
    *,
    sender_label: str,
    sender_session_id: str,
    sender_computer: str,
    content: str,
) -> str:
    """Format mirrored plain user input for a peer session."""
    return format_system_message(
        f'{_HUMAN_IN_THE_LOOP_LABEL_PREFIX}{sender_label}" ({sender_session_id}) on {sender_computer}',
        content,
    )


def format_bundled_conversation_message(
    *,
    sender_label: str,
    sender_session_id: str,
    sender_computer: str,
    segments: list[tuple[str, datetime | None, str]],
) -> str:
    """Format multiple role-tagged turns into ONE system-framed body.

    The outer header is a single ``[TeleClaude Conversation update from "..."]``
    so the receiver's ``is_internal_user_text`` filter classifies the whole
    entry as system-injected. Inside the body each turn carries an inline
    marker so the receiver can reconstruct the temporal sequence:

        --- Human in the Loop @ <iso8601> ---
        <user content>

        --- Linked output @ <iso8601> ---
        <assistant content>

    ``segments`` is an ordered list of ``(role, timestamp, text)`` where
    ``role`` is ``"user"`` or ``"assistant"`` and ``timestamp`` may be None
    when the source transcript has none. Empty input yields an empty string;
    callers must skip delivery when no segments exist.
    """
    if not segments:
        return ""
    sections: list[str] = []
    for role, ts, text in segments:
        marker_label = "Human in the Loop" if role == "user" else "Linked output"
        ts_label = ts.isoformat() if isinstance(ts, datetime) else "unknown"
        sections.append(f"--- {marker_label} @ {ts_label} ---\n{text.strip()}")
    body = "\n\n".join(sections)
    return format_system_message(
        f'{_BUNDLED_LABEL_PREFIX}{sender_label}" ({sender_session_id}) on {sender_computer}',
        body,
    )
