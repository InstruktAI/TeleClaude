"""Presentation decisions derived from the canonical transcript classification."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from teleclaude.core.conversation_messages import (
    MachineRoleLabel,
    is_conversation_bridge_message,
)
from teleclaude.core.injected_text import (
    TranscriptEntryKind,
    TranscriptTextClassification,
    classify_transcript_text,
)

_PEER_BRIDGE_LABEL = "Peer"

_SYSTEM_MESSAGE_PREFIX_TEMPLATE = "[{label} "

_SYSTEM_MESSAGE_PREFIXES: Mapping[str, MachineRoleLabel] = MappingProxyType(
    {_SYSTEM_MESSAGE_PREFIX_TEMPLATE.format(label=label): label for label in MachineRoleLabel}
)


def resolve_projected_text_author(text: str) -> tuple[TranscriptTextClassification, str | None]:
    """Return canonical classification plus optional legacy presentation label."""
    stripped = text.lstrip()
    classification = classify_transcript_text(text)
    if classification.kind in {
        TranscriptEntryKind.PLATFORM_CONTROL,
        TranscriptEntryKind.THIRD_PARTY_RUNTIME_ARTIFACT,
    }:
        return classification, None
    # is_conversation_bridge_message recognizes the leading structural marker
    # only — never the full peer grammar. It is the one part of the historical
    # bridge format that never froze delivery (see conversation_messages'
    # MalformedPeerSegmentError). Authorship for a bridge-classified block is
    # a durable, structural fact (peer bundle segments) once a bundle exists
    # for it; this classification decides presentation only — which category
    # badge a human sees — never attribution.
    if is_conversation_bridge_message(stripped):
        return TranscriptTextClassification(TranscriptEntryKind.IDENTITY_CONTENT), _PEER_BRIDGE_LABEL
    for prefix, role_label in _SYSTEM_MESSAGE_PREFIXES.items():
        if stripped.startswith(prefix):
            return TranscriptTextClassification(TranscriptEntryKind.IDENTITY_CONTENT), role_label.value
    return classification, None


def classify_projected_text(text: str) -> TranscriptTextClassification:
    """Classify transcript text for a synchronous projection caller."""
    classification, _ = resolve_projected_text_author(text)
    return classification
