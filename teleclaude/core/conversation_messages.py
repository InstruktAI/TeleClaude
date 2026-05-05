"""Shared formatting and classification for TeleClaude conversation bridge messages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from teleclaude.constants import format_system_message

_LINKED_OUTPUT_LABEL_PREFIX = 'Linked output from "'
_HUMAN_IN_THE_LOOP_LABEL_PREFIX = 'Human in the Loop from "'
_DIRECT_CONVERSATION_LABEL = "Direct Conversation"
_BUNDLED_LABEL_PREFIX = 'Conversation update from "'
_LINKED_OUTPUT_HEADER_PATTERN = re.compile(r'(?P<label>.+)" \((?P<session_id>[^)]+)\) on (?P<computer>.+)')
_ACK_ONLY_PAYLOADS = {
    "ack",
    "copy",
    "done",
    "got it",
    "gotcha",
    "k",
    "kk",
    "noted",
    "ok",
    "okay",
    "on it",
    "roger",
    "sounds good",
    "thanks",
    "thank you",
    "understood",
    "will do",
}
_IDLE_OR_STANDBY_PATTERN = re.compile(
    r"\b("
    r"idle|"
    r"standing by|"
    r"awaiting|"
    r"waiting for|"
    r"returning to work|"
    r"back to work|"
    r"continuing(?: work)?|"
    r"no (?:further )?action needed|"
    r"no response needed|"
    r"nothing (?:else |further )?to add|"
    r"no update|"
    r"no changes"
    r")\b"
)
_STATUS_NARRATION_PATTERN = re.compile(
    r"^(?:i(?: am|'m)? )?"
    r"(?:looking into|checking|reviewing|investigating|working on|handling|digging into)\b"
)
_MEANINGFUL_HINTS = (
    "?",
    "`",
    "/",
    ".py",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    "::",
    "->",
    "error",
    "failed",
    "failure",
    "fix",
    "fixed",
    "bug",
    "regression",
    "blocker",
    "root cause",
    "because",
    "found",
    "missing",
    "need",
    "should",
    "must",
    "please",
    "can you",
    "could you",
    "review",
    "confirm",
    "decide",
    "choose",
    "cursor",
    "retry",
)


@dataclass(frozen=True)
class LinkedOutputMessage:
    """Parsed linked-output wrapper and payload."""

    sender_label: str
    sender_session_id: str
    sender_computer: str
    payload: str


@dataclass(frozen=True)
class LinkedDirectOutputClassification:
    """Emit decision for linked direct-conversation assistant output."""

    emit: bool
    reason: str
    role: str
    preview: str
    payload: str


def _preview(text: str, *, limit: int = 160) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _split_bridge_message(text: str) -> tuple[str, str] | None:
    stripped = text.lstrip()
    if not stripped.startswith("[TeleClaude "):
        return None
    header_end = stripped.find("]")
    if header_end < 0:
        return None
    label = stripped[len("[TeleClaude ") : header_end]
    payload = stripped[header_end + 1 :].strip()
    return label, payload


def parse_linked_output_message(text: str) -> LinkedOutputMessage | None:
    """Parse a linked-output wrapper into sender metadata and payload."""
    parts = _split_bridge_message(text)
    if parts is None:
        return None
    label, payload = parts
    if not label.startswith(_LINKED_OUTPUT_LABEL_PREFIX):
        return None
    header = label[len(_LINKED_OUTPUT_LABEL_PREFIX) :]
    match = _LINKED_OUTPUT_HEADER_PATTERN.fullmatch(header)
    if match is None:
        return None
    return LinkedOutputMessage(
        sender_label=match.group("label"),
        sender_session_id=match.group("session_id"),
        sender_computer=match.group("computer"),
        payload=payload,
    )


def classify_linked_direct_conversation_output(text: str) -> LinkedDirectOutputClassification:
    """Classify whether linked assistant output should be emitted in direct conversation.

    The wrapped payload is authoritative; wrapper text never makes output actionable.
    """
    parsed = parse_linked_output_message(text)
    if parsed is None:
        return LinkedDirectOutputClassification(
            emit=False,
            reason="not_linked_output",
            role="assistant",
            preview=_preview(text),
            payload="",
        )

    payload = parsed.payload.strip()
    preview = _preview(payload or text)
    if not payload:
        return LinkedDirectOutputClassification(
            emit=False,
            reason="empty_payload",
            role="assistant",
            preview=preview,
            payload=payload,
        )

    normalized = " ".join(payload.lower().split())
    word_count = len(re.findall(r"[a-z0-9_./:-]+", normalized))
    if normalized.rstrip(".!?") in _ACK_ONLY_PAYLOADS and word_count <= 6:
        return LinkedDirectOutputClassification(
            emit=False,
            reason="acknowledgment_only",
            role="assistant",
            preview=preview,
            payload=payload,
        )
    if word_count <= 12 and _IDLE_OR_STANDBY_PATTERN.search(normalized):
        return LinkedDirectOutputClassification(
            emit=False,
            reason="idle_or_noop",
            role="assistant",
            preview=preview,
            payload=payload,
        )
    if word_count <= 10 and _STATUS_NARRATION_PATTERN.search(normalized):
        return LinkedDirectOutputClassification(
            emit=False,
            reason="status_narration_only",
            role="assistant",
            preview=preview,
            payload=payload,
        )
    if any(hint in normalized for hint in _MEANINGFUL_HINTS):
        return LinkedDirectOutputClassification(
            emit=True,
            reason="meaningful",
            role="assistant",
            preview=preview,
            payload=payload,
        )
    if word_count >= 8:
        return LinkedDirectOutputClassification(
            emit=True,
            reason="meaningful",
            role="assistant",
            preview=preview,
            payload=payload,
        )
    return LinkedDirectOutputClassification(
        emit=False,
        reason="non_actionable",
        role="assistant",
        preview=preview,
        payload=payload,
    )


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
