"""Identity headers and conversation bridge message formatters.

Every machine-originated injection into a session uses the canonical bracket:

    [Role - Category (session_id) on computer]
    [Role (session_id) on computer]   # category omitted

``Role`` is a stable taxonomy: ``TeleClaude`` for daemon-injected bridge
messages; ``Orchestrator``, ``Integrator``, ``System`` for machine-role API
callers whose marker is prepended at the send-message boundary
(see ``_MACHINE_ROLE_LABELS`` in ``teleclaude/api/sessions_routes.py``).
``Category`` is a role-specific stable label used by receivers that dispatch
on header alone (checkpoint receiver, render paths) — only TeleClaude bridges
carry one. ``session_id`` is the originator session, full UUID per identity
invariant. ``computer`` is the originator host.

The bracket is the marker. Receivers distinguish machine content from human
content by the leading bracket — there is no separate stripping pass.
"""

from __future__ import annotations

from datetime import datetime

_TELECLAUDE_ROLE = "TeleClaude"
_ORCHESTRATOR_ROLE = "Orchestrator"

_CATEGORY_LINKED_OUTPUT = "Linked output"
_CATEGORY_CONVERSATION_UPDATE = "Conversation update"
_CATEGORY_DIRECT_CONVERSATION = "Direct Conversation"
_CATEGORY_HUMAN_IN_THE_LOOP = "Human in the Loop"

_BRIDGE_PREFIXES: tuple[str, ...] = (
    f"[{_TELECLAUDE_ROLE} - {_CATEGORY_LINKED_OUTPUT}",
    f"[{_TELECLAUDE_ROLE} - {_CATEGORY_CONVERSATION_UPDATE}",
    f"[{_TELECLAUDE_ROLE} - {_CATEGORY_DIRECT_CONVERSATION}",
    f"[{_TELECLAUDE_ROLE} - {_CATEGORY_HUMAN_IN_THE_LOOP}",
)


def format_identity_header(
    *,
    role: str,
    session_id: str,
    computer: str,
    category: str | None = None,
) -> str:
    """Build the canonical identity bracket for a machine-originated message."""
    if category:
        return f"[{role} - {category} ({session_id}) on {computer}]"
    return f"[{role} ({session_id}) on {computer}]"


def is_conversation_bridge_message(text: str) -> bool:
    """Return True when text is a TeleClaude conversation bridge message."""
    stripped = text.lstrip()
    return any(stripped.startswith(prefix) for prefix in _BRIDGE_PREFIXES)


def _format_with_body(header: str, content: str) -> str:
    return f"{header}\n\n{content}" if content else header


def format_linked_output_message(
    *,
    sender_session_id: str,
    sender_computer: str,
    content: str,
) -> str:
    """Format mirrored assistant output for a peer session."""
    header = format_identity_header(
        role=_TELECLAUDE_ROLE,
        category=_CATEGORY_LINKED_OUTPUT,
        session_id=sender_session_id,
        computer=sender_computer,
    )
    return _format_with_body(header, content)


def format_direct_conversation_intro_header(
    *,
    caller_session_id: str,
    caller_computer: str,
) -> str:
    """Build the identity header for the first message of a direct link."""
    return format_identity_header(
        role=_TELECLAUDE_ROLE,
        category=_CATEGORY_DIRECT_CONVERSATION,
        session_id=caller_session_id,
        computer=caller_computer,
    )


def format_bundled_conversation_message(
    *,
    sender_session_id: str,
    sender_computer: str,
    segments: list[tuple[str, datetime | None, str]],
) -> str:
    """Format multiple role-tagged turns into ONE bracketed body.

    ``segments`` is an ordered list of ``(role, timestamp, text)`` where
    ``role`` is ``"user"`` or ``"assistant"`` and ``timestamp`` may be None
    when the source transcript has none. Empty input yields an empty string;
    callers must skip delivery when no segments exist.

    The outer header is the canonical identity bracket. Inner segments carry
    per-turn markers (``--- Human in the Loop @ <iso> ---`` for user turns,
    ``--- Linked output @ <iso> ---`` for assistant turns) so the receiver
    can reconstruct the temporal sequence.
    """
    if not segments:
        return ""
    sections: list[str] = []
    for role, ts, text in segments:
        marker_label = _CATEGORY_HUMAN_IN_THE_LOOP if role == "user" else _CATEGORY_LINKED_OUTPUT
        ts_label = ts.isoformat() if isinstance(ts, datetime) else "unknown"
        sections.append(f"--- {marker_label} @ {ts_label} ---\n{text.strip()}")
    body = "\n\n".join(sections)
    header = format_identity_header(
        role=_TELECLAUDE_ROLE,
        category=_CATEGORY_CONVERSATION_UPDATE,
        session_id=sender_session_id,
        computer=sender_computer,
    )
    return _format_with_body(header, body)


def is_orchestrator_dispatch_message(text: str) -> bool:
    """Return True when text is an orchestrator dispatch."""
    return text.lstrip().startswith(f"[{_ORCHESTRATOR_ROLE} ")
