"""Action-scoped human-involvement admission for agent-authored facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from teleclaude.core.agents import resolve_parser_agent
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.models import Session
from teleclaude.core.session_message_projection import build_message_chain
from teleclaude.output_projection.conversation_projector import project_conversation_chain
from teleclaude.output_projection.models import ProjectedAuthorKind, VisibilityPolicy

HUMAN_INPUT_RECENCY_WINDOW = timedelta(seconds=90)


class HumanInvolvementRefusal(StrEnum):
    """Reasons an action-local involvement declaration is not admissible."""

    EMPTY_REASON = "empty_reason"
    ABSENT_HUMAN_INPUT = "absent_human_input"
    STALE_HUMAN_INPUT = "stale_human_input"


@dataclass(frozen=True)
class HumanInvolvementValidation:
    """The non-durable result consumed by one fact-producing boundary."""

    admitted: bool
    refusal: HumanInvolvementRefusal | None = None
    latest_human_input_age_seconds: int | None = None


class HumanInvolvementSessionStore(Protocol):
    """The narrow session read required to derive transcript-backed recency."""

    async def get_session(self, session_id: str) -> Session | None: ...


async def validate_human_involvement(
    *,
    session_id: str,
    reason: str | None,
    session_store: HumanInvolvementSessionStore,
    now: datetime | None = None,
) -> HumanInvolvementValidation:
    """Validate one reason-bearing declaration without persisting its reason."""
    if reason is None or not reason.strip():
        return HumanInvolvementValidation(admitted=False, refusal=HumanInvolvementRefusal.EMPTY_REASON)

    session = await session_store.get_session(session_id)
    if session is None:
        return HumanInvolvementValidation(admitted=False, refusal=HumanInvolvementRefusal.ABSENT_HUMAN_INPUT)
    latest_human_input = _latest_human_input_at(session)
    if latest_human_input is None:
        return HumanInvolvementValidation(admitted=False, refusal=HumanInvolvementRefusal.ABSENT_HUMAN_INPUT)

    current = (now or datetime.now(UTC)).astimezone(UTC)
    age = max(timedelta(), current - latest_human_input)
    age_seconds = int(age.total_seconds())
    if age <= HUMAN_INPUT_RECENCY_WINDOW:
        return HumanInvolvementValidation(admitted=True)
    return HumanInvolvementValidation(
        admitted=False,
        refusal=HumanInvolvementRefusal.STALE_HUMAN_INPUT,
        latest_human_input_age_seconds=age_seconds,
    )


def human_involvement_refusal_detail(validation: HumanInvolvementValidation) -> str:
    """Render a reason-safe refusal that leaves the undeclared action available."""
    if validation.refusal is HumanInvolvementRefusal.EMPTY_REASON:
        return "human involvement requires a non-empty reason"
    if validation.refusal is HumanInvolvementRefusal.STALE_HUMAN_INPUT:
        assert validation.latest_human_input_age_seconds is not None
        return (
            "human involvement requires recent qualified human input "
            f"({validation.latest_human_input_age_seconds} seconds ago); rerun without --human-involved"
        )
    return "human involvement requires recent qualified human input; rerun without --human-involved"


def _latest_human_input_at(session: Session) -> datetime | None:
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
