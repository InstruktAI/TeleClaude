"""Event scopes: which Redis an event lives on (``local/projects/teleclaude/design/architecture/event-delivery``).

A declared platform event type is local unless a consumer on another computer acts on it; then it is cluster.
A relayed type, whose name the platform catalog does not declare, is cluster: it enters on the ingress computer
for the consumers of every computer. A consumer reads from the Redis of every scope its interest can select.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib import import_module
from typing import Final

from teleclaude.events.type_pattern import ANY_TYPE, TypePattern

_CATALOG_MODULE: Final = "teleclaude.events.catalog"
_CATALOG_BUILDER: Final = "build_default_catalog"


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
    catalog = getattr(import_module(_CATALOG_MODULE), _CATALOG_BUILDER)()
    return frozenset(declaration.name for declaration in catalog.list_all())


def scope_of(event_type: str) -> EventScope:
    """The scope of one event type: cluster for the listed and the relayed types, local for every other."""
    if event_type in CLUSTER_EVENT_TYPES or event_type not in _declared_types():
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
        if not matched or any(event_type in CLUSTER_EVENT_TYPES for event_type in matched):
            # A pattern no declared type answers selects relayed types.
            scopes.add(EventScope.CLUSTER)
    return frozenset(scopes)


@dataclass(frozen=True)
class ScopedClients[ClientT]:
    """One client per scope: this computer's local Redis and the shared cluster Redis."""

    local: ClientT
    cluster: ClientT

    def for_scope(self, scope: EventScope) -> ClientT:
        """The client of one scope."""
        return self.local if scope is EventScope.LOCAL else self.cluster
