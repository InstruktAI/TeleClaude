"""Typed vocabulary and paired envelopes for platform-injected session text."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import assert_never

from teleclaude.agent_registry import AGENT_REGISTRY, AgentName
from teleclaude.core.dates import format_utc_datetime


class TranscriptEntryKind(StrEnum):
    """The durable classification assigned to each accepted transcript entry."""

    PLATFORM_CONTROL = "platform_control"
    IDENTITY_CONTENT = "identity_content"
    REMINDER = "reminder"
    COMMAND_LOADER = "command_loader"
    ORDINARY = "ordinary"


class InjectedTextSourceFeature(StrEnum):
    """Closed producer vocabulary persisted with every accepted text occurrence."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    GITHUB = "github"
    VOICE = "voice"
    RELAY = "relay"
    CALLER_SEND = "caller_send"
    PEER_BUNDLE = "peer_bundle"
    LISTENER = "listener"
    AGENT_RESTART = "agent_restart"
    AGENT_HANDOFF = "agent_handoff"
    REMINDER = "reminder"
    PROCEDURE_ACTIVATION = "procedure_activation"


class InjectedInputAuthority(StrEnum):
    """Whether accepted text is conversation or controls the interface."""

    CONVERSATION = "conversation"
    INTERFACE = "interface"


_FORMAT_CATEGORY = "Cf"
_TRAILING_BACKSLASH = "\\"


def authority_for_source_feature(source: InjectedTextSourceFeature) -> InjectedInputAuthority:
    """Classify accepted text by its recorded producer, never by its content."""
    match source:
        case (
            InjectedTextSourceFeature.TELEGRAM
            | InjectedTextSourceFeature.DISCORD
            | InjectedTextSourceFeature.WHATSAPP
            | InjectedTextSourceFeature.GITHUB
            | InjectedTextSourceFeature.VOICE
            | InjectedTextSourceFeature.RELAY
        ):
            return InjectedInputAuthority.CONVERSATION
        case (
            InjectedTextSourceFeature.CALLER_SEND
            | InjectedTextSourceFeature.PEER_BUNDLE
            | InjectedTextSourceFeature.LISTENER
            | InjectedTextSourceFeature.AGENT_RESTART
            | InjectedTextSourceFeature.AGENT_HANDOFF
            | InjectedTextSourceFeature.REMINDER
            | InjectedTextSourceFeature.PROCEDURE_ACTIVATION
        ):
            return InjectedInputAuthority.INTERFACE
        case _ as unreachable:
            assert_never(unreachable)


def construct_delivered_text(text: str, authority: InjectedInputAuthority, agent: AgentName) -> str:
    """Prefix conversation text when its effective first character controls the composer."""
    if authority is not InjectedInputAuthority.CONVERSATION:
        return text
    control = AGENT_REGISTRY[agent].composer_control
    for character in text:
        if character.isspace() or unicodedata.category(character) == _FORMAT_CATEGORY:
            continue
        if character in control.control_characters:
            return f"{control.neutralizing_mark}{text}"
        break
    return text


def prepare_composer_submission(text: str, agent: AgentName) -> str:
    """Append the runtime's continuation mark after a trailing backslash."""
    mark = AGENT_REGISTRY[agent].composer_control.trailing_continuation_mark
    if mark is None or not text.rstrip().endswith(_TRAILING_BACKSLASH):
        return text
    return text + mark


def recognize_delivered_text(text: str, agent: AgentName) -> str:
    """Remove one delivery-added mark only when construction reproduces the native text."""
    mark = AGENT_REGISTRY[agent].composer_control.neutralizing_mark
    if not text.startswith(mark):
        return text
    unmarked = text[len(mark) :]
    if construct_delivered_text(unmarked, InjectedInputAuthority.CONVERSATION, agent) == text:
        return unmarked
    return text


class PlatformTextLabel(StrEnum):
    """Closed labels used by platform-authored control envelopes."""

    CHECKPOINT = "Checkpoint"
    NOTIFICATION = "Notification"
    RESTART_CONTINUATION = "Restart Continuation"
    HANDOFF = "Handoff"


class EnvelopeName(StrEnum):
    """Closed semantic envelope vocabulary shared by every renderer."""

    CHECKPOINT = "checkpoint"
    NOTIFICATION = "notification"
    WAKE = "wake"
    RESTART_CONTINUATION = "restart_continuation"
    HANDOFF = "handoff"
    PEER = "peer"
    CALLER_IDENTITY = "caller_identity"
    REMINDER = "reminder"


class EnvelopeClosure(StrEnum):
    """The one declared closure discipline for an envelope definition."""

    PAIRED = "paired"
    AUTO_CLOSED = "auto_closed"


class EnvelopeField(StrEnum):
    """Structured values consumed by the closed envelope vocabulary."""

    ARMED_AT = "armed_at"
    AUTHOR_TOKEN = "author_token"
    CATEGORY = "category"
    COMPUTER = "computer"
    DUE_AT = "due_at"
    INTERVAL = "interval"
    NEXT_FIRE_AT = "next_fire_at"
    OCCURRED_AT = "occurred_at"
    OCCURRENCE_KEY = "occurrence_key"
    ROLE = "role"
    SESSION_ID = "session_id"
    SLUG = "slug"


class MachineRoleLabel(StrEnum):
    """Identity-envelope labels for callers that carry no role; a role-carrying caller is labelled by its role name."""

    SYSTEM = "System"
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
_HANDOFF_ENVELOPE = EnvelopeName.HANDOFF
_PEER_ENVELOPE = EnvelopeName.PEER
_CALLER_IDENTITY_ENVELOPE = EnvelopeName.CALLER_IDENTITY
_REMINDER_ENVELOPE = EnvelopeName.REMINDER
_EMPTY_BRACKET_CLOSING = ""
_CHECKPOINT_BRACKET_OPENING = "[TeleClaude Checkpoint]"
_NOTIFICATION_BRACKET_OPENING = "[TeleClaude Notification]"
_WAKE_BRACKET_OPENING = "[TeleClaude Wake]"
_WAKE_BRACKET_OPENING_WITH_OCCURRENCE = "[TeleClaude Wake {occurrence_key}]"
_RESTART_CONTINUATION_BRACKET_OPENING = "[TeleClaude Restart Continuation]"
_HANDOFF_BRACKET_OPENING = "[TeleClaude Handoff]"
_PEER_BRACKET_OPENING = "[Peer ({session_id} · {author_token} · {occurred_at})]"
_CALLER_IDENTITY_BRACKET_OPENING = "[{role}{category} ({session_id}) on {computer} · {occurred_at}]"
_CALLER_IDENTITY_KEYED_SUFFIX = " · {occurrence_key}]"
_REMINDER_BRACKET_OPENING = "[Reminder {slug} {occurrence_key}]"
_CHECKPOINT_BRACKET_CLOSING = "[/TeleClaude Checkpoint]"
_NOTIFICATION_BRACKET_CLOSING = "[/TeleClaude Notification]"
_RESTART_CONTINUATION_BRACKET_CLOSING = "[/TeleClaude Restart Continuation]"
_HANDOFF_BRACKET_CLOSING = "[/TeleClaude Handoff]"
_PEER_BRACKET_CLOSING = "[/TeleClaude - Peer]"
_CALLER_IDENTITY_BRACKET_CLOSING = "[/{role}{category} ({session_id}) on {computer} · {occurred_at}]"
_REMINDER_BRACKET_CLOSING = "[/Reminder {slug} {occurrence_key}]"
_CHECKPOINT_XML_TAG = "teleclaude-checkpoint"
_NOTIFICATION_XML_TAG = "teleclaude-notification"
_WAKE_XML_TAG = "teleclaude-wake"
_RESTART_CONTINUATION_XML_TAG = "teleclaude-restart-continuation"
_HANDOFF_XML_TAG = "teleclaude-handoff"
_PEER_XML_TAG = "teleclaude-peer"
_CALLER_IDENTITY_XML_TAG = "teleclaude-caller"
_REMINDER_XML_TAG = "teleclaude-reminder"
_CHECKPOINT_OPENING_RE = re.compile(re.escape(_CHECKPOINT_BRACKET_OPENING))
_NOTIFICATION_OPENING_RE = re.compile(re.escape(_NOTIFICATION_BRACKET_OPENING))
_WAKE_OPENING_RE = re.compile(r"\[TeleClaude Wake(?: (?P<occurrence_key>[^\]\n]+))?\]")
_RESTART_CONTINUATION_OPENING_RE = re.compile(re.escape(_RESTART_CONTINUATION_BRACKET_OPENING))
_HANDOFF_OPENING_RE = re.compile(re.escape(_HANDOFF_BRACKET_OPENING))
_PEER_OPENING_RE = re.compile(r"\[Peer \([^\]\n]+ · [^\]\n]+ · [^\]\n]+\)\]")
_CALLER_IDENTITY_OPENING_RE = re.compile(r"\[[^\[\]\n()]+ \([^\]\n]+\) on [^\]\n]+(?: · [^\]\n]+)?\]")
_CALLER_OCCURRENCE_KEY_RE = re.compile(r" · (?P<occurrence_key>[0-9a-f]{32})\]$")
_REMINDER_OPENING_RE = re.compile(r"\[Reminder [^\]\n]+\]")
_IDENTITY_FIELDS = frozenset(
    {EnvelopeField.ROLE, EnvelopeField.SESSION_ID, EnvelopeField.COMPUTER, EnvelopeField.OCCURRED_AT}
)
_PEER_FIELDS = frozenset({EnvelopeField.SESSION_ID, EnvelopeField.AUTHOR_TOKEN, EnvelopeField.OCCURRED_AT})
_REMINDER_FIELDS = frozenset({EnvelopeField.SLUG, EnvelopeField.OCCURRENCE_KEY})
_EMPTY_ENVELOPE_FIELDS: Mapping[EnvelopeField, str] = MappingProxyType({})
_PLATFORM_LABEL_ENVELOPES: Mapping[PlatformTextLabel, EnvelopeName] = MappingProxyType(
    {
        PlatformTextLabel.CHECKPOINT: EnvelopeName.CHECKPOINT,
        PlatformTextLabel.NOTIFICATION: EnvelopeName.NOTIFICATION,
        PlatformTextLabel.RESTART_CONTINUATION: EnvelopeName.RESTART_CONTINUATION,
        PlatformTextLabel.HANDOFF: EnvelopeName.HANDOFF,
    }
)
_XML_ATTRIBUTE_TEMPLATE = ' {name}="{value}"'
_XML_PAIRED_TEMPLATE = "<{tag}{attributes}>{body}</{tag}>"
_XML_AUTO_CLOSED_TEMPLATE = "<{tag}{attributes} />"
_XML_ATTRIBUTE_SEPARATOR = ""
_XML_OPENING_TEMPLATE = "<{tag}>"
_XML_CLOSING_TEMPLATE = "</{tag}>"

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
        _HANDOFF_ENVELOPE: EnvelopeDefinition(
            _HANDOFF_ENVELOPE,
            TranscriptEntryKind.PLATFORM_CONTROL,
            EnvelopeClosure.PAIRED,
            _HANDOFF_BRACKET_OPENING,
            _HANDOFF_BRACKET_CLOSING,
            _HANDOFF_XML_TAG,
            _HANDOFF_OPENING_RE,
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
    }
)


_SCANNED_PAIRED_OPENINGS: tuple[tuple[re.Pattern[str], EnvelopeDefinition], ...] = tuple(
    (definition.opening_pattern, definition)
    for definition in ENVELOPE_REGISTRY.values()
    if definition.opening_pattern is not None and definition.closure is EnvelopeClosure.PAIRED
)
_SCANNED_AUTO_CLOSED_OPENINGS: tuple[tuple[re.Pattern[str], EnvelopeDefinition], ...] = tuple(
    (definition.opening_pattern, definition)
    for definition in ENVELOPE_REGISTRY.values()
    if definition.opening_pattern is not None and definition.closure is EnvelopeClosure.AUTO_CLOSED
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
_COMMAND_LOADER_MARKER_PREFIX = "TELECLAUDE COMMAND: "
_COMMAND_LOADER_ARGUMENT_PREFIX = " "
_COMMAND_LOADER_READ_PREFIX = "Read "
_COMMAND_LOADER_READ_SUFFIX = " verbatim and follow it exactly as the active instruction set for this session."
_COMMAND_LOADER_INPUTS_HEADING = "Treat the following as provided inputs to that instruction set:"
_COMMAND_LOADER_INPUTS_SEPARATOR = "\n"
_REFERENCE_LOADER_INPUTS_HEADING = "## Provided inputs"
_REFERENCE_LOADER_ENTRY_FACTS_HEADING = "## Entry facts"
_REFERENCE_LOADER_ADDITIONAL_CONTEXT_HEADING = "## Additional context"
_REFERENCE_LOADER_READ_INSTRUCTION = (
    "Load your assigned procedure's instructions with `telec docs get {command} --closure`, "
    "then follow the returned procedure as this assignment."
)
_REFERENCE_LOADER_ARGUMENTS_LABEL = "$ARGUMENTS (the raw argument text)"
_REFERENCE_LOADER_INPUT_LINE = "- {name}: {value}"
_REFERENCE_LOADER_FACT_LINE = "- {name}: {value}"
_REFERENCE_LOADER_RE = re.compile(
    r"\ATELECLAUDE COMMAND: [^\r\n]+\r?\n\r?\n"
    r"[\s\S]*\r?\n\r?\nLoad your assigned procedure's instructions with `telec docs get [^\r\n]+ --closure`, "
    r"then follow the returned procedure as this assignment\.\Z"
)
_HISTORICAL_DISPATCH_DOOR_PREFIX = "DISPATCH DOOR: "
_COMMAND_LOADER_RE = re.compile(
    r"\A"
    + re.escape(_COMMAND_LOADER_MARKER_PREFIX)
    + r"[^\r\n]+\r?\n\r?\n"
    # Transcripts written before the dispatch door retired carry its line.
    + r"(?:"
    + re.escape(_HISTORICAL_DISPATCH_DOOR_PREFIX)
    + r"[^\r\n]+\r?\n\r?\n)?"
    + re.escape(_COMMAND_LOADER_READ_PREFIX)
    + r"[^\r\n]+"
    + re.escape(_COMMAND_LOADER_READ_SUFFIX)
    + r"\r?\n\r?\n"
    + re.escape(_COMMAND_LOADER_INPUTS_HEADING)
    + r"\r?\n[\s\S]*\Z"
)
_CHECKPOINT_BODY = (
    "Continue or validate your work if needed. Perform checkpoint housekeeping silently, then send a short "
    "user-relevant debrief without mentioning checkpoint chores. If everything that is expected of you is done, do not respond."
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


def envelope_moment(value: datetime) -> str:
    """Render one moment for a control-envelope field: UTC, second precision."""
    return format_utc_datetime(value)


def occurrence_fields(occurred_at: datetime | None) -> Mapping[EnvelopeField, str]:
    """Return the occurrence field for a control envelope, or none when the moment is unknown."""
    if occurred_at is None:
        return _EMPTY_ENVELOPE_FIELDS
    return MappingProxyType({EnvelopeField.OCCURRED_AT: envelope_moment(occurred_at)})


def semantic_envelope(
    name: EnvelopeName,
    *,
    fields: Mapping[EnvelopeField, str] = _EMPTY_ENVELOPE_FIELDS,
    body: str = _EMPTY_TEXT,
) -> SemanticEnvelope:
    """Build one validated envelope from the closed semantic registry."""
    return SemanticEnvelope(definition=ENVELOPE_REGISTRY[name], fields=fields, body=body)


def wake_envelope(occurrence_key: str | None = None) -> SemanticEnvelope:
    """Build the shared content-free wake envelope, optionally correlated to one opportunity."""
    fields = {EnvelopeField.OCCURRENCE_KEY: occurrence_key} if occurrence_key is not None else _EMPTY_ENVELOPE_FIELDS
    return semantic_envelope(EnvelopeName.WAKE, fields=fields)


def _format_envelope_template(template: str, fields: Mapping[EnvelopeField, str]) -> str:
    """Render a registry-owned delimiter from typed header fields."""
    values = {field.value: value for field, value in fields.items()}
    return template.format(**values)


def envelope_bracket_opening(envelope: SemanticEnvelope) -> str:
    """Render the registry-owned opening delimiter for a semantic envelope."""
    if envelope.definition.name is EnvelopeName.WAKE and EnvelopeField.OCCURRENCE_KEY in envelope.fields:
        return _WAKE_BRACKET_OPENING_WITH_OCCURRENCE.format(
            occurrence_key=envelope.fields[EnvelopeField.OCCURRENCE_KEY]
        )
    return _format_envelope_template(envelope.definition.bracket_opening, envelope.fields)


def wake_occurrence_key(opening: str) -> str | None:
    """Read the correlation key from a canonical wake opening, when one is present."""
    match = _WAKE_OPENING_RE.fullmatch(opening)
    return match.group("occurrence_key") if match is not None else None


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
        _XML_ATTRIBUTE_TEMPLATE.format(name=field.value, value=value)  # value=_xml_escape(value, quote=True))
        for field, value in envelope.fields.items()
    )
    tag = envelope.definition.xml_tag
    if envelope.definition.closure is EnvelopeClosure.AUTO_CLOSED:
        return _XML_AUTO_CLOSED_TEMPLATE.format(tag=tag, attributes=attributes)
    return _XML_PAIRED_TEMPLATE.format(
        tag=tag, attributes=attributes, body=envelope.body.strip()
    )  # body=_xml_escape(envelope.body))


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
    occurrence_key: str | None = None,
) -> InjectedTextEnvelope:
    """Compose a paired identity envelope from its resolved opening header."""
    if not (_CALLER_IDENTITY_OPENING_RE.fullmatch(header) or _PEER_OPENING_RE.fullmatch(header)):
        raise ValueError("Identity headers must use the closed identity vocabulary")
    if occurrence_key is not None:
        if is_peer_opening(header):
            raise ValueError("Peer envelopes do not carry caller occurrence keys")
        header = header.removesuffix("]") + _CALLER_IDENTITY_KEYED_SUFFIX.format(occurrence_key=occurrence_key)
    return InjectedTextEnvelope(
        opening=header,
        closing=f"[/{header.removeprefix('[')}",
        body=body,
    )


def caller_occurrence_key(opening: str) -> str | None:
    """Return the opaque key carried by a complete caller opening, when present."""
    if not _CALLER_IDENTITY_OPENING_RE.fullmatch(opening):
        return None
    match = _CALLER_OCCURRENCE_KEY_RE.search(opening)
    return match.group("occurrence_key") if match is not None else None


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
    candidates: list[InjectedEnvelopeCandidate] = []
    occupied_until = 0
    for opening_match, definition in _envelope_openings(text):
        opening = opening_match.group(0)
        if opening_match.start() < occupied_until:
            continue
        if definition.closure is EnvelopeClosure.AUTO_CLOSED:
            candidates.append(
                InjectedEnvelopeCandidate(
                    kind=definition.kind,
                    envelope_span=(opening_match.start(), opening_match.end()),
                    body_span=(opening_match.end(), opening_match.end()),
                    opening=opening,
                )
            )
            occupied_until = opening_match.end()
            continue
        closing = _closing_for_opening(opening)
        if closing is None:
            continue
        body_start = opening_match.end()
        closing_start = text.find(closing, body_start)
        if closing_start < 0:
            continue
        envelope_end = closing_start + len(closing)
        candidates.append(
            InjectedEnvelopeCandidate(
                kind=definition.kind,
                envelope_span=(opening_match.start(), envelope_end),
                body_span=(body_start, closing_start),
                opening=opening,
            )
        )
        occupied_until = envelope_end
    return candidates


def render_reference_loader(
    command: str,
    role_framing: str | None,
    arguments: str,
    inputs: Mapping[str, str],
    entry_facts: Mapping[str, str],
    additional_context: str,
) -> str:
    """Render a short assignment loader that retrieves its instructions by reference."""
    marker_args = f"{_COMMAND_LOADER_ARGUMENT_PREFIX}{arguments}" if arguments else _EMPTY_TEXT
    parts = [f"{_COMMAND_LOADER_MARKER_PREFIX}{command}{marker_args}"]
    if role_framing:
        parts.extend([role_framing, _EMPTY_TEXT])
    parts.append(_REFERENCE_LOADER_INPUTS_HEADING)
    parts.extend(_REFERENCE_LOADER_INPUT_LINE.format(name=name, value=value) for name, value in inputs.items())
    parts.append(_REFERENCE_LOADER_INPUT_LINE.format(name=_REFERENCE_LOADER_ARGUMENTS_LABEL, value=arguments))
    if entry_facts:
        parts.extend([_EMPTY_TEXT, _REFERENCE_LOADER_ENTRY_FACTS_HEADING])
        parts.extend(_REFERENCE_LOADER_FACT_LINE.format(name=name, value=value) for name, value in entry_facts.items())
    if additional_context:
        parts.extend([_EMPTY_TEXT, _REFERENCE_LOADER_ADDITIONAL_CONTEXT_HEADING, additional_context])
    parts.extend([_EMPTY_TEXT, _REFERENCE_LOADER_READ_INSTRUCTION.format(command=command)])
    return _SECTION_SEPARATOR.join(parts)


def is_command_loader(text: str) -> bool:
    """Recognize the current reference loader and the complete historical file loader."""
    return _COMMAND_LOADER_RE.fullmatch(text) is not None or _REFERENCE_LOADER_RE.fullmatch(text) is not None


def cut_transcript_entry(text: str, *, is_user_entry: bool) -> tuple[TranscriptCutSegment, ...]:
    """Cut an entry into ordered opaque envelopes and ordinary user-text gaps.

    A complete dispatch loader is one opaque segment: its provided inputs are
    part of the platform-composed text, never envelopes or prompt input.
    """
    if not is_user_entry:
        return (TranscriptCutSegment(None, (0, len(text)), None, text),)
    if is_command_loader(text):
        return (TranscriptCutSegment(TranscriptEntryKind.COMMAND_LOADER, (0, len(text)), None, text),)
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
    {TranscriptEntryKind.PLATFORM_CONTROL, TranscriptEntryKind.REMINDER, TranscriptEntryKind.COMMAND_LOADER}
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


FIELD_LAST_INPUT = "last_input"
"""Session field holding the visible span; see the session-projection contract."""
FIELD_LAST_INPUT_WRITTEN_AT = "last_input_written_at"
"""Acceptance time coupled to the visible span, never the fingerprint clock."""
INPUT_PREVIEW_LIMIT = 200
"""Stored length of a visible-span preview — a row of session list, not a document."""


def visible_input_update(
    text: str,
    accepted_at: datetime | str | None = None,
    visible_source_text: str | None = None,
) -> dict[str, str]:
    """The ``last_input`` field update for one accepted turn.

    Empty when the turn carries nothing a person sent — a wake, a
    notification, a checkpoint — so a control turn leaves the previously
    stored visible input standing instead of blanking the session row.
    The span's own acceptance time travels with it, because the fingerprint
    clock keeps advancing on control turns and would relabel retained input.
    Acceptance writers merge this into their update rather than assigning
    the fields directly.
    """
    preview = visible_input_preview(visible_source_text if visible_source_text is not None else text)
    if not preview:
        return {}
    if isinstance(accepted_at, datetime):
        accepted_at = accepted_at.isoformat()
    written_at = accepted_at or datetime.now(UTC).isoformat()
    return {FIELD_LAST_INPUT: preview, FIELD_LAST_INPUT_WRITTEN_AT: written_at}


def visible_input_preview(text: str) -> str | None:
    """The stored, display-ready form of what a person sent in one turn.

    Written at acceptance, while the turn's envelopes are still complete, and
    read straight onto the session row. ``None`` when the turn carries nothing
    a person sent — a notification, a wake, a reminder. What ``None`` means
    for the stored row is owned by :func:`visible_input_update`: the previous
    span stays standing rather than being blanked.
    """
    joined = _SECTION_SEPARATOR.join(body for _, body in visible_user_segments(text))
    return joined[:INPUT_PREVIEW_LIMIT] or None


def _envelope_openings(text: str) -> list[tuple[re.Match[str], EnvelopeDefinition]]:
    """Return canonical opening markers with their definitions in source order."""
    return sorted(
        [
            (match, definition)
            for pattern, definition in (*_SCANNED_PAIRED_OPENINGS, *_SCANNED_AUTO_CLOSED_OPENINGS)
            for match in pattern.finditer(text)
        ],
        key=lambda item: item[0].start(),
    )


def _closing_for_opening(opening: str) -> str | None:
    """Derive the canonical close, if the opening carries its required fields."""
    if opening.startswith("[Peer "):
        return "[/TeleClaude - Peer]"
    if opening.startswith("[Reminder "):
        header_parts = opening.removeprefix("[Reminder ").removesuffix("]").split(" ", maxsplit=2)
        if len(header_parts) < 2:
            return None
        return f"[/Reminder {header_parts[0]} {header_parts[1]}]"
    return f"[/{opening.removeprefix('[')}"


def is_peer_opening(text: str) -> bool:
    """Return whether text is one current peer opening delimiter."""
    pattern = ENVELOPE_REGISTRY[EnvelopeName.PEER].opening_pattern
    return pattern is not None and pattern.fullmatch(text) is not None


def checkpoint_text(body: str = _CHECKPOINT_BODY) -> str:
    """Render the registry-owned XML checkpoint envelope at the hook boundary."""
    return render_xml_envelope(_platform_semantic_envelope(PlatformTextLabel.CHECKPOINT, body))


def is_checkpoint_text(text: str) -> bool:
    """Recognize current XML checkpoints and complete historical bracket envelopes."""
    definition = ENVELOPE_REGISTRY[EnvelopeName.CHECKPOINT]
    stripped = text.lstrip()
    xml_opening = _XML_OPENING_TEMPLATE.format(tag=definition.xml_tag)
    xml_closing = _XML_CLOSING_TEMPLATE.format(tag=definition.xml_tag)
    if stripped.startswith(xml_opening) and xml_closing in stripped[len(xml_opening) :]:
        return True
    return any(
        candidate.envelope_span[0] == len(text) - len(stripped) and candidate.opening == definition.bracket_opening
        for candidate in scan_injected_envelopes(text)
    )


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
    if is_command_loader(text):
        return TranscriptTextClassification(TranscriptEntryKind.COMMAND_LOADER)
    label = _platform_control_label(text)
    if label is not None:
        return TranscriptTextClassification(TranscriptEntryKind.PLATFORM_CONTROL, label)
    if _is_auto_closed_platform_control(text):
        return TranscriptTextClassification(TranscriptEntryKind.PLATFORM_CONTROL)
    return TranscriptTextClassification(TranscriptEntryKind.ORDINARY)


__all__ = [
    "FIELD_LAST_INPUT",
    "FIELD_LAST_INPUT_WRITTEN_AT",
    "INPUT_PREVIEW_LIMIT",
    "UNSEEN_ENTRY_KINDS",
    "InjectedEnvelopeCandidate",
    "InjectedTextEnvelope",
    "InjectedTextSourceFeature",
    "PlatformTextLabel",
    "TranscriptCutSegment",
    "TranscriptEntryKind",
    "TranscriptTextClassification",
    "caller_occurrence_key",
    "checkpoint_text",
    "classify_transcript_text",
    "cut_transcript_entry",
    "identity_content_envelope",
    "is_checkpoint_text",
    "is_peer_opening",
    "platform_control_envelope",
    "platform_control_text",
    "reminder_envelope",
    "render_reference_loader",
    "scan_injected_envelopes",
    "visible_input_preview",
    "visible_input_update",
    "visible_user_segments",
    "wake_envelope",
    "wake_occurrence_key",
]
