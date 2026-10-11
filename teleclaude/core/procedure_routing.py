"""Procedure activation consumer: matches each of this computer's events to the published procedure subscriptions.

Publication is registration: the consumer reads the subscription set from the
published index and holds it with the index file identity it came from, so an
added, edited or removed subscription takes effect at the next event. Matching
reads only the event's type and home. Every match becomes one activation
command whose request id derives from the event, the procedure and the home, so
an event handed again after interrupted handling submits the same activations
and the operations service finds the ones already submitted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.core.command_dispatch import run_local_command
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import ErrorEventContext, TeleClaudeEvents
from teleclaude.docs_subscriptions import (
    IndexFileIdentity,
    SubscriptionEntry,
    SubscriptionHomeKind,
    published_index_identity,
    published_procedure_subscriptions,
)
from teleclaude.events.consumers import Consumer, Interest
from teleclaude.events.envelope import EventHomeMarker, EventHomeRef, EventVisibility, ReceivedEvent, occurrence_id
from teleclaude.events.type_pattern import ANY_TYPE
from teleclaude.types.activation_home import ActivationHome
from teleclaude.types.commands import ActivateProcedureCommand

logger = get_logger(__name__)

PROCEDURE_ACTIVATION_CONSUMER = "procedure-activation"

_ACTIVATION_DECISION_EVENT = "procedure_activation_decision"
_SUBSCRIPTIONS_READ_EVENT = "procedure_subscriptions_read"
_SUBSCRIPTIONS_UNREADABLE_EVENT = "procedure_subscriptions_unreadable"
_SUBMISSION_FAILED_EVENT = "procedure_activation_submission_failed"
_SUBMITTED_OUTCOME = "submitted"
_OPERATION_ID_KEY = "operation_id"
_UNREADABLE_INDEX_SOURCE = "procedure_subscriptions_refresh"
_ERROR_EVENT_EMISSION_FAILED_EVENT = "procedure_activation_error_event_emission_failed"


def _emit_platform_error(message: str, *, source: str, details: Mapping[str, object] | None = None) -> None:
    try:
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=None, message=message, source=source, details=details),
            visibility=EventVisibility.CLUSTER,
        )
    except Exception as exc:
        logger.error(_ERROR_EVENT_EMISSION_FAILED_EVENT, source=source, error=str(exc))


def activation_home(event: ReceivedEvent) -> ActivationHome | None:
    """The home an event's origin names, or ``None`` when its origin is unknown and activates nothing."""
    home = event.home
    if isinstance(home, EventHomeRef):
        return ActivationHome(SubscriptionHomeKind(home.kind.value), home.instance)
    if home is EventHomeMarker.NONE:
        return ActivationHome.platform()
    return None


class _PublishedSubscriptions:
    """The subscription set this consumer matches against, with the index version it was read from.

    A set that cannot be read is replaced by none, never kept stale, and the
    unreadable version is announced once: a later event finding the same
    unreadable version emits nothing more.
    """

    def __init__(self) -> None:
        self._loaded = False
        self._version: IndexFileIdentity | None = None
        self._entries: tuple[SubscriptionEntry, ...] = ()

    async def current(self) -> tuple[SubscriptionEntry, ...]:
        """The subscriptions of the index as it is now; re-read only when the index file changed."""
        try:
            identity: IndexFileIdentity | None = await asyncio.to_thread(published_index_identity)
        except OSError:
            identity = None
        if self._loaded and identity == self._version:
            return self._entries
        self._loaded = True
        self._version = identity
        try:
            publication = await asyncio.to_thread(published_procedure_subscriptions)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self._entries = ()
            logger.error(_SUBSCRIPTIONS_UNREADABLE_EVENT, error=str(exc), exc_info=True)
            _emit_platform_error(str(exc), source=_UNREADABLE_INDEX_SOURCE)
            return self._entries
        self._version = publication.identity
        self._entries = publication.entries
        logger.info(_SUBSCRIPTIONS_READ_EVENT, digest=publication.digest, entry_count=len(self._entries))
        return self._entries


def _activation_request_id(event: ReceivedEvent, procedure_id: str, home: ActivationHome) -> str:
    """The identity of one activation: the same event, procedure and home always yield the same id."""
    return occurrence_id(event.id, procedure_id, home.to_token())


async def _submit(event: ReceivedEvent, entry: SubscriptionEntry, home: ActivationHome) -> None:
    command = ActivateProcedureCommand(
        procedure_id=entry.procedure_id,
        home=home.to_token(),
        event_json=event.model_dump_json(),
        identity=entry.identity,
        attendance=entry.attendance,
        event_delivery=entry.delivery.event_delivery,
        interruptible=entry.delivery.interruptible,
        request_id=_activation_request_id(event, entry.procedure_id, home),
    )
    receipt = await run_local_command(command)
    operation_id = receipt.get(_OPERATION_ID_KEY) if isinstance(receipt, dict) else None
    logger.info(
        _ACTIVATION_DECISION_EVENT,
        procedure_id=entry.procedure_id,
        home=home.to_token(),
        outcome=_SUBMITTED_OUTCOME,
        operation_id=operation_id,
        event_id=event.id,
        event_type=event.type,
    )


def build_procedure_activation_consumer() -> Consumer:
    """The consumer that activates, on this computer, the published procedures an event of this computer answers."""
    subscriptions = _PublishedSubscriptions()

    async def handle(event: ReceivedEvent) -> None:
        home = activation_home(event)
        if home is None:
            return
        entries = await subscriptions.current()
        matched = [entry for entry in entries if entry.matches_type(event.type) and entry.reaches(home.kind, home.slug)]
        failures: list[Exception] = []
        for entry in matched:
            try:
                await _submit(event, entry, home)
            except Exception as exc:
                logger.error(
                    _SUBMISSION_FAILED_EVENT,
                    procedure_id=entry.procedure_id,
                    home=home.to_token(),
                    event_id=event.id,
                    error=str(exc),
                    exc_info=True,
                )
                failures.append(exc)
        if failures:
            raise failures[0]

    return Consumer(
        name=PROCEDURE_ACTIVATION_CONSUMER,
        interest=Interest(types=(ANY_TYPE,), own_computer_only=True),
        handler=handle,
    )
