"""Facts the emission boundary adds and the homes producers state: caller session, project owner, recorded homes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.config_roster import ProjectOwnershipIndex, load_project_ownership_index
from teleclaude.config_subjects import SubjectRef
from teleclaude.events.envelope import (
    EventHome,
    EventHomeKind,
    EventHomeMarker,
    EventHomeOwner,
    EventHomeOwnerMarker,
    EventHomeRef,
    EventOwnerKind,
    EventOwnerRef,
)
from teleclaude.session_identity import get_session_id

_LOGGER = get_logger(__name__)
_SESSION_HOME_LOOKUP_FAILED = "event_session_home_lookup_failed"
_SESSION_HOME_MISMATCH = "The identity response named a different session."
_SESSION_ID_FIELD = "session_id"
_ERROR_FIELD = "error"


def home_for_project_path(path: str | Path) -> EventHome:
    """Name the registered project at a path, or state that none governs it."""
    ownership = load_project_ownership_index().for_path(Path(path))
    if ownership is None:
        return EventHomeMarker.NONE
    return EventHomeRef(EventHomeKind.PROJECT, ownership.project_slug)


def home_for_session_config(config_subject: str | None) -> EventHome:
    """Convert one recorded session home to its event home."""
    return EventHomeRef.from_token(config_subject) if config_subject else EventHomeMarker.NONE


@dataclass(frozen=True)
class EnvelopeFactResolver:
    """Read the current process session and project ownership at the emission boundary."""

    session_id: Callable[[], str | None]
    ownership_index: Callable[[], ProjectOwnershipIndex]


def home_owner_of(home: EventHome, resolver: EnvelopeFactResolver) -> EventHomeOwner:
    """Resolve the owner a project home carries as this computer reads it; other homes have none."""
    if not (isinstance(home, EventHomeRef) and home.kind is EventHomeKind.PROJECT):
        return EventHomeOwnerMarker.NONE
    ownership = resolver.ownership_index().for_slug(home.instance)
    if ownership is None:
        return EventHomeOwnerMarker.UNRESOLVED
    owner_identity = ownership.owner_identity()
    if owner_identity is None:
        return EventHomeOwnerMarker.OWNERLESS
    owner_kind, owner_slug = owner_identity
    return EventOwnerRef(EventOwnerKind(owner_kind.value), owner_slug)


def cli_envelope_fact_resolver() -> EnvelopeFactResolver:
    """Build the resolver used by short-lived CLI event producers."""
    return EnvelopeFactResolver(session_id=get_session_id, ownership_index=load_project_ownership_index)


async def cli_session_home(session_id: str) -> EventHome:
    """Read a session's recorded home through the daemon API, for CLI producers acting for that session."""
    client = TelecAPIClient()
    try:
        await client.connect()
        identity = await client.whoami()
        if identity.session_id != session_id:
            raise ValueError(_SESSION_HOME_MISMATCH)
        if identity.config_subject is None:
            return EventHomeMarker.NONE
        return EventHomeRef.from_subject_ref(SubjectRef.from_token(identity.config_subject))
    except (APIError, OSError, ValueError, ValidationError) as error:
        _LOGGER.warning(
            _SESSION_HOME_LOOKUP_FAILED,
            extra={_SESSION_ID_FIELD: session_id, _ERROR_FIELD: repr(error)},
        )
        return EventHomeMarker.UNKNOWN
    finally:
        await client.close()
