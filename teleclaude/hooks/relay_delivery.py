"""Per-computer delivery of relayed external events to the hook dispatcher.

The ingress relays every verified external request onto the platform event
stream. Each computer, the ingress included, reads that stream through its own
consumer group and hands each relayed event to its local hook dispatcher once.
The envelope's ``source`` names the protocol that accepted the request, and that
alone decides how the event is rebuilt for the dispatcher: a provider delivery
becomes the provider's canonical hook event, and a native event keeps its full
name as its type whatever that name says.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventEnvelope, EventHomeKind, EventHomeRef
from teleclaude.hooks.dispatcher import HookDispatcher
from teleclaude.hooks.normalizers.github import github_hook_event
from teleclaude.hooks.normalizers.whatsapp import whatsapp_hook_event
from teleclaude.hooks.webhook_models import HookEvent

logger = get_logger(__name__)

_DOMAIN_SEPARATOR = "."
_COMPANY_PROPERTY = "company"
_NAME_PREFIX_ERROR = "relayed event {event!r} does not begin with its domain {domain!r}"


class RelayProtocol(StrEnum):
    """The protocols the ingress accepts, carried as a relayed event's ``source``."""

    NATIVE = "native"
    GITHUB = "github"
    WHATSAPP = "whatsapp"


def _name_after_domain(envelope: EventEnvelope) -> str:
    """Return the event name that follows its domain, ``<name>`` of ``<domain>.<name>``."""
    prefix = envelope.domain + _DOMAIN_SEPARATOR
    if not envelope.event.startswith(prefix):
        raise ValueError(_NAME_PREFIX_ERROR.format(event=envelope.event, domain=envelope.domain))
    return envelope.event[len(prefix) :]


def _native_hook_event(envelope: EventEnvelope) -> HookEvent:
    properties: dict[str, str | int | float | bool | list[str] | None] = {}
    subject = envelope.subject
    if isinstance(subject, EventHomeRef) and subject.kind is EventHomeKind.COMPANY:
        properties[_COMPANY_PROPERTY] = subject.instance
    return HookEvent(
        source=envelope.domain,
        type=envelope.event,
        timestamp=envelope.timestamp.isoformat(),
        properties=properties,
        payload=envelope.payload,
    )


def _github_hook_event(envelope: EventEnvelope) -> HookEvent:
    return github_hook_event(_name_after_domain(envelope), envelope.payload, envelope.timestamp.isoformat())


def _whatsapp_hook_event(envelope: EventEnvelope) -> HookEvent:
    return whatsapp_hook_event(_name_after_domain(envelope), envelope.payload)


_REBUILDERS: Final[Mapping[RelayProtocol, Callable[[EventEnvelope], HookEvent]]] = {
    RelayProtocol.NATIVE: _native_hook_event,
    RelayProtocol.GITHUB: _github_hook_event,
    RelayProtocol.WHATSAPP: _whatsapp_hook_event,
}


def relayed_hook_event(envelope: EventEnvelope) -> HookEvent:
    """Rebuild the hook event a relayed envelope is delivered as; the envelope's source must be a relay protocol."""
    return _REBUILDERS[RelayProtocol(envelope.source)](envelope)


class RelayDeliveryPipeline:
    """Deliver relayed envelopes to the local hook dispatcher and acknowledge every other envelope untouched."""

    def __init__(self, dispatcher: HookDispatcher) -> None:
        self._dispatcher = dispatcher

    async def execute(self, envelope: EventEnvelope, /) -> HookEvent | None:
        """Dispatch one relayed envelope; a failure escaping dispatch propagates to the processor's retry and DLQ."""
        if envelope.source not in set(RelayProtocol):
            return None
        event = relayed_hook_event(envelope)
        await self._dispatcher.dispatch(event)
        return event
