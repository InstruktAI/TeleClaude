"""Value objects for the origin-addressed inbound resolve-or-create seam.

Mirrors ``core/delivery/models.py`` on the inbound side — see
docs/project/design/architecture/ui-adapter.md for the resolve-or-create
seam invariants these types implement.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from teleclaude.core.models import Session


@dataclass(frozen=True)
class InboundBinding:
    """A resolved inbound identity: the platform origin plus its binding key.

    Mirrors ``Destination`` on the outbound side — the concrete identity
    coords an adapter's resolve-or-create policy is scoped to, without
    carrying a ``Session``.
    """

    origin: str
    origin_metadata: dict[str, object]  # guard: loose-dict - adapter-parsed inbound payload
    binding_key: str | None = None


async def _no_dispatch(_session: Session) -> None:
    """Default for callers that only need `resolve_or_create_bound_session`'s explicit is_new.

    Some adapter paths (e.g. Discord guild messages) gate delivery behind extra,
    path-specific checks (authorization, relay-diversion) that must run between
    resolve-or-create and delivery, so they call the resolver directly instead of
    `handle_inbound_message` and never invoke `dispatch`.
    """


@dataclass(frozen=True)
class InboundSessionPolicy:
    """Adapter-supplied resolve-or-create callbacks feeding the shared seam.

    Parameterizes the one divergent piece across platforms — project/workspace
    resolution and launch-intent construction differ per adapter — as
    callbacks rather than a per-adapter fork of the orchestration.
    """

    find: Callable[[], Awaitable[Session | None]]
    create: Callable[[], Awaitable[Session | None]]
    reconcile: Callable[[Session], Awaitable[Session]]
    dispatch: Callable[[Session], Awaitable[None]] = _no_dispatch
