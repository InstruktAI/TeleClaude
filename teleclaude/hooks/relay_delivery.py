"""Per-computer delivery of relayed external events to the hook dispatcher.

The ingress relays every verified external request onto the platform event
stream. Each computer, the ingress included, reads that stream through its own
consumer group and hands each relayed event to its local hook dispatcher once.
The event's producer label names the protocol that accepted the request, and that
alone decides how the event is rebuilt for the dispatcher: a provider delivery
becomes the provider's canonical hook event, and a native event keeps its full
name as its type whatever that name says.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Final, cast

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventHomeKind, EventHomeRef
from teleclaude.events.references import ReferenceKind
from teleclaude.events.wire import StreamEvent
from teleclaude.hooks.dispatcher import HookDispatcher
from teleclaude.hooks.normalizers.github import github_hook_event
from teleclaude.hooks.normalizers.whatsapp import whatsapp_hook_event
from teleclaude.hooks.webhook_models import HookEvent

logger = get_logger(__name__)

# Each computer reads relayed events through its own consumer group on the cluster event stream.
_RELAY_DELIVERY_GROUP_PREFIX: Final = "relay-delivery-"
_DOMAIN_SEPARATOR = "."
_SOURCE_PROTOCOL_SEPARATOR = ":"
_NOT_RELAYED_ERROR = "event {event!r} is not a relayed event"
_COMPANY_PROPERTY = "company"
_NAME_PREFIX_ERROR = "relayed event {event!r} does not begin with its domain {domain!r}"


class RelayProtocol(StrEnum):
    """The protocols the ingress accepts, led by in a relayed event's subject identity."""

    NATIVE = "native"
    GITHUB = "github"
    WHATSAPP = "whatsapp"


def _domain(event: StreamEvent) -> str:
    """Return the relayed event's domain: the first segment of its type."""
    return event.type.split(_DOMAIN_SEPARATOR, 1)[0]


def _name_after_domain(event: StreamEvent) -> str:
    """Return the event name that follows its domain, ``<name>`` of ``<domain>.<name>``."""
    domain = _domain(event)
    prefix = domain + _DOMAIN_SEPARATOR
    if not event.type.startswith(prefix):
        raise ValueError(_NAME_PREFIX_ERROR.format(event=event.type, domain=domain))
    return event.type[len(prefix) :]


def _native_hook_event(event: StreamEvent) -> HookEvent:
    properties: dict[str, str | int | float | bool | list[str] | None] = {}
    home = event.home
    if isinstance(home, EventHomeRef) and home.kind is EventHomeKind.COMPANY:
        properties[_COMPANY_PROPERTY] = home.instance
    return HookEvent(
        source=_domain(event),
        type=event.type,
        timestamp=event.time.isoformat(),
        properties=properties,
        payload=event.data,
    )


def _relayed_payload(event: StreamEvent) -> dict[str, object]:  # guard: loose-dict - relayed payload is uninterpreted
    """Return the relayed request body as the provider normalizers take it."""
    return cast(dict[str, object], event.data)  # guard: loose-dict - relayed payload is uninterpreted


def _github_hook_event(event: StreamEvent) -> HookEvent:
    return github_hook_event(_name_after_domain(event), _relayed_payload(event), event.time.isoformat())


def _whatsapp_hook_event(event: StreamEvent) -> HookEvent:
    return whatsapp_hook_event(_name_after_domain(event), _relayed_payload(event))


def relay_delivery_group(computer: str) -> str:
    """The consumer group through which ``computer`` reads relayed events."""
    return _RELAY_DELIVERY_GROUP_PREFIX + computer


_REBUILDERS: Final[Mapping[RelayProtocol, Callable[[StreamEvent], HookEvent]]] = {
    RelayProtocol.NATIVE: _native_hook_event,
    RelayProtocol.GITHUB: _github_hook_event,
    RelayProtocol.WHATSAPP: _whatsapp_hook_event,
}


def relay_protocol(event: StreamEvent) -> RelayProtocol | None:
    """Return the protocol that accepted a relayed event, or None for an event that is not a relay.

    A relayed event's subject is the inbound source that received the request, and the
    source's identity leads with its protocol. An event from an older ingress computer states
    no subject; its protocol is the legacy producer label it still carries.
    """
    if event.subject is None:
        return RelayProtocol(event.legacy.producer) if event.legacy.producer in set(RelayProtocol) else None
    if not event.subject.is_kind(ReferenceKind.INBOUND_SOURCE):
        return None
    protocol, _, _ = event.subject.identity.partition(_SOURCE_PROTOCOL_SEPARATOR)
    return RelayProtocol(protocol) if protocol in set(RelayProtocol) else None


def relayed_hook_event(event: StreamEvent) -> HookEvent:
    """Rebuild the hook event a relayed event is delivered as; the event must be a relay."""
    protocol = relay_protocol(event)
    if protocol is None:
        raise ValueError(_NOT_RELAYED_ERROR.format(event=event.type))
    return _REBUILDERS[protocol](event)


class RelayDeliveryPipeline:
    """Deliver relayed events to the local hook dispatcher and acknowledge every other event untouched."""

    def __init__(self, dispatcher: HookDispatcher) -> None:
        self._dispatcher = dispatcher

    async def execute(self, event: StreamEvent, /) -> HookEvent | None:
        """Dispatch one relayed event; a failure escaping dispatch propagates to the processor's retry and DLQ."""
        if relay_protocol(event) is None:
            return None
        hook_event = relayed_hook_event(event)
        await self._dispatcher.dispatch(hook_event)
        return hook_event
