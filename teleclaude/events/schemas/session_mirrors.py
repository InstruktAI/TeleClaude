"""Session mirror event declarations: a conversation mirror reporting how far it covers a session's conversation."""

from __future__ import annotations

from teleclaude.events.catalog import DeclaredEvent, EventData, PlatformEvent
from teleclaude.events.envelope import EventHomeKind
from teleclaude.events.references import SessionRef

_SESSION_HOMES = (EventHomeKind.PROJECT, EventHomeKind.PERSON, EventHomeKind.COMPANY)


class MirrorCoveredData(EventData):
    session_id: str
    covered_at: str
    ready: bool
    complete: bool
    missing_source_count: int
    message_count: int


class MirrorCovered(PlatformEvent[SessionRef, MirrorCoveredData]):
    NAME = "teleclaude.session_mirrors.mirror.covered"
    DESCRIPTION = (
        "A session's conversation mirror was refreshed and covers the conversation through the stated time; "
        "readiness reports whether every source present on disk was read"
    )
    HOME_KINDS = _SESSION_HOMES


DECLARED: tuple[DeclaredEvent, ...] = (MirrorCovered,)
