"""Content lifecycle event declarations: the captured item is the subject."""

from __future__ import annotations

from pydantic import JsonValue

from teleclaude.events.catalog import DeclaredEvent, EventData, PlatformEvent
from teleclaude.events.envelope import EventHomeKind
from teleclaude.events.references import CapturedItemRef

_SESSION_HOMES = (EventHomeKind.PROJECT, EventHomeKind.PERSON, EventHomeKind.COMPANY)


class ContentDumpedData(EventData):
    author: str
    inbox_path: str
    tags: list[str]


class ContentIdData(EventData):
    content_id: JsonValue


class ContentDumped(PlatformEvent[CapturedItemRef, ContentDumpedData]):
    NAME = "teleclaude.content.dumped"
    DESCRIPTION = "Raw content was captured and queued for processing"
    HOME_KINDS = _SESSION_HOMES


class ContentRefined(PlatformEvent[CapturedItemRef, ContentIdData]):
    NAME = "teleclaude.content.refined"
    DESCRIPTION = "Content was processed or edited"
    HOME_KINDS = _SESSION_HOMES


class ContentPublished(PlatformEvent[CapturedItemRef, ContentIdData]):
    NAME = "teleclaude.content.published"
    DESCRIPTION = "Content was made available externally"
    HOME_KINDS = _SESSION_HOMES


DECLARED: tuple[DeclaredEvent, ...] = (ContentDumped, ContentRefined, ContentPublished)
