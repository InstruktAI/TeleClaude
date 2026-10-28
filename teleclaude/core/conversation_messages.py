"""Identity headers and peer-segment message formatter.

Every machine-originated injection into a session uses the canonical bracket:

    [Role - Category (session_id) on computer · utc-minute]
    [Role (session_id) on computer · utc-minute]   # category omitted

``Role`` names who is speaking: the caller's role name, or a ``MachineRoleLabel``
(``Agent``, ``System``) for a caller carrying no role; an agent caller carries
``Agent`` with its agent and role in ``Category``. Receivers recognize the
envelope by its shape and read neither field; they are there for the reading
agent. ``session_id`` is the originator session, full UUID per identity
invariant. ``computer`` is the originator host.

The bracket is the marker. Receivers distinguish machine content from human
content by complete registered envelope shape — there is no separate stripping
pass.

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
rendered. The header and footer carry presentation and source facts. Complete
registered shapes are the sole recognition contract; bodies remain opaque and
header values are carried rather than validated.

The peer segment header sits outside the reserved ``[TeleClaude ...]`` control
namespace, so control-header recognition can never mismatch it. Retired
shapes remain ordinary human input.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from teleclaude.core.dates import ensure_utc
from teleclaude.core.injected_text import (
    ENVELOPE_REGISTRY,
    EnvelopeField,
    EnvelopeName,
    MachineRoleLabel,
    envelope_bracket_opening,
    identity_content_envelope,
    is_peer_opening,
    render_bracket_envelope,
    scan_injected_envelopes,
    semantic_envelope,
)
from teleclaude.core.models import HumanFacingMessage, MessageAuthor, MessageAuthorKind
from teleclaude.core.roles import Role, resolve_role

_CATEGORY_PREFIX_TEMPLATE = " - {category}"
_EMPTY_CATEGORY = ""

_UTC_MINUTE_FORMAT = "%Y-%m-%dT%H:%MZ"
_SECTION_SEPARATOR = "\n\n"
_EMPTY_RENDERED_MESSAGE = ""
_PEER_HEADER_TEMPLATE = ENVELOPE_REGISTRY[EnvelopeName.PEER].bracket_opening
_PEER_SOURCE_FIELD = f"{{{EnvelopeField.SESSION_ID.value}}}"
_PEER_AUTHOR_FIELD = f"{{{EnvelopeField.AUTHOR_TOKEN.value}}}"
_PEER_OCCURRENCE_FIELD = f"{{{EnvelopeField.OCCURRED_AT.value}}}"
_PEER_HEADER_PREFIX, _PEER_HEADER_SOURCE_TAIL = _PEER_HEADER_TEMPLATE.split(_PEER_SOURCE_FIELD, maxsplit=1)
_PEER_HEADER_FIELD_SEPARATOR, _PEER_HEADER_AUTHOR_TAIL = _PEER_HEADER_SOURCE_TAIL.split(_PEER_AUTHOR_FIELD, maxsplit=1)
_, _PEER_HEADER_SUFFIX = _PEER_HEADER_AUTHOR_TAIL.split(_PEER_OCCURRENCE_FIELD, maxsplit=1)


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


def machine_role_label(role: str | None) -> str:
    """The identity-header label for a session running no agent: its role's name, the agent label when it has none."""
    resolved = resolve_role(role)
    return resolved.name.value if isinstance(resolved, Role) else MachineRoleLabel.AGENT.value


def resolve_session_event_author(
    *,
    session_id: str,
    role: str | None,
    active_agent: str | None,
    thinking_mode: str | None,
) -> MessageAuthor:
    """Build a session's immutable structural author snapshot.

    Agent identity is primary whenever an active agent exists; a role
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
    return MessageAuthor.for_machine(session_id=session_id, role_label=machine_role_label(role))


def format_identity_header(
    *,
    role: str,
    session_id: str,
    computer: str,
    occurred_at: datetime,
    category: str | None = None,
) -> str:
    """Build the canonical identity bracket for a machine-originated message.

    Occurrence time is rendered once, into the opening, in the same UTC-minute
    grammar the peer and action envelopes use. The paired closing is derived
    from this rendered opening, so the two can never disagree.
    """
    category_segment = _CATEGORY_PREFIX_TEMPLATE.format(category=category) if category else _EMPTY_CATEGORY
    return envelope_bracket_opening(
        semantic_envelope(
            EnvelopeName.CALLER_IDENTITY,
            fields={
                EnvelopeField.ROLE: role,
                EnvelopeField.CATEGORY: category_segment,
                EnvelopeField.SESSION_ID: session_id,
                EnvelopeField.COMPUTER: computer,
                EnvelopeField.OCCURRED_AT: ensure_utc(occurred_at).strftime(_UTC_MINUTE_FORMAT),
            },
        )
    )


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
    return envelope_bracket_opening(
        semantic_envelope(
            EnvelopeName.PEER,
            fields={
                EnvelopeField.SESSION_ID: author.session_id,
                EnvelopeField.AUTHOR_TOKEN: author.peer_token,
                EnvelopeField.OCCURRED_AT: timestamp_label,
            },
        )
    )


def peer_segments_from_entry(text: str, *, occurred_at: datetime) -> tuple[ParsedPeerSegment, ...]:
    """Extract peer segments from complete registry-recognized envelopes."""
    segments: list[ParsedPeerSegment] = []
    for candidate in scan_injected_envelopes(text):
        if not is_peer_opening(candidate.opening):
            continue
        source_session_id, author_token, _ = _peer_header_fields(candidate.opening)
        body_start, body_end = candidate.body_span
        segments.append(
            ParsedPeerSegment(
                original_source_session_id=source_session_id,
                author=_peer_author_from_token(session_id=source_session_id, token=author_token),
                occurred_at=occurred_at,
                body=text[body_start:body_end].strip(),
                rendered_segment=text[candidate.envelope_span[0] : candidate.envelope_span[1]],
            )
        )
    return tuple(segments)


def _peer_header_fields(opening: str) -> tuple[str, str, str]:
    """Return the carried structural fields from a recognized peer opening."""
    fields = (
        opening.removeprefix(_PEER_HEADER_PREFIX)
        .removesuffix(_PEER_HEADER_SUFFIX)
        .split(_PEER_HEADER_FIELD_SEPARATOR, maxsplit=2)
    )
    return fields[0], fields[1], fields[2]


def _peer_author_from_token(*, session_id: str, token: str) -> MessageAuthor:
    """Decode a carried peer token without validating its vocabulary."""
    author_kind, separator, value = token.partition(":")
    if separator and value and author_kind == "human":
        return MessageAuthor.for_human(session_id=session_id, display_name=value)
    if separator and value and author_kind == "agent":
        runtime, mode_separator, thinking_mode = value.partition("/")
        if mode_separator and runtime and thinking_mode:
            return MessageAuthor(
                kind=MessageAuthorKind.AGENT,
                display=f"{runtime.title()}/{thinking_mode}",
                session_id=session_id,
                agent_runtime=runtime,
                thinking_mode=thinking_mode,
            )
    if separator and value and author_kind == "machine":
        return MessageAuthor(
            kind=MessageAuthorKind.MACHINE,
            display=value,
            session_id=session_id,
            machine_role=value,
        )
    return MessageAuthor.for_human(session_id=session_id, display_name=token)


def format_peer_footer() -> str:
    """Build the canonical closing delimiter for a human-facing peer segment.

    The registry's paired-envelope recognizer uses this declared delimiter to
    bound the opaque peer span. After recognition, the opening carries the
    source and presentation fields used for attribution.
    """
    return ENVELOPE_REGISTRY[EnvelopeName.PEER].bracket_closing


def _render_peer_message(message: HumanFacingMessage) -> str:
    """Render one peer segment through the registry-owned bracket codec."""
    author = message.author
    assert author.session_id is not None
    return render_bracket_envelope(
        semantic_envelope(
            EnvelopeName.PEER,
            fields={
                EnvelopeField.SESSION_ID: author.session_id,
                EnvelopeField.AUTHOR_TOKEN: author.peer_token,
                EnvelopeField.OCCURRED_AT: ensure_utc(message.occurred_at).strftime(_UTC_MINUTE_FORMAT),
            },
            body=message.body.strip(),
        )
    )


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
        message.rendered_segment if isinstance(message, ParsedPeerSegment) else _render_peer_message(message)
        for message in messages
    ]
    return _SECTION_SEPARATOR.join(sections)


def format_identity_conversation(*, header: str, body: str, occurrence_key: str | None = None) -> tuple[str, int, int]:
    """Render an identity-bearing conversation with platform-owned boundaries."""
    envelope = identity_content_envelope(header, body, occurrence_key)
    body_start, body_end = envelope.body_span
    return envelope.rendered, body_start, len(envelope.rendered) - body_end
