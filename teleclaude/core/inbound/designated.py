"""Which retained sessions a designated channel's assistant adopts.

A conversation channel can hold sessions created before its input reached the
conversation seam: they carry the adapter's channel but no endpoint stamp, so
the idle cycle never saw them as continuing conversations
(`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`,
Designated conversation channels). Adopting one records the endpoint on it and
keeps everything else; this module decides whether a record may be adopted.

A record is adopted only when its recorded purpose, home and participant agree
with the person whose assistant the channel reaches. A record that disagrees is
left untouched and reported with the fact that disagreed, never given an
inferred endpoint.
"""

from __future__ import annotations

from enum import StrEnum

from teleclaude.core.inbound.conversation_env import ConversationEnvironment
from teleclaude.core.models import Session
from teleclaude.core.session_ended import session_ended_kind
from teleclaude.events.envelope import EventHomeKind, EventHomeRef
from teleclaude.events.envelope_facts import home_for_session_config
from teleclaude.events.schemas.system import SessionEndedKind


class AdoptionVerdict(StrEnum):
    """Whether a retained session may be adopted into a person's assistant conversation, and the fact that bars it."""

    ADOPTABLE = "adoptable"
    PURPOSE_MISMATCH = "purpose_mismatch"
    HOME_MISMATCH = "home_mismatch"
    PARTICIPANT_MISMATCH = "participant_mismatch"


def _in_person_home(session: Session, person_slug: str) -> bool:
    """Whether the session's recorded configuration subject is the person's own home."""
    try:
        home = home_for_session_config(session.config_subject)
    except ValueError:
        return False
    return isinstance(home, EventHomeRef) and home.kind is EventHomeKind.PERSON and home.instance == person_slug


def assess_adoption(session: Session, person_slug: str, env: ConversationEnvironment) -> AdoptionVerdict:
    """Whether a session without an endpoint stamp may become ``person_slug``'s assistant conversation.

    Its recorded kind must be a person's own session (a help-desk, system or unresolvable
    record is another purpose), it must have run in that person's home, and its recorded
    human principal must resolve to that person.
    """
    if session_ended_kind(session) is not SessionEndedKind.PERSON:
        return AdoptionVerdict.PURPOSE_MISMATCH
    if not _in_person_home(session, person_slug):
        return AdoptionVerdict.HOME_MISMATCH
    if env.session_person(session) != person_slug:
        return AdoptionVerdict.PARTICIPANT_MISMATCH
    return AdoptionVerdict.ADOPTABLE


__all__ = ["AdoptionVerdict", "assess_adoption"]
