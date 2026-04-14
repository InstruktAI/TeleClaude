"""Shared formatting and classification for TeleClaude conversation bridge messages."""

from __future__ import annotations

from teleclaude.constants import format_system_message

_LINKED_OUTPUT_LABEL_PREFIX = 'Linked output from "'
_HUMAN_IN_THE_LOOP_LABEL_PREFIX = 'Human in the Loop from "'
_DIRECT_CONVERSATION_LABEL = "Direct Conversation"


def is_conversation_bridge_message(text: str) -> bool:
    """Return True when text is a TeleClaude conversation bridge message."""
    stripped = text.lstrip()
    if not stripped.startswith("[TeleClaude "):
        return False
    return (
        stripped.startswith(f"[TeleClaude {_LINKED_OUTPUT_LABEL_PREFIX}")
        or stripped.startswith(f"[TeleClaude {_HUMAN_IN_THE_LOOP_LABEL_PREFIX}")
        or stripped.startswith(f"[TeleClaude {_DIRECT_CONVERSATION_LABEL}]")
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
