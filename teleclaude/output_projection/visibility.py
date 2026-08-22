"""Presentation decisions derived from the canonical transcript classification."""

from __future__ import annotations

from teleclaude.core.conversation_messages import is_conversation_bridge_message
from teleclaude.core.injected_text import (
    TranscriptEntryKind,
    TranscriptTextClassification,
    classify_transcript_text,
)

_PEER_BRIDGE_LABEL = "Peer"


def resolve_projected_text_author(text: str) -> tuple[TranscriptTextClassification, str | None]:
    """Return canonical classification plus optional legacy presentation label."""
    stripped = text.lstrip()
    classification = classify_transcript_text(text)
    if classification.kind in {
        TranscriptEntryKind.PLATFORM_CONTROL,
    }:
        return classification, None
    if is_conversation_bridge_message(stripped):
        return TranscriptTextClassification(TranscriptEntryKind.IDENTITY_CONTENT), _PEER_BRIDGE_LABEL
    return classification, None


def classify_projected_text(text: str) -> TranscriptTextClassification:
    """Classify transcript text for a synchronous projection caller."""
    classification, _ = resolve_projected_text_author(text)
    return classification
