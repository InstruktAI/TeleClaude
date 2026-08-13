"""Segment types shared between conversation collection and bundle delivery.

Extracted so `conversation_delivery.py` (collection) and
`conversation_bundle_delivery.py` (send/replay mechanics) can both depend on
one typed vocabulary without depending on each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from teleclaude.core.conversation_messages import ParsedPeerSegment
from teleclaude.core.models import HumanFacingMessage
from teleclaude.output_projection.models import ProjectedAuthor


@dataclass(frozen=True)
class ProjectedSegment:
    """Transcript-cut segment before identity resolution.

    The pure, synchronous output of the thread worker: no config or database
    access has happened yet, so ``author`` is the projector's own bracket
    classification (see ``ProjectedAuthor``), not a resolved identity. Phase 2
    turns each of these into a ``ConversationSegment`` once identity is
    resolved.
    """

    role: str
    text: str
    timestamp: datetime
    author: ProjectedAuthor


@dataclass(frozen=True)
class ForwardedProjectedSegment:
    """A peer segment parsed from a source transcript bridge block."""

    source_timestamp: datetime
    peer_segment: ParsedPeerSegment


type CollectedSegment = ProjectedSegment | ForwardedProjectedSegment


@dataclass(frozen=True)
class LocalConversationPayload:
    """A locally-authored segment rendered from its resolved message envelope."""

    role: str
    message: HumanFacingMessage


@dataclass(frozen=True)
class ForwardedConversationPayload:
    """A parsed peer segment retained with its original rendered header/body."""

    peer_segment: ParsedPeerSegment


type ConversationPayload = LocalConversationPayload | ForwardedConversationPayload


@dataclass(frozen=True)
class ConversationSegment:
    """Visible content with one replay clock and a typed rendering payload."""

    source_timestamp: datetime
    payload: ConversationPayload
