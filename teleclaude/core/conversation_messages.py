"""Identity headers and peer-bridge message formatter.

Every machine-originated injection into a session uses the canonical bracket:

    [Role - Category (session_id) on computer]
    [Role (session_id) on computer]   # category omitted

``Role`` is a stable taxonomy: ``TeleClaude`` for daemon-injected peer
bridges; ``MachineRoleLabel`` values for machine-role API callers whose
marker is prepended at the send-message boundary.
``Category`` is a role-specific stable label used by receivers that dispatch
on header alone (checkpoint receiver, render paths) — TeleClaude bridges
carry the ``Peer`` category. ``session_id`` is the originator session, full
UUID per identity invariant. ``computer`` is the originator host.

The bracket is the marker. Receivers distinguish machine content from human
content by the leading bracket — there is no separate stripping pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from teleclaude.constants import (
    ROLE_INTEGRATOR,
    ROLE_JOB_RUNNER,
    ROLE_ORCHESTRATOR,
    ROLE_SYSTEM,
    ROLE_TASKER,
    ROLE_WORKER,
)

_TELECLAUDE_ROLE = "TeleClaude"
_ORCHESTRATOR_ROLE = "Orchestrator"

_CATEGORY_PEER = "Peer"
_SEGMENT_HUMAN = "Human"
_SEGMENT_AGENT = "Agent"

_BRIDGE_PREFIXES: tuple[str, ...] = (f"[{_TELECLAUDE_ROLE} - {_CATEGORY_PEER}",)


class MachineRoleLabel(StrEnum):
    """Canonical labels for machine-originated session message headers."""

    ORCHESTRATOR = "Orchestrator"
    INTEGRATOR = "Integrator"
    SYSTEM = "System"
    WORKER = "Worker"
    TASKER = "Tasker"
    JOB_RUNNER = "Job Runner"


class TeleClaudeNotificationLabel(StrEnum):
    """Canonical labels for daemon notification-style system messages."""

    NOTIFICATION = "Notification"
    INPUT_REQUEST = "Input Request"
    LINKED_OUTPUT = "Linked Output"
    LINKED_OUTPUT_NOTIFICATION = "Linked Output Notification"


MACHINE_ROLE_LABELS: Mapping[str, MachineRoleLabel] = MappingProxyType(
    {
        ROLE_ORCHESTRATOR: MachineRoleLabel.ORCHESTRATOR,
        ROLE_INTEGRATOR: MachineRoleLabel.INTEGRATOR,
        ROLE_SYSTEM: MachineRoleLabel.SYSTEM,
        ROLE_WORKER: MachineRoleLabel.WORKER,
        ROLE_TASKER: MachineRoleLabel.TASKER,
        ROLE_JOB_RUNNER: MachineRoleLabel.JOB_RUNNER,
    }
)
TELECLAUDE_NOTIFICATION_LABELS: tuple[TeleClaudeNotificationLabel, ...] = (
    TeleClaudeNotificationLabel.NOTIFICATION,
    TeleClaudeNotificationLabel.INPUT_REQUEST,
    TeleClaudeNotificationLabel.LINKED_OUTPUT,
    TeleClaudeNotificationLabel.LINKED_OUTPUT_NOTIFICATION,
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
