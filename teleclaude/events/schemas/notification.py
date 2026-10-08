"""Escalation event declarations: an issue escalated to a human, and its resolution."""

from __future__ import annotations

from pydantic import JsonValue

from teleclaude.events.catalog import DeclaredEvent, EventData, PlatformEvent
from teleclaude.events.envelope import EventHomeKind
from teleclaude.events.references import EscalationRef

_SESSION_HOMES = (EventHomeKind.PROJECT, EventHomeKind.PERSON, EventHomeKind.COMPANY)


class EscalationData(EventData):
    escalation_id: JsonValue | None = None
    reason: JsonValue | None = None


class EscalationResolutionData(EventData):
    escalation_id: JsonValue


class NotificationEscalation(PlatformEvent[EscalationRef, EscalationData]):
    NAME = "teleclaude.notification.escalation"
    DESCRIPTION = "An issue was escalated to a human for action"
    HOME_KINDS = _SESSION_HOMES


class NotificationResolution(PlatformEvent[EscalationRef, EscalationResolutionData]):
    NAME = "teleclaude.notification.resolution"
    DESCRIPTION = "An escalation was resolved"
    HOME_KINDS = _SESSION_HOMES


DECLARED: tuple[DeclaredEvent, ...] = (NotificationEscalation, NotificationResolution)
