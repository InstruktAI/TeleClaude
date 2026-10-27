"""Event scopes: which Redis an event lives on (``local/projects/teleclaude/design/architecture/event-delivery``).

A platform event type is local unless a consumer on another computer acts on it; then it is cluster. A relayed
event is cluster: it enters on the ingress computer for the consumers of every computer, and a type outside every
namespace the platform declares is a relayed type. A consumer reads from the Redis of every scope its interest can
select.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib import import_module
from typing import TYPE_CHECKING, Final, Protocol, cast

from teleclaude.events.type_pattern import ANY_TYPE, TypePattern

_CATALOG_MODULE: Final = "teleclaude.events.catalog"
_NAMESPACE_SEPARATOR: Final = "."
_FAMILY_SUFFIX: Final = ".*"

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


class _CatalogModule(Protocol):
    def build_default_catalog(self) -> EventCatalog: ...


class EventScope(StrEnum):
    """The scope that decides which Redis carries an event."""

    LOCAL = "local"
    CLUSTER = "cluster"


#: The declared types a consumer on another computer acts on. A new cross-computer consumer adds its types here.
CLUSTER_EVENT_TYPES: Final = frozenset(
    {
        # Installation reaction admits a passed revision on every computer.
        "teleclaude.ci.revision.passed",
        # Views of another computer's sessions: WebSocket status, activity and errors, and Discord voice.
        "teleclaude.agent_runtime.session.status_changed",
        "teleclaude.agent_runtime.agent.activity_observed",
        "teleclaude.agent_runtime.error.reported",
        # The earlier internal wire, whose session-close request acts on the computer that holds the session.
        "teleclaude.internal.compat.ingress",
    }
)


@cache
def _declared_types() -> frozenset[str]:
    # The catalog imports every schema module, so it is loaded on first use instead of at import.
    catalog_module = cast("_CatalogModule", import_module(_CATALOG_MODULE))
    return frozenset(declaration.name for declaration in catalog_module.build_default_catalog().list_all())


@cache
def _platform_namespaces() -> frozenset[str]:
    return frozenset(event_type.split(_NAMESPACE_SEPARATOR, 1)[0] for event_type in _declared_types())


def scope_of(event_type: str) -> EventScope:
    """The scope of one event type: cluster for the listed types and for relayed types outside the platform's namespaces.

    A platform type the catalog no longer declares, such as a retired one, stays local.
    """
    if event_type in CLUSTER_EVENT_TYPES:
        return EventScope.CLUSTER
    if event_type.split(_NAMESPACE_SEPARATOR, 1)[0] not in _platform_namespaces():
        return EventScope.CLUSTER
    return EventScope.LOCAL


def scopes_of_interest(patterns: Iterable[TypePattern]) -> frozenset[EventScope]:
    """The scopes whose Redis a consumer reads to receive every type its patterns select."""
    scopes: set[EventScope] = set()
    declared = _declared_types()
    for pattern in patterns:
        if pattern == ANY_TYPE:
            return frozenset(EventScope)
        matched = [event_type for event_type in declared if pattern.matches(event_type)]
        scopes.update(scope_of(event_type) for event_type in matched)
        if any(pattern.matches(event_type) for event_type in CLUSTER_EVENT_TYPES):
            scopes.add(EventScope.CLUSTER)
        if not matched:
            # A pattern no declared type answers names a relayed type, or a retired platform type.
            scopes.add(scope_of(pattern.text.removesuffix(_FAMILY_SUFFIX)))
    return frozenset(scopes)


@dataclass(frozen=True)
class ScopedClients[ClientT]:
    """One client per scope: this computer's local Redis and the shared cluster Redis."""

    local: ClientT
    cluster: ClientT

    def for_scope(self, scope: EventScope) -> ClientT:
        """The client of one scope."""
        return self.local if scope is EventScope.LOCAL else self.cluster

    def distinct(self) -> tuple[ClientT, ...]:
        """Each client once; a local scope that shares the cluster client is one client."""
        return (self.local,) if self.local is self.cluster else (self.local, self.cluster)
