"""Compose event origin and project-owner facts at the producer boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.config_roster import ProjectOwnershipIndex, load_project_ownership_index
from teleclaude.config_subjects import SubjectRef
from teleclaude.core.operation_caller_identity import get_caller_session_id
from teleclaude.events.envelope import (
    EventEnvelope,
    EventHomeKind,
    EventHomeRef,
    EventOwnerKind,
    EventOwnerRef,
    EventSubjectOwnerMarker,
)
from teleclaude.session_identity import get_session_id


@dataclass(frozen=True)
class EnvelopeFactResolver:
    """Read the current process session, its recorded home, and project ownership."""

    session_id: Callable[[], str | None]
    session_home: Callable[[str], Awaitable[EventHomeRef | None]]
    ownership_index: Callable[[], ProjectOwnershipIndex]


async def complete_envelope_facts(envelope: EventEnvelope, resolver: EnvelopeFactResolver) -> None:
    """Fill origin and owner facts without changing the producer's subject."""
    if envelope.originating_session_id is None:
        envelope.originating_session_id = get_caller_session_id() or resolver.session_id()
    if envelope.origin_home is None and envelope.originating_session_id is not None:
        envelope.origin_home = await resolver.session_home(envelope.originating_session_id)

    subject = envelope.subject
    if isinstance(subject, EventHomeRef) and subject.kind is EventHomeKind.PROJECT:
        ownership = resolver.ownership_index().for_slug(subject.instance)
        if ownership is None:
            envelope.subject_owner = EventSubjectOwnerMarker.UNRESOLVED
        elif ownership.company:
            envelope.subject_owner = EventOwnerRef(EventOwnerKind.COMPANY, ownership.company)
        elif ownership.person:
            envelope.subject_owner = EventOwnerRef(EventOwnerKind.PERSON, ownership.person)
        else:
            envelope.subject_owner = EventSubjectOwnerMarker.OWNERLESS
    else:
        envelope.subject_owner = EventSubjectOwnerMarker.NONE


def cli_envelope_fact_resolver() -> EnvelopeFactResolver:
    """Build the resolver used by short-lived CLI event producers."""

    async def _session_home(session_id: str) -> EventHomeRef | None:
        client = TelecAPIClient()
        try:
            sessions = await client.list_sessions(session_ids=(session_id,))
        finally:
            await client.close()
        if not sessions or sessions[0].config_subject is None:
            return None
        return EventHomeRef.from_subject_ref(SubjectRef.from_token(sessions[0].config_subject))

    return EnvelopeFactResolver(
        session_id=get_session_id,
        session_home=_session_home,
        ownership_index=load_project_ownership_index,
    )
