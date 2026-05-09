"""Identity headers and peer-bridge message formatter.

Every machine-originated injection into a session uses the canonical bracket:

    [Role - Category (session_id) on computer]
    [Role (session_id) on computer]   # category omitted

``Role`` is a stable taxonomy: ``TeleClaude`` for daemon-injected peer
bridges; ``Orchestrator``, ``Integrator``, ``System`` for machine-role API
callers whose marker is prepended at the send-message boundary
(see ``_MACHINE_ROLE_LABELS`` in ``teleclaude/api/sessions_routes.py``).
``Category`` is a role-specific stable label used by receivers that dispatch
on header alone (checkpoint receiver, render paths) — TeleClaude bridges
carry the ``Peer`` category. ``session_id`` is the originator session, full
UUID per identity invariant. ``computer`` is the originator host.

The bracket is the marker. Receivers distinguish machine content from human
content by the leading bracket — there is no separate stripping pass.
"""

from __future__ import annotations

from datetime import datetime

_TELECLAUDE_ROLE = "TeleClaude"
_ORCHESTRATOR_ROLE = "Orchestrator"
_INTEGRATOR_ROLE = "Integrator"
_SYSTEM_ROLE = "System"

_CATEGORY_PEER = "Peer"
_SEGMENT_HUMAN = "Human"
_SEGMENT_AGENT = "Agent"

_BRIDGE_PREFIXES: tuple[str, ...] = (f"[{_TELECLAUDE_ROLE} - {_CATEGORY_PEER}",)

# All canonical machine-role headers that the API wraps around outbound messages.
# Any user-role transcript block whose text starts with one of these is a
# machine-injected paste, not real human input. See `_MACHINE_ROLE_LABELS` in
# `teleclaude/api/sessions_routes.py` for the producing side.
_MACHINE_ORIGINATED_PREFIXES: tuple[str, ...] = (
    f"[{_TELECLAUDE_ROLE} - {_CATEGORY_PEER}",
    f"[{_ORCHESTRATOR_ROLE} ",
    f"[{_INTEGRATOR_ROLE} ",
    f"[{_SYSTEM_ROLE} ",
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


def format_peer_header(*, sender_session_id: str, sender_computer: str) -> str:
    """Build the canonical outer header for a peer-originated message."""
    return format_identity_header(
        role=_TELECLAUDE_ROLE,
        category=_CATEGORY_PEER,
        session_id=sender_session_id,
        computer=sender_computer,
    )


def is_conversation_bridge_message(text: str) -> bool:
    """Return True when text is a TeleClaude peer-bridge message."""
    stripped = text.lstrip()
    return any(stripped.startswith(prefix) for prefix in _BRIDGE_PREFIXES)


def _format_with_body(header: str, content: str) -> str:
    return f"{header}\n\n{content}" if content else header


def format_peer_message(
    *,
    sender_session_id: str,
    sender_computer: str,
    segments: list[tuple[str, datetime | None, str]],
) -> str:
    """Format role-tagged turns from a peer session into one bracketed body.

    ``segments`` is an ordered list of ``(role, timestamp, text)`` where
    ``role`` is ``"user"`` or ``"assistant"`` and ``timestamp`` may be None
    when the source transcript has none. Empty input yields an empty string;
    callers must skip delivery when no segments exist.

    The outer header is the canonical identity bracket. Inner segments carry
    per-turn markers (``--- Human @ <iso> ---`` for user turns,
    ``--- Agent @ <iso> ---`` for assistant turns) so the receiver can
    reconstruct the temporal sequence.
    """
    if not segments:
        return ""
    sections: list[str] = []
    for role, ts, text in segments:
        marker_label = _SEGMENT_HUMAN if role == "user" else _SEGMENT_AGENT
        ts_label = ts.isoformat() if isinstance(ts, datetime) else "unknown"
        sections.append(f"--- {marker_label} @ {ts_label} ---\n{text.strip()}")
    body = "\n\n".join(sections)
    return _format_with_body(
        format_peer_header(sender_session_id=sender_session_id, sender_computer=sender_computer),
        body,
    )


def is_orchestrator_dispatch_message(text: str) -> bool:
    """Return True when text is an orchestrator dispatch."""
    return text.lstrip().startswith(f"[{_ORCHESTRATOR_ROLE} ")


def is_machine_originated_user_text(text: str) -> bool:
    """Return True when a user-role block is actually a machine-injected paste.

    Covers every canonical machine-role header (``TeleClaude - Peer``,
    ``Orchestrator``, ``Integrator``, ``System``). Used by the conversation
    collector to keep these blocks out of the bundled delivery — re-shipping
    them to the peer would echo machine framing as human input.
    """
    stripped = text.lstrip()
    return any(stripped.startswith(prefix) for prefix in _MACHINE_ORIGINATED_PREFIXES)
