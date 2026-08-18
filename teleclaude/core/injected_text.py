"""Typed vocabulary and paired envelopes for platform-injected session text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class TranscriptEntryKind(StrEnum):
    """The durable classification assigned to each accepted transcript entry."""

    PLATFORM_CONTROL = "platform_control"
    IDENTITY_CONTENT = "identity_content"
    REMINDER = "reminder"
    THIRD_PARTY_RUNTIME_ARTIFACT = "third_party_runtime_artifact"
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
    INPUT_REQUEST = "Input Request"


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


_TELECLAUDE_NAME = "TeleClaude"
_OPENING_TEMPLATE = "[{platform} {label}]"
_CLOSING_TEMPLATE = "[/{platform} {label}]"
_SECTION_SEPARATOR = "\n\n"
_EMPTY_TEXT = ""
_RESPONSE_BOUNDARY_FOOTER = (
    "[Mandatory response boundary]\n"
    "After preparing your response, arm the prescribed halt-to-respond reminder as your final tool action. "
    "Then emit only that response and yield.\n"
    "[/Mandatory response boundary]"
)
_CHECKPOINT_BODY = (
    "Continue or validate your work if needed. Perform checkpoint housekeeping silently, then send a short "
    "user-relevant debrief without mentioning checkpoint chores. Any truly interesting memories to be created that "
    "meet our criteria? (DON'T abuse it as work log!) If everything that is expected of you is done, do not respond."
)
_HOOK_FEEDBACK_PREFIXES = ("Stop hook feedback:", "PreToolUse hook feedback:")
_INTERNAL_WRAPPER_RE = re.compile(
    r"^\s*<(task-notification|system-reminder)\b[^>]*>.*</\1>\s*$",
    re.DOTALL,
)
_TEAMMATE_MESSAGE_BLOCK_RE = re.compile(
    r"<teammate-message\b[^>]*>.*?</teammate-message\s*>",
    re.DOTALL,
)
_XML_STYLE_PREFIX_RE = re.compile(r"^\s*</?[A-Za-z_][\w:.-]*(?:\s[^>]*)?>", re.DOTALL)
_AGENTS_MD_INSTRUCTIONS_RE = re.compile(r"^# AGENTS\.md instructions(?: for .*)?[ \t]*(?:\r?\n|$)")
_REMINDER_OPENING_RE = re.compile(r"\[Reminder [^\]\n]+\]")
_CONTROL_OPENING_RE = re.compile(r"\[TeleClaude (?:Checkpoint|Notification|Input Request)\]")
_PEER_OPENING_RE = re.compile(r"\[Peer \([^\]\n]+\)\]")
_CALLER_IDENTITY_OPENING_RE = re.compile(
    r"\[(?:Orchestrator|Integrator|System|Worker|Tasker|Job Runner|Agent)(?: - [^\]\n]+)? \([^\]\n]+\) on [^\]\n]+\]"
)


@dataclass(frozen=True)
class InjectedTextEnvelope:
    """A rendered platform envelope whose delimiters and body span share one owner."""

    opening: str
    closing: str
    body: str
    footer: str | None = None
    separator: str = _SECTION_SEPARATOR

    @property
    def rendered(self) -> str:
        """Return the complete paired envelope."""
        sections = [self.opening]
        if self.body:
            sections.append(self.body)
        sections.append(self.closing)
        if self.footer:
            sections.append(self.footer)
        return self.separator.join(sections)

    @property
    def body_span(self) -> tuple[int, int]:
        """Return the body offsets in the rendered envelope."""
        opening_prefix = len(self.opening) + len(self.separator)
        if not self.body:
            return (opening_prefix, opening_prefix)
        return (opening_prefix, opening_prefix + len(self.body))


def platform_control_envelope(label: PlatformTextLabel, body: str = _EMPTY_TEXT) -> InjectedTextEnvelope:
    """Compose the paired control envelope for one closed platform label."""
    return InjectedTextEnvelope(
        opening=_OPENING_TEMPLATE.format(platform=_TELECLAUDE_NAME, label=label.value),
        closing=_CLOSING_TEMPLATE.format(platform=_TELECLAUDE_NAME, label=label.value),
        body=body.strip(),
    )


def platform_control_text(label: PlatformTextLabel, body: str = _EMPTY_TEXT) -> str:
    """Render a paired platform-control envelope for injection."""
    return platform_control_envelope(label, body).rendered


def identity_content_envelope(
    header: str,
    body: str,
    *,
    footer: str | None = None,
) -> InjectedTextEnvelope:
    """Compose a paired identity envelope from its resolved opening header."""
    if not (_CALLER_IDENTITY_OPENING_RE.fullmatch(header) or _PEER_OPENING_RE.fullmatch(header)):
        raise ValueError("Identity headers must use the closed identity vocabulary")
    if footer not in {None, _RESPONSE_BOUNDARY_FOOTER}:
        raise ValueError("Identity envelope footers must use the canonical response boundary")
    return InjectedTextEnvelope(
        opening=header,
        closing=f"[/{header.removeprefix('[')}",
        body=body,
        footer=footer,
    )


def peer_content_envelope(header: str, body: str, *, footer: str | None = None) -> InjectedTextEnvelope:
    """Compose one peer segment using its stable peer closing delimiter."""
    if not _PEER_OPENING_RE.fullmatch(header):
        raise ValueError("Peer headers must use the canonical peer delimiter")
    return InjectedTextEnvelope(opening=header, closing="[/TeleClaude - Peer]", body=body, footer=footer)


def response_boundary_footer() -> str:
    """Return the one platform-owned footer appended to response-bearing identities."""
    return _RESPONSE_BOUNDARY_FOOTER


def reminder_envelope(opening: str, body: str) -> InjectedTextEnvelope:
    """Compose one reminder record from its durable opening facts."""
    if not _REMINDER_OPENING_RE.fullmatch(opening):
        raise ValueError("Reminder headers must use the canonical reminder delimiter")
    slug = opening.removeprefix("[Reminder ").split(" ", maxsplit=1)[0]
    return InjectedTextEnvelope(
        opening=opening,
        closing=f"[/Reminder {slug}]",
        body=body,
        separator="\n",
    )


def scan_injected_envelopes(text: str) -> list[InjectedEnvelopeCandidate]:
    """Return non-overlapping complete envelopes with their body boundaries."""
    candidates: list[InjectedEnvelopeCandidate] = []
    occupied_until = 0
    openings = _envelope_openings(text)
    for opening_match in openings:
        opening = opening_match.group(0)
        separator = _separator_after_opening(text, opening_match.end())
        if separator is None:
            continue
        closing = _closing_for_opening(opening)
        body_start = opening_match.end() + len(separator)
        closing_start = text.find(closing, body_start)
        if closing_start < 0 or opening_match.start() < occupied_until:
            continue
        if any(body_start <= other.start() < closing_start for other in openings):
            continue
        envelope_end = closing_start + len(closing)
        footer_prefix = _SECTION_SEPARATOR + _RESPONSE_BOUNDARY_FOOTER
        if text.startswith(footer_prefix, envelope_end):
            envelope_end += len(footer_prefix)
        candidates.append(
            InjectedEnvelopeCandidate(
                kind=_envelope_kind(opening),
                envelope_span=(opening_match.start(), envelope_end),
                body_span=(body_start, closing_start),
                opening=opening,
            )
        )
        occupied_until = envelope_end
    return candidates


def _envelope_openings(text: str) -> list[re.Match[str]]:
    """Return canonical opening markers in source order."""
    return sorted(
        [
            *(_CONTROL_OPENING_RE.finditer(text)),
            *(_PEER_OPENING_RE.finditer(text)),
            *(_CALLER_IDENTITY_OPENING_RE.finditer(text)),
            *(_REMINDER_OPENING_RE.finditer(text)),
        ],
        key=lambda match: match.start(),
    )


def _closing_for_opening(opening: str) -> str:
    """Derive the canonical close for a recognized opening delimiter."""
    if opening.startswith("[Peer "):
        return "[/TeleClaude - Peer]"
    if opening.startswith("[Reminder "):
        slug = opening.removeprefix("[Reminder ").split(" ", maxsplit=1)[0]
        return f"[/Reminder {slug}]"
    return f"[/{opening.removeprefix('[')}"


def _separator_after_opening(text: str, opening_end: int) -> str | None:
    """Return the canonical body separator used by a recognized envelope."""
    if text.startswith(_SECTION_SEPARATOR, opening_end):
        return _SECTION_SEPARATOR
    if text.startswith("\n", opening_end):
        return "\n"
    return None


def _envelope_kind(opening: str) -> TranscriptEntryKind:
    """Resolve the closed kind declared by one canonical envelope opener."""
    if opening.startswith("[Reminder "):
        return TranscriptEntryKind.REMINDER
    if any(opening == platform_control_envelope(label).opening for label in PlatformTextLabel):
        return TranscriptEntryKind.PLATFORM_CONTROL
    return TranscriptEntryKind.IDENTITY_CONTENT


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


def _is_third_party_runtime_artifact(text: str) -> bool:
    stripped = text.lstrip()
    if stripped.startswith(_HOOK_FEEDBACK_PREFIXES):
        return True
    if _XML_STYLE_PREFIX_RE.match(stripped):
        return True
    if _INTERNAL_WRAPPER_RE.match(text):
        return True
    if _TEAMMATE_MESSAGE_BLOCK_RE.search(text):
        return True
    return bool(_AGENTS_MD_INSTRUCTIONS_RE.match(stripped))


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
    if _is_third_party_runtime_artifact(text):
        return TranscriptTextClassification(TranscriptEntryKind.THIRD_PARTY_RUNTIME_ARTIFACT)
    return TranscriptTextClassification(TranscriptEntryKind.ORDINARY)


__all__ = [
    "InjectedEnvelopeCandidate",
    "InjectedTextEnvelope",
    "InjectedTextSourceFeature",
    "PlatformTextLabel",
    "TranscriptEntryKind",
    "TranscriptTextClassification",
    "checkpoint_text",
    "classify_transcript_text",
    "identity_content_envelope",
    "is_checkpoint_text",
    "peer_content_envelope",
    "platform_control_envelope",
    "platform_control_text",
    "reminder_envelope",
    "response_boundary_footer",
    "scan_injected_envelopes",
]
