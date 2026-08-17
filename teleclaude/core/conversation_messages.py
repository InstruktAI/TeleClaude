"""Identity headers and peer-segment message formatter.

Every machine-originated injection into a session uses the canonical bracket:

    [Role - Category (session_id) on computer]
    [Role (session_id) on computer]   # category omitted

``Role`` is a stable taxonomy: ``MachineRoleLabel`` values for machine-role API
callers and resolved session-originated callers with no machine role,
identified by their active agent at the send-message boundary.
``Category`` is a role-specific stable label used by receivers that dispatch
on header alone (checkpoint receiver, render paths). ``session_id`` is the
originator session, full UUID per identity invariant. ``computer`` is the
originator host.

The bracket is the marker. Receivers distinguish machine content from human
content by the leading bracket — there is no separate stripping pass.

A direct-conversation peer message is a distinct, simpler contract: one
``HumanFacingMessage`` header and closing footer per authored segment, no
outer wrapper —

    [Peer (session_id · author-token · utc-minute)]

    <body>

    [/TeleClaude - Peer]

``session_id`` is the source session's full UUID. ``author-token`` is one of
``human:<display>``, ``agent:<runtime>/<thinking-mode>``, or
``machine:<role>``. ``utc-minute`` is the original occurrence timestamp
truncated to the minute in UTC. Exact precision and internal identifiers stay
in transcript and delivery metadata as structured provenance — they are never
rendered. The header and footer are presentation only: they bound the span
for the receiving agent, but attribution is a durable, structural fact
(peer bundle segments, accepted-turn bindings) — nothing parses this pair
to derive or verify authorship.

The peer segment header sits outside the reserved ``[TeleClaude ...]`` control
namespace, so control-header recognition can never mismatch it. A legacy
``[TeleClaude - Peer (session_id) · author-token · utc-minute]`` shape,
written before the header moved out of that namespace, is still recognized —
but its recovery caller in ``conversation_delivery.py`` gates on two proofs
before trusting it: the entry must be older than the turn-binding cutover,
and a correlated accepted row (delivered, never bound) must exist for its
content. ``parse_peer_segments`` itself performs neither check and trusts its
input unconditionally — it is reachable only after its caller has verified
both.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
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
from teleclaude.core.dates import ensure_utc
from teleclaude.core.models import HumanFacingMessage, MessageAuthor
from teleclaude.helpers.agent_types import AgentName, ThinkingMode

_TELECLAUDE_ROLE = "TeleClaude"
_ORCHESTRATOR_ROLE = "Orchestrator"
_EMPTY_SYSTEM_ROLE = ""

_CATEGORY_PEER = "Peer"

_HEADER_FIELD_SEPARATOR = " · "
_UTC_MINUTE_FORMAT = "%Y-%m-%dT%H:%MZ"
_SECTION_SEPARATOR = "\n\n"
_EMPTY_RENDERED_MESSAGE = ""
_PEER_FOOTER = "[/TeleClaude - Peer]"
_RESPONSE_BOUNDARY = (
    "[Mandatory response boundary]\n"
    "After preparing your response, arm the prescribed halt-to-respond reminder as your final tool action. "
    "Then emit only that response and yield.\n"
    "[/Mandatory response boundary]"
)
_CATEGORY_FIELD = "{category}"
_SESSION_ID_FIELD = "{session_id}"
_SEPARATOR_FIELD = "{sep}"
_AUTHOR_TOKEN_FIELD = "{author_token}"
_TIMESTAMP_FIELD = "{timestamp}"
_SOURCE_SESSION_ID_GROUP = "source_session_id"
_TIMESTAMP_GROUP = "timestamp"
_SOURCE_SESSION_ID_PATTERN = (
    rf"(?P<{_SOURCE_SESSION_ID_GROUP}>[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
_AUTHOR_TOKEN_GROUP = "author_token"
_AUTHOR_TOKEN_PATTERN = rf"(?P<{_AUTHOR_TOKEN_GROUP}>.+?)"
_TIMESTAMP_PATTERN = rf"(?P<{_TIMESTAMP_GROUP}>.+?)"

# Peer segment header — outside the reserved `[TeleClaude ...]` control
# namespace: `[Peer (session_id · author-token · utc-minute)]`. Post-cutover
# content is always resolved structurally (accepted-turn binding + peer
# bundle), never text-parsed, so only the rendering template and the
# detection prefix are needed — no parsing pattern.
_PEER_HEADER_TEMPLATE = "[{category} ({session_id}{sep}{author_token}{sep}{timestamp})]"
_PEER_BRIDGE_PREFIX = _PEER_HEADER_TEMPLATE.split(_SESSION_ID_FIELD, maxsplit=1)[0].format(category=_CATEGORY_PEER)

# Legacy peer segment header, in force before the header moved out of the
# reserved `[TeleClaude ...]` control namespace. `parse_peer_segments` parses
# this grammar exclusively — used only by `_recover_legacy_peer_segments`
# (conversation_delivery.py), itself bounded to entries older than the
# turn-binding cutover with a correlated durable record; never reachable from
# text shape alone.
_LEGACY_ROLE_FIELD = "{role}"
_LEGACY_HEADER_TEMPLATE = "[{role} - {category} ({session_id}){sep}{author_token}{sep}{timestamp}]"
_LEGACY_PEER_BRIDGE_PREFIX = _LEGACY_HEADER_TEMPLATE.split(_SESSION_ID_FIELD, maxsplit=1)[0].format(
    role=_TELECLAUDE_ROLE,
    category=_CATEGORY_PEER,
)
_LEGACY_PEER_HEADER_PATTERN_TEXT = (
    re.escape(_LEGACY_HEADER_TEMPLATE)
    .replace(re.escape(_LEGACY_ROLE_FIELD), re.escape(_TELECLAUDE_ROLE))
    .replace(re.escape(_CATEGORY_FIELD), re.escape(_CATEGORY_PEER))
    .replace(re.escape(_SESSION_ID_FIELD), _SOURCE_SESSION_ID_PATTERN)
    .replace(re.escape(_SEPARATOR_FIELD), re.escape(_HEADER_FIELD_SEPARATOR))
    .replace(re.escape(_AUTHOR_TOKEN_FIELD), _AUTHOR_TOKEN_PATTERN)
    .replace(re.escape(_TIMESTAMP_FIELD), _TIMESTAMP_PATTERN)
)
_LEGACY_PEER_BRIDGE_PREFIX_PATTERN = re.compile(rf"^{re.escape(_LEGACY_PEER_BRIDGE_PREFIX)}", re.MULTILINE)
_LEGACY_PEER_HEADER_PATTERN = re.compile(rf"^{_LEGACY_PEER_HEADER_PATTERN_TEXT}", re.MULTILINE)

_BRIDGE_PREFIXES: tuple[str, ...] = (_PEER_BRIDGE_PREFIX, _LEGACY_PEER_BRIDGE_PREFIX)


class MalformedPeerSegmentError(ValueError):
    """Raised when a peer bridge block does not use the canonical segment grammar."""


@dataclass(frozen=True)
class ParsedPeerSegment:
    """One canonical peer segment preserved for onward delivery.

    The parser retains the typed author, source occurrence, and body for
    destination-specific presentation while preserving the complete rendered
    segment for further peer delivery.
    """

    original_source_session_id: str
    author: MessageAuthor
    occurred_at: datetime
    body: str
    rendered_segment: str
    author_job_role: str | None = None


class MachineRoleLabel(StrEnum):
    """Canonical labels for machine-originated session message headers."""

    ORCHESTRATOR = "Orchestrator"
    INTEGRATOR = "Integrator"
    SYSTEM = "System"
    WORKER = "Worker"
    TASKER = "Tasker"
    JOB_RUNNER = "Job Runner"
    AGENT = "Agent"


class TeleClaudeNotificationLabel(StrEnum):
    """Canonical labels for daemon notification-style system messages."""

    NOTIFICATION = "Notification"
    INPUT_REQUEST = "Input Request"


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
)


def resolve_session_event_author(
    *,
    session_id: str,
    system_role: str | None,
    active_agent: str | None,
    thinking_mode: str | None,
) -> MessageAuthor:
    """Build a session's immutable structural author snapshot.

    Agent identity is primary whenever an active agent exists; a system role
    is orthogonal metadata carried alongside it (see ``author_job_role`` on
    the authored span), never a substitute for the agent snapshot. Only a
    session with no active agent falls back to its machine-role label.
    """
    if active_agent:
        return MessageAuthor.for_agent(
            session_id=session_id,
            active_agent=active_agent,
            thinking_mode=thinking_mode,
        )
    role_label = MACHINE_ROLE_LABELS.get((system_role or _EMPTY_SYSTEM_ROLE).strip())
    if role_label is not None:
        return MessageAuthor.for_machine(session_id=session_id, role_label=role_label.value)
    return MessageAuthor.for_machine(session_id=session_id, role_label=MachineRoleLabel.AGENT.value)


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


def format_peer_header(message: HumanFacingMessage) -> str:
    """Build the canonical per-segment header for a human-facing peer message.

    ``[Peer (session_id · author-token · utc-minute)]`` — outside the reserved
    ``[TeleClaude ...]`` control namespace, carrying the source session UUID,
    closed typed author identity, and occurrence timestamp truncated to the
    minute in UTC, all inside one parenthesized group. ``occurred_at`` is
    required on the header, so there is no unknown-timestamp state to guard
    here.
    """
    author = message.author
    # The peer-header contract requires the source session UUID; HUMAN and
    # AGENT authors always carry one by the header's own construction
    # invariant (see MessageAuthor.__post_init__).
    assert author.session_id is not None
    timestamp_label = ensure_utc(message.occurred_at).strftime(_UTC_MINUTE_FORMAT)
    return _PEER_HEADER_TEMPLATE.format(
        category=_CATEGORY_PEER,
        session_id=author.session_id,
        sep=_HEADER_FIELD_SEPARATOR,
        author_token=author.peer_token,
        timestamp=timestamp_label,
    )


def is_conversation_bridge_message(text: str) -> bool:
    """Return True when text is a peer segment header, current or legacy shape."""
    stripped = text.lstrip()
    return any(stripped.startswith(prefix) for prefix in _BRIDGE_PREFIXES)


def parse_peer_segments(text: str) -> tuple[ParsedPeerSegment, ...]:
    """Parse one or more legacy peer segments without interpreting their bodies.

    Legacy-grammar only: this reconstructs pre-cutover ``[TeleClaude - Peer
    ...]`` blocks for ``_recover_legacy_peer_segments``, the sole caller. A
    bridge block must consist entirely of line-anchored canonical headers and
    their bodies. The exact header/body slice for every segment is kept for
    onward rendering; only the source session UUID is extracted for
    target-specific echo prevention.
    """
    position = 0
    parsed: list[ParsedPeerSegment] = []
    while position < len(text):
        header_match = _LEGACY_PEER_HEADER_PATTERN.match(text, position)
        if header_match is None:
            raise MalformedPeerSegmentError
        try:
            occurred_at = datetime.strptime(header_match.group(_TIMESTAMP_GROUP), _UTC_MINUTE_FORMAT).replace(
                tzinfo=UTC
            )
            author = _parse_peer_author(
                session_id=header_match.group(_SOURCE_SESSION_ID_GROUP),
                token=header_match.group(_AUTHOR_TOKEN_GROUP),
            )
        except ValueError as exc:
            raise MalformedPeerSegmentError from exc
        next_bridge_prefix = _LEGACY_PEER_BRIDGE_PREFIX_PATTERN.search(text, header_match.end())
        next_header = _LEGACY_PEER_HEADER_PATTERN.search(text, header_match.end())
        if next_bridge_prefix is None:
            segment_end = len(text)
        else:
            if next_header is None or next_header.start() != next_bridge_prefix.start():
                raise MalformedPeerSegmentError
            segment_end = next_header.start()
            if not text[:segment_end].endswith(_SECTION_SEPARATOR):
                raise MalformedPeerSegmentError
            segment_end -= len(_SECTION_SEPARATOR)
        rendered_segment = text[position:segment_end]
        body_suffix = rendered_segment[header_match.end() - position :]
        if not body_suffix:
            body = _EMPTY_RENDERED_MESSAGE
        elif body_suffix.startswith(_SECTION_SEPARATOR):
            body = body_suffix.removeprefix(_SECTION_SEPARATOR)
        else:
            raise MalformedPeerSegmentError
        parsed.append(
            ParsedPeerSegment(
                original_source_session_id=header_match.group(_SOURCE_SESSION_ID_GROUP),
                author=author,
                occurred_at=occurred_at,
                body=body,
                rendered_segment=rendered_segment,
            )
        )
        if next_bridge_prefix is None:
            break
        position = next_header.start()
    if not parsed:
        raise MalformedPeerSegmentError
    return tuple(parsed)


def peer_segment_from_authored_span(
    *,
    original_source_session_id: str,
    author: MessageAuthor,
    occurred_at: datetime,
    body: str,
    author_job_role: str | None = None,
) -> ParsedPeerSegment:
    """Reconstruct a ``ParsedPeerSegment`` from a durably persisted authored span.

    The structural counterpart to ``parse_peer_segments``: author, source
    session, and occurrence time are typed facts read from durable storage,
    not extracted by regex from rendered text. The rendered form is derived
    the same way outbound rendering derives it, so onward forwarding is
    byte-identical to the text-parsed path it replaces.
    """
    message = HumanFacingMessage(author=author, occurred_at=occurred_at, body=body)
    rendered_segment = _format_with_body(format_peer_header(message), body.strip())
    return ParsedPeerSegment(
        original_source_session_id=original_source_session_id,
        author=author,
        occurred_at=occurred_at,
        body=body,
        rendered_segment=rendered_segment,
        author_job_role=author_job_role,
    )


def _parse_peer_author(*, session_id: str, token: str) -> MessageAuthor:
    """Decode one closed peer-header author token without display inference."""
    author_kind, separator, value = token.partition(":")
    if not separator or not value:
        raise ValueError("Peer author token is malformed")
    if author_kind == "human":
        return MessageAuthor.for_human(session_id=session_id, display_name=value)
    if author_kind == "agent":
        runtime, mode_separator, thinking_mode = value.partition("/")
        if (
            not mode_separator
            or not runtime
            or not thinking_mode
            or runtime not in AgentName.choices()
            or thinking_mode not in ThinkingMode.choices()
        ):
            raise ValueError("Peer agent token is malformed")
        return MessageAuthor.for_agent(
            session_id=session_id,
            active_agent=runtime,
            thinking_mode=thinking_mode,
        )
    if author_kind == "machine":
        return MessageAuthor.for_machine(session_id=session_id, role_label=MachineRoleLabel(value).value)
    raise ValueError("Peer author token is unknown")


def format_peer_footer() -> str:
    """Build the canonical closing delimiter for a human-facing peer segment.

    Bounds the injected span for the receiving agent's benefit only —
    presentation, never authority. Nothing in this module or its consumers
    parses the footer back out to derive or verify attribution; the durable
    accepted-turn binding is what makes composed authorship structural.
    """
    return _PEER_FOOTER


def _format_with_body(header: str, content: str) -> str:
    if not content:
        return f"{header}{_SECTION_SEPARATOR}{format_peer_footer()}"
    return f"{header}{_SECTION_SEPARATOR}{content}{_SECTION_SEPARATOR}{format_peer_footer()}"


def format_peer_message(*, messages: list[HumanFacingMessage | ParsedPeerSegment]) -> str:
    """Format an ordered list of human-facing messages into one bridge body.

    Each entry renders its own author header immediately followed by its
    body and a closing footer, in temporal order — one actual author, one
    bounded span, per segment. There is no outer wrapper and no inner
    authorship marker; the per-entry header carries the full identity, and
    the header/footer pair is presentation only — bounding the span for the
    receiving agent, never parsed back out to derive attribution. Empty
    input yields an empty string; callers must skip delivery when no
    messages exist.
    """
    if not messages:
        return _EMPTY_RENDERED_MESSAGE
    sections = [
        message.rendered_segment
        if isinstance(message, ParsedPeerSegment)
        else _format_with_body(format_peer_header(message), message.body.strip())
        for message in messages
    ]
    return _SECTION_SEPARATOR.join((*sections, _RESPONSE_BOUNDARY))


def format_identity_conversation(*, header: str, body: str) -> tuple[str, int, int]:
    """Render an identity-bearing conversation with platform-owned boundaries."""
    prefix = f"{header}{_SECTION_SEPARATOR}"
    suffix = f"{_SECTION_SEPARATOR}{_RESPONSE_BOUNDARY}"
    return f"{prefix}{body}{suffix}", len(prefix), len(suffix)


def is_orchestrator_dispatch_message(text: str) -> bool:
    """Return True when text is an orchestrator dispatch."""
    return text.lstrip().startswith(f"[{_ORCHESTRATOR_ROLE} ")
