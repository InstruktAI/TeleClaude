"""Compose event origin, subject, and project-owner facts at producer boundaries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.config_roster import ProjectOwnershipIndex, load_project_ownership_index
from teleclaude.config_subjects import SubjectRef
from teleclaude.core.operation_caller_identity import get_caller_session_id
from teleclaude.events.envelope import (
    EventEnvelope,
    EventHomeKind,
    EventHomeRef,
    EventOwnerKind,
    EventOwnerRef,
    EventSubject,
    EventSubjectMarker,
    EventSubjectOwnerMarker,
)
from teleclaude.session_identity import get_session_id

_LOGGER = get_logger(__name__)
_ORIGIN_HOME_LOOKUP_FAILED = "event_origin_home_lookup_failed"
_ORIGIN_HOME_SESSION_MISMATCH = "The identity response named a different session."
_SESSION_ID_FIELD = "session_id"
_ERROR_FIELD = "error"


def subject_for_project_path(path: str | Path) -> EventSubject:
    """Name the registered project at a path, or state that none governs it."""
    ownership = load_project_ownership_index().for_path(Path(path))
    if ownership is None:
        return EventSubjectMarker.NONE
    return EventHomeRef(EventHomeKind.PROJECT, ownership.project_slug)


def subject_for_session_config(config_subject: str | None) -> EventSubject:
    """Convert one recorded session home to its event subject."""
    return EventHomeRef.from_token(config_subject) if config_subject else EventSubjectMarker.NONE


@dataclass(frozen=True)
class EnvelopeFactResolver:
    """Read the current process session, its recorded home, and project ownership."""

    session_id: Callable[[], str | None]
    session_home: Callable[[str], Awaitable[EventSubject]]
    ownership_index: Callable[[], ProjectOwnershipIndex]


async def complete_envelope_facts(envelope: EventEnvelope, resolver: EnvelopeFactResolver) -> None:
    """Fill origin and owner facts without changing the producer's subject."""
    if envelope.originating_session_id is None:
        envelope.originating_session_id = get_caller_session_id() or resolver.session_id()
    if envelope.origin_home is None and envelope.originating_session_id is not None:
        origin_subject = await resolver.session_home(envelope.originating_session_id)
        if isinstance(origin_subject, EventHomeRef):
            envelope.origin_home = origin_subject

    subject = envelope.subject
    if isinstance(subject, EventHomeRef) and subject.kind is EventHomeKind.PROJECT:
        ownership = resolver.ownership_index().for_slug(subject.instance)
        if ownership is None:
            envelope.subject_owner = EventSubjectOwnerMarker.UNRESOLVED
        else:
            owner_identity = ownership.owner_identity()
            if owner_identity is None:
                envelope.subject_owner = EventSubjectOwnerMarker.OWNERLESS
            else:
                owner_kind, owner_slug = owner_identity
                envelope.subject_owner = EventOwnerRef(EventOwnerKind(owner_kind.value), owner_slug)
    else:
        envelope.subject_owner = EventSubjectOwnerMarker.NONE


def cli_envelope_fact_resolver() -> EnvelopeFactResolver:
    """Build the resolver used by short-lived CLI event producers."""

    async def _session_home(session_id: str) -> EventSubject:
        client = TelecAPIClient()
        try:
            await client.connect()
            identity = await client.whoami()
            if identity.session_id != session_id:
                raise ValueError(_ORIGIN_HOME_SESSION_MISMATCH)
            if identity.config_subject is None:
                return EventSubjectMarker.NONE
            return EventHomeRef.from_subject_ref(SubjectRef.from_token(identity.config_subject))
        except (APIError, OSError, ValueError, ValidationError) as error:
            _LOGGER.warning(
                _ORIGIN_HOME_LOOKUP_FAILED,
                extra={_SESSION_ID_FIELD: session_id, _ERROR_FIELD: repr(error)},
            )
            return EventSubjectMarker.UNKNOWN
        finally:
            await client.close()

    return EnvelopeFactResolver(
        session_id=get_session_id,
        session_home=_session_home,
        ownership_index=load_project_ownership_index,
    )
