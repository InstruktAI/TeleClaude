"""Action-scoped human-involvement resolution for agent-authored facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import resolve_parser_agent
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.models import Session
from teleclaude.core.session_transcript_chain import build_message_chain
from teleclaude.output_projection.conversation_projector import project_conversation_chain
from teleclaude.output_projection.models import ProjectedAuthorKind, VisibilityPolicy

logger = get_logger(__name__)

HUMAN_INPUT_RECENCY_WINDOW = timedelta(seconds=90)


class HumanInvolvementSurface(StrEnum):
    """The fact-producing boundaries that resolve one involvement record."""

    COMMIT = "commit"
    TODO_CREATION = "todo_creation"


class HumanInvolvementReasonInvalid(ValueError):
    """Raised when a declared reason is missing or blank.

    This is the only way resolution refuses anything; it judges the
    invocation, never the observed human presence.
    """


@dataclass(frozen=True)
class HumanInvolvementResolution:
    """The non-durable outcome consumed by one fact-producing boundary."""

    involved: bool
    latest_human_input_age_seconds: int | None = None


class HumanInvolvementSessionStore(Protocol):
    """The narrow session read required to derive transcript-backed recency."""

    async def get_session(self, session_id: str) -> Session | None: ...


async def resolve_human_involvement(
    *,
    session_id: str,
    reason: str | None,
    session_store: HumanInvolvementSessionStore,
    surface: HumanInvolvementSurface,
    now: datetime | None = None,
) -> HumanInvolvementResolution:
    """Resolve one reason-bearing declaration against observed human presence.

    Never refuses the act it annotates: a stale or absent observation
    resolves to ``involved=False`` rather than raising. Only a missing or
    blank reason raises, because that is an argument error, not a judgement
    about the human.
    """
    if reason is None or not reason.strip():
        raise HumanInvolvementReasonInvalid("human involvement requires a non-empty reason")

    session = await session_store.get_session(session_id)
    latest_human_input = latest_human_input_at(session) if session is not None else None
    if latest_human_input is None:
        _record_discard(session_id=session_id, surface=surface, age_seconds=None)
        return HumanInvolvementResolution(involved=False)

    current = (now or datetime.now(UTC)).astimezone(UTC)
    age = max(timedelta(), current - latest_human_input)
    age_seconds = int(age.total_seconds())
    if age <= HUMAN_INPUT_RECENCY_WINDOW:
        return HumanInvolvementResolution(involved=True)
    _record_discard(session_id=session_id, surface=surface, age_seconds=age_seconds)
    return HumanInvolvementResolution(involved=False, latest_human_input_age_seconds=age_seconds)


def _record_discard(*, session_id: str, surface: HumanInvolvementSurface, age_seconds: int | None) -> None:
    """Log one discarded involvement declaration without the supplied reason."""
    logger.info(
        "human involvement declaration discarded",
        session_id=session_id,
        surface=surface.value,
        latest_human_input_age_seconds=age_seconds,
    )


def latest_human_input_at(session: Session) -> datetime | None:
    """Read the newest human-authored block through the canonical projection seam."""
    chain = build_message_chain(session.transcript_files, session.native_log_file)
    if not chain:
        return None
    blocks = project_conversation_chain(
        chain,
        resolve_parser_agent(session.active_agent),
        VisibilityPolicy(),
    )
    for block in reversed(blocks):
        if block.author.kind is not ProjectedAuthorKind.HUMAN:
            continue
        timestamp = parse_iso_datetime(block.timestamp)
        if timestamp is not None:
            return timestamp
    return None
