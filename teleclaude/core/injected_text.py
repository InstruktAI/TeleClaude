"""Typed vocabulary and paired envelopes for platform-injected session text."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from html import escape as _xml_escape
from types import MappingProxyType


class TranscriptEntryKind(StrEnum):
    """The durable classification assigned to each accepted transcript entry."""

    PLATFORM_CONTROL = "platform_control"
    IDENTITY_CONTENT = "identity_content"
    REMINDER = "reminder"
    ORDINARY = "ordinary"


class InjectedTextSourceFeature(StrEnum):
    """Closed producer vocabulary persisted with every accepted text occurrence."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    WEB = "web"
    VOICE = "voice"
    RELAY = "relay"
    CALLER_SEND = "caller_send"
    PEER_BUNDLE = "peer_bundle"
    LISTENER = "listener"
    AGENT_RESTART = "agent_restart"
    REMINDER = "reminder"


class PlatformTextLabel(StrEnum):
    """Closed labels used by platform-authored control envelopes."""

    CHECKPOINT = "Checkpoint"
    NOTIFICATION = "Notification"
    RESTART_CONTINUATION = "Restart Continuation"


class EnvelopeName(StrEnum):
    """Closed semantic envelope vocabulary shared by every renderer."""

    CHECKPOINT = "checkpoint"
    NOTIFICATION = "notification"
    WAKE = "wake"
    RESTART_CONTINUATION = "restart_continuation"
    PEER = "peer"
    LEGACY_PEER = "legacy_peer"
    CALLER_IDENTITY = "caller_identity"
    REMINDER = "reminder"
    ACTION = "action"


class EnvelopeClosure(StrEnum):
    """The one declared closure discipline for an envelope definition."""

    PAIRED = "paired"
    AUTO_CLOSED = "auto_closed"


class EnvelopeField(StrEnum):
    """Structured values consumed by the closed envelope vocabulary."""

    AUTHOR_TOKEN = "author_token"
    CATEGORY = "category"
    COMPUTER = "computer"
    OCCURRED_AT = "occurred_at"
    OCCURRENCE_KEY = "occurrence_key"
    ROLE = "role"
    SESSION_ID = "session_id"
    SLUG = "slug"
    TOPIC = "topic"


class MachineRoleLabel(StrEnum):
    """Closed caller-role vocabulary rendered by the identity envelope."""

    ORCHESTRATOR = "Orchestrator"
    INTEGRATOR = "Integrator"
    SYSTEM = "System"
    WORKER = "Worker"
    TASKER = "Tasker"
    JOB_RUNNER = "Job Runner"
    AGENT = "Agent"


@dataclass(frozen=True)
class EnvelopeDefinition:
    """One registry-owned grammar, recognition, and rendering discipline."""

    name: EnvelopeName
    kind: TranscriptEntryKind
    closure: EnvelopeClosure
    bracket_opening: str
    bracket_closing: str
    xml_tag: str
    opening_pattern: re.Pattern[str] | None
    required_fields: frozenset[EnvelopeField] = frozenset()
    output_only: bool = False


@dataclass(frozen=True)
class SemanticEnvelope:
    """A typed envelope rendered by exactly one registry-owned codec."""

    definition: EnvelopeDefinition
    fields: Mapping[EnvelopeField, str]
    body: str = ""

    def __post_init__(self) -> None:
        missing_fields = self.definition.required_fields.difference(self.fields)
        if missing_fields:
            raise ValueError("Envelope is missing required structured header fields")
        if self.definition.closure is EnvelopeClosure.AUTO_CLOSED and self.body:
            raise ValueError("Auto-closed envelopes cannot carry a body")


_CHECKPOINT_ENVELOPE = EnvelopeName.CHECKPOINT
_NOTIFICATION_ENVELOPE = EnvelopeName.NOTIFICATION
_WAKE_ENVELOPE = EnvelopeName.WAKE
_RESTART_CONTINUATION_ENVELOPE = EnvelopeName.RESTART_CONTINUATION
_PEER_ENVELOPE = EnvelopeName.PEER
_LEGACY_PEER_ENVELOPE = EnvelopeName.LEGACY_PEER
_CALLER_IDENTITY_ENVELOPE = EnvelopeName.CALLER_IDENTITY
_REMINDER_ENVELOPE = EnvelopeName.REMINDER
_ACTION_ENVELOPE = EnvelopeName.ACTION
_EMPTY_BRACKET_CLOSING = ""
_CHECKPOINT_BRACKET_OPENING = "[TeleClaude Checkpoint]"
_NOTIFICATION_BRACKET_OPENING = "[TeleClaude Notification]"
_WAKE_BRACKET_OPENING = "[TeleClaude Wake]"
_RESTART_CONTINUATION_BRACKET_OPENING = "[TeleClaude Restart Continuation]"
_PEER_BRACKET_OPENING = "[Peer ({session_id} · {author_token} · {occurred_at})]"
_LEGACY_PEER_BRACKET_OPENING = "[TeleClaude - Peer ({session_id}) · {author_token} · {occurred_at}]"
_CALLER_IDENTITY_BRACKET_OPENING = "[{role}{category} ({session_id}) on {computer}]"
_REMINDER_BRACKET_OPENING = "[Reminder {slug} {occurrence_key}]"
_ACTION_BRACKET_OPENING = "[Action ({topic} · {occurred_at})]"
_CHECKPOINT_BRACKET_CLOSING = "[/TeleClaude Checkpoint]"
_NOTIFICATION_BRACKET_CLOSING = "[/TeleClaude Notification]"
_RESTART_CONTINUATION_BRACKET_CLOSING = "[/TeleClaude Restart Continuation]"
_PEER_BRACKET_CLOSING = "[/TeleClaude - Peer]"
_LEGACY_PEER_BRACKET_CLOSING = "[/TeleClaude - Peer]"
_CALLER_IDENTITY_BRACKET_CLOSING = "[/{role}{category} ({session_id}) on {computer}]"
_REMINDER_BRACKET_CLOSING = "[/Reminder {slug} {occurrence_key}]"
_ACTION_BRACKET_CLOSING = "[/Action]"
_CHECKPOINT_XML_TAG = "teleclaude-checkpoint"
_NOTIFICATION_XML_TAG = "teleclaude-notification"
_WAKE_XML_TAG = "teleclaude-wake"
_RESTART_CONTINUATION_XML_TAG = "teleclaude-restart-continuation"
_PEER_XML_TAG = "teleclaude-peer"
_CALLER_IDENTITY_XML_TAG = "teleclaude-caller"
_REMINDER_XML_TAG = "teleclaude-reminder"
_ACTION_XML_TAG = "teleclaude-action"
_CHECKPOINT_OPENING_RE = re.compile(re.escape(_CHECKPOINT_BRACKET_OPENING))
_NOTIFICATION_OPENING_RE = re.compile(re.escape(_NOTIFICATION_BRACKET_OPENING))
_WAKE_OPENING_RE = re.compile(re.escape(_WAKE_BRACKET_OPENING))
_RESTART_CONTINUATION_OPENING_RE = re.compile(re.escape(_RESTART_CONTINUATION_BRACKET_OPENING))
_PEER_OPENING_RE = re.compile(r"\[Peer \([^\]\n]+\)\]")
_CALLER_IDENTITY_OPENING_RE = re.compile(
    r"\[(?:Orchestrator|Integrator|System|Worker|Tasker|Job Runner|Agent)(?: - [^\]\n]+)? \([^\]\n]+\) on [^\]\n]+\]"
)
_REMINDER_OPENING_RE = re.compile(r"\[Reminder [^\]\n]+\]")
_IDENTITY_FIELDS = frozenset({EnvelopeField.ROLE, EnvelopeField.SESSION_ID, EnvelopeField.COMPUTER})
_PEER_FIELDS = frozenset({EnvelopeField.SESSION_ID, EnvelopeField.AUTHOR_TOKEN, EnvelopeField.OCCURRED_AT})
_REMINDER_FIELDS = frozenset({EnvelopeField.SLUG, EnvelopeField.OCCURRENCE_KEY})
_ACTION_FIELDS = frozenset({EnvelopeField.TOPIC, EnvelopeField.OCCURRED_AT})
_EMPTY_ENVELOPE_FIELDS: Mapping[EnvelopeField, str] = MappingProxyType({})
_PLATFORM_LABEL_ENVELOPES: Mapping[PlatformTextLabel, EnvelopeName] = MappingProxyType(
    {
        PlatformTextLabel.CHECKPOINT: EnvelopeName.CHECKPOINT,
        PlatformTextLabel.NOTIFICATION: EnvelopeName.NOTIFICATION,
        PlatformTextLabel.RESTART_CONTINUATION: EnvelopeName.RESTART_CONTINUATION,
    }
)
_XML_ATTRIBUTE_TEMPLATE = ' {name}="{value}"'
_XML_PAIRED_TEMPLATE = "<{tag}{attributes}>{body}</{tag}>"
_XML_AUTO_CLOSED_TEMPLATE = "<{tag}{attributes} />"
_XML_ATTRIBUTE_SEPARATOR = ""

ENVELOPE_REGISTRY: Mapping[EnvelopeName, EnvelopeDefinition] = MappingProxyType(
    {
        _CHECKPOINT_ENVELOPE: EnvelopeDefinition(
            _CHECKPOINT_ENVELOPE,
            TranscriptEntryKind.PLATFORM_CONTROL,
            EnvelopeClosure.PAIRED,
            _CHECKPOINT_BRACKET_OPENING,
            _CHECKPOINT_BRACKET_CLOSING,
            _CHECKPOINT_XML_TAG,
            _CHECKPOINT_OPENING_RE,
        ),
        _NOTIFICATION_ENVELOPE: EnvelopeDefinition(
            _NOTIFICATION_ENVELOPE,
            TranscriptEntryKind.PLATFORM_CONTROL,
            EnvelopeClosure.PAIRED,
            _NOTIFICATION_BRACKET_OPENING,
            _NOTIFICATION_BRACKET_CLOSING,
            _NOTIFICATION_XML_TAG,
            _NOTIFICATION_OPENING_RE,
        ),
        _WAKE_ENVELOPE: EnvelopeDefinition(
            _WAKE_ENVELOPE,
            TranscriptEntryKind.PLATFORM_CONTROL,
            EnvelopeClosure.AUTO_CLOSED,
            _WAKE_BRACKET_OPENING,
            _EMPTY_BRACKET_CLOSING,
            _WAKE_XML_TAG,
            _WAKE_OPENING_RE,
        ),
        _RESTART_CONTINUATION_ENVELOPE: EnvelopeDefinition(
            _RESTART_CONTINUATION_ENVELOPE,
            TranscriptEntryKind.PLATFORM_CONTROL,
            EnvelopeClosure.PAIRED,
            _RESTART_CONTINUATION_BRACKET_OPENING,
            _RESTART_CONTINUATION_BRACKET_CLOSING,
            _RESTART_CONTINUATION_XML_TAG,
            _RESTART_CONTINUATION_OPENING_RE,
        ),
        _PEER_ENVELOPE: EnvelopeDefinition(
            _PEER_ENVELOPE,
            TranscriptEntryKind.IDENTITY_CONTENT,
            EnvelopeClosure.PAIRED,
            _PEER_BRACKET_OPENING,
            _PEER_BRACKET_CLOSING,
            _PEER_XML_TAG,
            _PEER_OPENING_RE,
            _PEER_FIELDS,
        ),
        # Legacy peer recovery is owned by conversation_messages.parse_peer_segments,
        # so the scanner deliberately does not recognize this opening.
        _LEGACY_PEER_ENVELOPE: EnvelopeDefinition(
            _LEGACY_PEER_ENVELOPE,
            TranscriptEntryKind.IDENTITY_CONTENT,
            EnvelopeClosure.PAIRED,
            _LEGACY_PEER_BRACKET_OPENING,
            _LEGACY_PEER_BRACKET_CLOSING,
            _PEER_XML_TAG,
            None,
            _PEER_FIELDS,
        ),
        _CALLER_IDENTITY_ENVELOPE: EnvelopeDefinition(
            _CALLER_IDENTITY_ENVELOPE,
            TranscriptEntryKind.IDENTITY_CONTENT,
            EnvelopeClosure.PAIRED,
            _CALLER_IDENTITY_BRACKET_OPENING,
            _CALLER_IDENTITY_BRACKET_CLOSING,
            _CALLER_IDENTITY_XML_TAG,
            _CALLER_IDENTITY_OPENING_RE,
            _IDENTITY_FIELDS,
        ),
        _REMINDER_ENVELOPE: EnvelopeDefinition(
            _REMINDER_ENVELOPE,
            TranscriptEntryKind.REMINDER,
            EnvelopeClosure.PAIRED,
            _REMINDER_BRACKET_OPENING,
            _REMINDER_BRACKET_CLOSING,
            _REMINDER_XML_TAG,
            _REMINDER_OPENING_RE,
            _REMINDER_FIELDS,
        ),
        _ACTION_ENVELOPE: EnvelopeDefinition(
            _ACTION_ENVELOPE,
            TranscriptEntryKind.IDENTITY_CONTENT,
            EnvelopeClosure.PAIRED,
            _ACTION_BRACKET_OPENING,
            _ACTION_BRACKET_CLOSING,
            _ACTION_XML_TAG,
            None,
            _ACTION_FIELDS,
            output_only=True,
        ),
    }
)


_SCANNED_PAIRED_OPENINGS: tuple[tuple[re.Pattern[str], EnvelopeDefinition], ...] = tuple(
    (definition.opening_pattern, definition)
    for definition in ENVELOPE_REGISTRY.values()
    if definition.opening_pattern is not None
    and not definition.output_only
    and definition.closure is EnvelopeClosure.PAIRED
)
_SCANNED_AUTO_CLOSED_OPENINGS: tuple[tuple[re.Pattern[str], EnvelopeDefinition], ...] = tuple(
    (definition.opening_pattern, definition)
    for definition in ENVELOPE_REGISTRY.values()
    if definition.opening_pattern is not None
    and not definition.output_only
    and definition.closure is EnvelopeClosure.AUTO_CLOSED
)


@dataclass(frozen=True)
class TranscriptTextClassification:
    """The single structural classification for accepted or receiptless text."""

    kind: TranscriptEntryKind
    platform_label: PlatformTextLabel | None = None


@dataclass(frozen=True)
class InjectedEnvelopeCandidate:
    """One complete canonical envelope found in a native transcript entry."""

    kind: TranscriptEntryKind
    envelope_span: tuple[int, int]
    body_span: tuple[int, int]
    opening: str


@dataclass(frozen=True)
class TranscriptCutSegment:
    """One ordered user-entry gap or complete structural envelope span."""

    kind: TranscriptEntryKind | None
    span: tuple[int, int]
    body_span: tuple[int, int] | None
    text: str
    opening: str | None = None


_SECTION_SEPARATOR = "\n\n"
_EMPTY_TEXT = ""
_CHECKPOINT_BODY = (
    "Continue or validate your work if needed. Perform checkpoint housekeeping silently, then send a short "
    "user-relevant debrief without mentioning checkpoint chores. Any truly interesting memories to be created that "
    "meet our criteria? (DON'T abuse it as work log!) If everything that is expected of you is done, do not respond."
)


@dataclass(frozen=True)
class InjectedTextEnvelope:
    """A rendered platform envelope whose delimiters and body span share one owner."""

    opening: str
    closing: str
    body: str
    separator: str = _SECTION_SEPARATOR

    @property
    def rendered(self) -> str:
        """Return the complete paired envelope."""
        sections = [self.opening]
        if self.body:
            sections.append(self.body)
        sections.append(self.closing)
        return self.separator.join(sections)

    @property
    def body_span(self) -> tuple[int, int]:
        """Return the body offsets in the rendered envelope."""
        opening_prefix = len(self.opening) + len(self.separator)
        if not self.body:
            return (opening_prefix, opening_prefix)
        return (opening_prefix, opening_prefix + len(self.body))


def semantic_envelope(
    name: EnvelopeName,
    *,
    fields: Mapping[EnvelopeField, str] = _EMPTY_ENVELOPE_FIELDS,
    body: str = _EMPTY_TEXT,
) -> SemanticEnvelope:
    """Build one validated envelope from the closed semantic registry."""
    return SemanticEnvelope(definition=ENVELOPE_REGISTRY[name], fields=fields, body=body)


def _format_envelope_template(template: str, fields: Mapping[EnvelopeField, str]) -> str:
    """Render a registry-owned delimiter from typed header fields."""
    values = {field.value: value for field, value in fields.items()}
    return template.format(**values)


def envelope_bracket_opening(envelope: SemanticEnvelope) -> str:
    """Render the registry-owned opening delimiter for a semantic envelope."""
    return _format_envelope_template(envelope.definition.bracket_opening, envelope.fields)


def envelope_bracket_closing(envelope: SemanticEnvelope) -> str:
    """Render the registry-owned closing delimiter for a semantic envelope."""
    return _format_envelope_template(envelope.definition.bracket_closing, envelope.fields)


def render_bracket_envelope(envelope: SemanticEnvelope) -> str:
    """Render the human-readable codec for one semantic envelope."""
    opening = envelope_bracket_opening(envelope)
    if envelope.definition.closure is EnvelopeClosure.AUTO_CLOSED:
        return opening
    closing = envelope_bracket_closing(envelope)
    return _SECTION_SEPARATOR.join((opening, envelope.body, closing))


def render_xml_envelope(envelope: SemanticEnvelope) -> str:
    """Render the hook-boundary XML codec for one semantic envelope."""
    attributes = _XML_ATTRIBUTE_SEPARATOR.join(
        _XML_ATTRIBUTE_TEMPLATE.format(name=field.value, value=_xml_escape(value, quote=True))
        for field, value in envelope.fields.items()
    )
    tag = envelope.definition.xml_tag
    if envelope.definition.closure is EnvelopeClosure.AUTO_CLOSED:
        return _XML_AUTO_CLOSED_TEMPLATE.format(tag=tag, attributes=attributes)
    return _XML_PAIRED_TEMPLATE.format(tag=tag, attributes=attributes, body=_xml_escape(envelope.body))


def _platform_semantic_envelope(label: PlatformTextLabel, body: str) -> SemanticEnvelope:
    """Translate the legacy platform label surface onto the semantic registry."""
    return semantic_envelope(_PLATFORM_LABEL_ENVELOPES[label], body=body.strip())


def platform_control_envelope(label: PlatformTextLabel, body: str = _EMPTY_TEXT) -> InjectedTextEnvelope:
    """Compose the paired control envelope for one closed platform label."""
    semantic = _platform_semantic_envelope(label, body)
    return InjectedTextEnvelope(
        opening=envelope_bracket_opening(semantic),
        closing=envelope_bracket_closing(semantic),
        body=semantic.body,
    )


def platform_control_text(label: PlatformTextLabel, body: str = _EMPTY_TEXT) -> str:
    """Render a paired platform-control envelope for injection."""
    return render_bracket_envelope(_platform_semantic_envelope(label, body))


def identity_content_envelope(
    header: str,
    body: str,
) -> InjectedTextEnvelope:
    """Compose a paired identity envelope from its resolved opening header."""
    if not (_CALLER_IDENTITY_OPENING_RE.fullmatch(header) or _PEER_OPENING_RE.fullmatch(header)):
        raise ValueError("Identity headers must use the closed identity vocabulary")
    return InjectedTextEnvelope(
        opening=header,
        closing=f"[/{header.removeprefix('[')}",
        body=body,
    )


def reminder_envelope(opening: str, body: str) -> InjectedTextEnvelope:
    """Compose one reminder record from its durable opening facts."""
    if not _REMINDER_OPENING_RE.fullmatch(opening):
        raise ValueError("Reminder headers must use the canonical reminder delimiter")
    header_parts = opening.removeprefix("[Reminder ").removesuffix("]").split(" ", maxsplit=2)
    if len(header_parts) < 2:
        raise ValueError("Reminder headers must carry a slug and occurrence key")
    slug, occurrence_key = header_parts[:2]
    return InjectedTextEnvelope(
        opening=opening,
        closing=f"[/Reminder {slug} {occurrence_key}]",
        body=body,
        separator="\n",
    )


def scan_injected_envelopes(text: str) -> list[InjectedEnvelopeCandidate]:
    """Return non-overlapping complete envelopes with their body boundaries."""
    auto_closed = _auto_closed_entry_candidate(text)
    if auto_closed is not None:
        return [auto_closed]
    candidates: list[InjectedEnvelopeCandidate] = []
    occupied_until = 0
    for opening_match, definition in _envelope_openings(text):
        opening = opening_match.group(0)
        separator = _separator_after_opening(text, opening_match.end())
        if separator is None:
            continue
        closing = _closing_for_opening(opening)
        body_start = opening_match.end() + len(separator)
        closing_start = text.find(closing, body_start)
        if closing_start < 0 or opening_match.start() < occupied_until:
            continue
        body_end = closing_start
        if closing_start > body_start and text.startswith(separator, closing_start - len(separator)):
            body_end -= len(separator)
        envelope_end = closing_start + len(closing)
        candidates.append(
            InjectedEnvelopeCandidate(
                kind=definition.kind,
                envelope_span=(opening_match.start(), envelope_end),
                body_span=(body_start, body_end),
                opening=opening,
            )
        )
        occupied_until = envelope_end
    return candidates


def _auto_closed_entry_candidate(text: str) -> InjectedEnvelopeCandidate | None:
    """Recognize an auto-closed envelope only when it is the entire entry."""
    stripped = text.strip()
    for pattern, definition in _SCANNED_AUTO_CLOSED_OPENINGS:
        if pattern.fullmatch(stripped) is None:
            continue
        end = len(text)
        return InjectedEnvelopeCandidate(
            kind=definition.kind,
            envelope_span=(0, end),
            body_span=(end, end),
            opening=stripped,
        )
    return None


def cut_transcript_entry(text: str, *, is_user_entry: bool) -> tuple[TranscriptCutSegment, ...]:
    """Cut an entry into ordered opaque envelopes and ordinary user-text gaps."""
    if not is_user_entry:
        return (TranscriptCutSegment(None, (0, len(text)), None, text),)
    segments: list[TranscriptCutSegment] = []
    cursor = 0
    for envelope in scan_injected_envelopes(text):
        envelope_start, envelope_end = envelope.envelope_span
        if cursor < envelope_start:
            segments.append(
                TranscriptCutSegment(
                    TranscriptEntryKind.ORDINARY,
                    (cursor, envelope_start),
                    None,
                    text[cursor:envelope_start],
                )
            )
        segments.append(
            TranscriptCutSegment(
                envelope.kind,
                envelope.envelope_span,
                envelope.body_span,
                text[envelope_start:envelope_end],
                envelope.opening,
            )
        )
        cursor = envelope_end
    if cursor < len(text):
        segments.append(
            TranscriptCutSegment(
                TranscriptEntryKind.ORDINARY,
                (cursor, len(text)),
                None,
                text[cursor:],
            )
        )
    return tuple(segments)


UNSEEN_ENTRY_KINDS: frozenset[TranscriptEntryKind] = frozenset(
    {TranscriptEntryKind.PLATFORM_CONTROL, TranscriptEntryKind.REMINDER}
)
"""Kinds that carry nothing a person sent: platform text addressed to the agent's own loop."""


def visible_user_segments(text: str) -> tuple[tuple[TranscriptEntryKind, str], ...]:
    """The parts of a user entry a person sees, in order, with their kind.

    THE single owner of that question. Every surface answering it — the
    conversation projector, user-turn reflection, the session-row preview —
    reads this rather than cutting and filtering for itself. A surface needing
    a distinction this does not draw extends it here; a second recognizer
    beside it is how the kinds drift apart.

    An envelope contributes its body, never its framing, so envelope framing
    cannot reach human-facing copy. A kind in ``UNSEEN_ENTRY_KINDS``
    contributes nothing at all.

    Requires the entry as written. Recognition is by declared closure, so a
    truncated entry degrades to one ordinary span carrying its own framing —
    which is why a caller passes the accepted turn and never a stored preview
    of it. Recognizing on an opening alone would be the cheaper rule and the
    wrong one: a person may type a bracket, and text outside a complete
    envelope is that person's own words.
    """
    visible: list[tuple[TranscriptEntryKind, str]] = []
    for segment in cut_transcript_entry(text, is_user_entry=True):
        kind = segment.kind or TranscriptEntryKind.ORDINARY
        if kind in UNSEEN_ENTRY_KINDS:
            continue
        body = text[segment.body_span[0] : segment.body_span[1]] if segment.body_span else segment.text
        stripped = body.strip()
        if stripped:
            visible.append((kind, stripped))
    return tuple(visible)


INPUT_PREVIEW_LIMIT = 200
"""Stored length of a visible-span preview — a row of session list, not a document."""


def visible_input_update(text: str) -> dict[str, str]:
    """The ``last_input`` field update for one accepted turn.

    Empty when the turn carries nothing a person sent — a wake, a
    notification, a checkpoint — so a control turn leaves the previously
    stored visible input standing instead of blanking the session row.
    Acceptance writers merge this into their update rather than assigning
    the field directly.
    """
    preview = visible_input_preview(text)
    return {"last_input": preview} if preview else {}


def visible_input_preview(text: str) -> str | None:
    """The stored, display-ready form of what a person sent in one turn.

    Written at acceptance, while the turn's envelopes are still complete, and
    read straight onto the session row. ``None`` when the turn carries nothing
    a person sent — a notification, a wake, a reminder — so the row shows no
    input rather than showing framing.
    """
    joined = _SECTION_SEPARATOR.join(body for _, body in visible_user_segments(text))
    return joined[:INPUT_PREVIEW_LIMIT] or None


def _envelope_openings(text: str) -> list[tuple[re.Match[str], EnvelopeDefinition]]:
    """Return canonical opening markers with their definitions in source order."""
    return sorted(
        [(match, definition) for pattern, definition in _SCANNED_PAIRED_OPENINGS for match in pattern.finditer(text)],
        key=lambda item: item[0].start(),
    )


def _closing_for_opening(opening: str) -> str:
    """Derive the canonical close for a recognized opening delimiter."""
    if opening.startswith("[Peer "):
        return "[/TeleClaude - Peer]"
    if opening.startswith("[Reminder "):
        header_parts = opening.removeprefix("[Reminder ").removesuffix("]").split(" ", maxsplit=2)
        if len(header_parts) < 2:
            raise ValueError("Reminder headers must carry a slug and occurrence key")
        return f"[/Reminder {header_parts[0]} {header_parts[1]}]"
    return f"[/{opening.removeprefix('[')}"


def _separator_after_opening(text: str, opening_end: int) -> str | None:
    """Return the canonical body separator used by a recognized envelope."""
    if text.startswith(_SECTION_SEPARATOR, opening_end):
        return _SECTION_SEPARATOR
    if text.startswith("\n", opening_end):
        return "\n"
    return None


def checkpoint_text(body: str = _CHECKPOINT_BODY) -> str:
    """Render the canonical paired checkpoint-control envelope."""
    return platform_control_text(PlatformTextLabel.CHECKPOINT, body)


def is_checkpoint_text(text: str) -> bool:
    """Return whether text begins with the closed checkpoint control opener."""
    return classify_transcript_text(text).platform_label is PlatformTextLabel.CHECKPOINT


def _platform_control_label(text: str) -> PlatformTextLabel | None:
    stripped = text.lstrip()
    for label in PlatformTextLabel:
        if stripped.startswith(platform_control_envelope(label).opening):
            return label
    return None


def _is_auto_closed_platform_control(text: str) -> bool:
    """Recognize an unlabeled control marker occupying the entire entry."""
    stripped = text.strip()
    return any(
        definition.kind is TranscriptEntryKind.PLATFORM_CONTROL and pattern.fullmatch(stripped) is not None
        for pattern, definition in _SCANNED_AUTO_CLOSED_OPENINGS
    )


def classify_transcript_text(
    text: str,
    *,
    accepted_kind: TranscriptEntryKind | None = None,
) -> TranscriptTextClassification:
    """Classify text once, trusting accepted provenance whenever it exists."""
    if accepted_kind is not None:
        return TranscriptTextClassification(
            kind=accepted_kind,
            platform_label=_platform_control_label(text)
            if accepted_kind is TranscriptEntryKind.PLATFORM_CONTROL
            else None,
        )
    label = _platform_control_label(text)
    if label is not None:
        return TranscriptTextClassification(TranscriptEntryKind.PLATFORM_CONTROL, label)
    if _is_auto_closed_platform_control(text):
        return TranscriptTextClassification(TranscriptEntryKind.PLATFORM_CONTROL)
    return TranscriptTextClassification(TranscriptEntryKind.ORDINARY)


__all__ = [
    "INPUT_PREVIEW_LIMIT",
    "UNSEEN_ENTRY_KINDS",
    "InjectedEnvelopeCandidate",
    "InjectedTextEnvelope",
    "InjectedTextSourceFeature",
    "PlatformTextLabel",
    "TranscriptCutSegment",
    "TranscriptEntryKind",
    "TranscriptTextClassification",
    "checkpoint_text",
    "classify_transcript_text",
    "cut_transcript_entry",
    "identity_content_envelope",
    "is_checkpoint_text",
    "platform_control_envelope",
    "platform_control_text",
    "reminder_envelope",
    "scan_injected_envelopes",
    "visible_input_preview",
    "visible_input_update",
    "visible_user_segments",
]
