"""Incident alerts: the consumer that tells platform administrators once when a thing breaks and once when it works again.

A matter is one lifecycle family's state of one thing: the family and the subject within its origin. The
type of an event names the state it reports; the consumer opens a matter on a failing state, closes it on
an ok state, and tells each selected administrator the matter's current state once. The only state kept
is the incident record in the event database: the matter's current standing with the type and time of the
event that brought it there, when it became broken, and the standing each selected administrator was last
told. A message is composed from that record, so a delivery that outlives its event still states the
transition it stands for. The consumer knows no producer and no type name.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.config.notification_interests import PLATFORM_CATEGORY, selects
from teleclaude.core.integration.notification_messages import compose_notification_message
from teleclaude.core.organization import platform_admin_people
from teleclaude.core.person_messaging import send_person_message
from teleclaude.events.catalog import EventCatalog, StateStanding
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.db import EventDB, IncidentKey, IncidentRecord
from teleclaude.events.envelope import ReceivedEvent, home_token
from teleclaude.events.references import EventRef
from teleclaude.events.type_pattern import TypePattern

logger = get_logger(__name__)

INCIDENT_ALERTS_CONSUMER: Final = "incident-alerts"

_NO_PUBLISHED_DOMAINS: Final[tuple[str, ...]] = ()
_RECOVERY_SENTENCE: Final = "It was broken for {duration}."
_DURATION_UNITS: Final = ((86400, "d"), (3600, "h"), (60, "m"), (1, "s"))
_DURATION_PART: Final = "{count}{unit}"
_DURATION_SEPARATOR: Final = " "
_DURATION_PARTS_SHOWN: Final = 2
_LESS_THAN_A_SECOND: Final = "under 1s"
_NEGATIVE_INTERVAL_ERROR: Final = "recovery is dated {duration} before the failure it ends"
_UNDECLARED_RECORD_TYPE_ERROR: Final = "incident record names event type {event_type} the catalog does not declare"
_UNDELIVERED_ERROR: Final = "incident alert not delivered to: {recipients}"
_RECIPIENT_SEPARATOR: Final = ", "
_INCIDENT_OPENED_EVENT: Final = "Incident opened"
_INCIDENT_STANDING_CHANGED_EVENT: Final = "Incident standing changed"
_INCIDENT_CLOSED_EVENT: Final = "Incident closed"
_INCIDENT_TOLD_EVENT: Final = "Incident told"
_INCIDENT_TELL_FAILED_EVENT: Final = "Incident could not be told"


class IncidentDeliveryError(RuntimeError):
    """An alert did not reach every outstanding recipient; the runtime retries the handling."""


def _format_duration(duration: timedelta) -> str:
    """The two largest nonzero units of a non-negative duration, such as `2h 5m`; a negative one is invalid time ordering."""
    if duration < timedelta(0):
        raise ValueError(_NEGATIVE_INTERVAL_ERROR.format(duration=duration))
    remaining = int(duration.total_seconds())
    parts: list[str] = []
    for seconds_per_unit, unit in _DURATION_UNITS:
        count, remaining = divmod(remaining, seconds_per_unit)
        if count:
            parts.append(_DURATION_PART.format(count=count, unit=unit))
    return _DURATION_SEPARATOR.join(parts[:_DURATION_PARTS_SHOWN]) or _LESS_THAN_A_SECOND


class _IncidentAlerts:
    """The handler of one computer's incident alerts."""

    def __init__(self, db: EventDB, catalog: EventCatalog) -> None:
        self._db = db
        self._catalog = catalog

    async def handle(self, event: ReceivedEvent) -> None:
        """Apply the event's state to its matter, then tell every selected administrator who still awaits it."""
        declaration = self._catalog.get(event.type)
        state = declaration.state if declaration is not None else None
        if state is None or event.subject is None:
            return
        key = IncidentKey(family=state.family, subject=event.subject.to_token(), home=home_token(event.home))
        selected = [
            slug
            for slug, person in platform_admin_people()
            if selects(person.notifications, event.type, _NO_PUBLISHED_DOMAINS)
        ]
        record = await self._apply_state(key, state.standing, event, selected)
        if record is None:
            return
        told = dict(record.told)
        # Recipients are fixed at each transition; a later subscriber is not added by a repeated failure.
        audience = [slug for slug in selected if slug in told]
        outstanding = [slug for slug in audience if told[slug] is not record.standing]
        failed = await self._tell(record, event.subject, event.source, outstanding, told)
        if failed:
            raise IncidentDeliveryError(_UNDELIVERED_ERROR.format(recipients=_RECIPIENT_SEPARATOR.join(failed)))
        if record.standing is StateStanding.OK and all(told[slug] is StateStanding.OK for slug in audience):
            await self._db.delete_incident(key)
            logger.info(_INCIDENT_CLOSED_EVENT, family=key.family, subject=key.subject, home=key.home)

    async def _apply_state(
        self, key: IncidentKey, standing: StateStanding, event: ReceivedEvent, selected: list[str]
    ) -> IncidentRecord | None:
        """Bring the matter to the standing the event reports and return its record; none when there is no matter.

        A matter that opens or changes standing takes the administrators selected by the event as recipients of
        that transition; an event that changes nothing adds none.
        """
        record = await self._db.get_incident(key)
        if record is None:
            if standing is StateStanding.OK:
                return None
            await self._db.open_incident(key, event.type, event.time, selected)
            logger.info(_INCIDENT_OPENED_EVENT, family=key.family, subject=key.subject, home=key.home)
        elif record.standing is standing:
            return record
        else:
            broken_since = record.broken_since if standing is StateStanding.OK else event.time
            await self._db.set_incident_standing(key, standing, event.type, event.time, broken_since, selected)
            logger.info(
                _INCIDENT_STANDING_CHANGED_EVENT, family=key.family, subject=key.subject, standing=standing.value
            )
        return await self._db.get_incident(key)

    async def _tell(
        self,
        record: IncidentRecord,
        subject: EventRef,
        computer: str,
        outstanding: list[str],
        told: dict[str, StateStanding | None],
    ) -> list[str]:
        """Send the matter's current standing to each outstanding recipient and mark each success; return the failures.

        `told` is updated with every recipient reached. One recipient's channel failing must not hide the
        others, so a failure is logged and collected, never raised here.
        """
        if not outstanding:
            return []
        text = self._message(record, subject, computer)
        failed: list[str] = []
        for slug in outstanding:
            try:
                await send_person_message(slug, text)
            except Exception:
                logger.exception(
                    _INCIDENT_TELL_FAILED_EVENT, family=record.key.family, subject=record.key.subject, recipient=slug
                )
                failed.append(slug)
                continue
            await self._db.mark_incident_recipient_told(record.key, slug, record.standing)
            told[slug] = record.standing
            logger.info(
                _INCIDENT_TOLD_EVENT,
                family=record.key.family,
                subject=record.key.subject,
                recipient=slug,
                standing=record.standing.value,
            )
        return failed

    def _message(self, record: IncidentRecord, subject: EventRef, computer: str) -> str:
        """The message for the matter's current standing, from the record's type and time rather than the handling event's."""
        declaration = self._catalog.get(record.event_type)
        if declaration is None:
            raise LookupError(_UNDECLARED_RECORD_TYPE_ERROR.format(event_type=record.event_type))
        recovery = (
            _RECOVERY_SENTENCE.format(duration=_format_duration(record.occurred_at - record.broken_since))
            if record.standing is StateStanding.OK
            else None
        )
        return compose_notification_message(
            event_type=record.event_type,
            declaration=declaration,
            subject=subject,
            computer=computer,
            occurred_at=record.occurred_at,
            addition=recovery,
        )


def build_incident_alerts_consumer(db: EventDB, catalog: EventCatalog) -> Consumer:
    """The consumer that tells platform administrators about this computer's platform problems."""
    alerts = _IncidentAlerts(db, catalog)
    return Consumer(
        name=INCIDENT_ALERTS_CONSUMER,
        interest=Interest(types=(TypePattern.below(PLATFORM_CATEGORY),), own_computer_only=True),
        handler=alerts.handle,
    )
