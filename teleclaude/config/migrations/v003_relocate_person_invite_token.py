"""Move person invitation tokens to the config-owned token map."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Final

from teleclaude.config.invitation_store import InvitationTokenOwned, assign_token
from teleclaude.config.migrations._chain import Destination
from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 3
KINDS: Final = frozenset({ConfigSubjectKind.PERSON})
READ_REQUIRES_REGISTRY: Final = False
MOVES: Final = Destination.INVITATIONS
_INVITE_TOKEN = "invite_token"
_PERSON_INSTANCE_ERROR = "Person subject requires an instance"
_TOKEN_TYPE_ERROR = "Invitation token must be text"


class DestinationConflict(ValueError):
    """A person token conflicts with the token map's existing owner."""


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Remove the token after a persisting operation delivers it."""
    document.pop(_INVITE_TOKEN, None)


def pending(document: Mapping[str, object], _subject: SubjectRef) -> object | None:
    """Return a token still held in the person document."""
    return document.get(_INVITE_TOKEN)


def deliver(value: object, subject: SubjectRef) -> None:
    """Assign the token to its registered person."""
    if subject.instance is None:
        raise ValueError(_PERSON_INSTANCE_ERROR)
    if not isinstance(value, str):
        raise TypeError(_TOKEN_TYPE_ERROR)
    try:
        assign_token(value, subject.instance)
    except InvitationTokenOwned as exc:
        raise DestinationConflict(str(exc)) from exc
