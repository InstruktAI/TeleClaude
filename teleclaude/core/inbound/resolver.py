"""Shared inbound resolve-or-create orchestrator: one seam for every UI adapter.

Mirrors ``core/delivery/router.py`` on the inbound side — this module has no
adapter imports (``software-development`` adapter-boundaries: core never
imports adapter modules).
"""

from __future__ import annotations

from teleclaude.core.models import Session

from .models import InboundSessionPolicy


def resolve_binding_key(origin: str, origin_metadata: dict[str, object]) -> str | None:  # guard: loose-dict
    """Derive the ``{origin}:{platform_user_id}`` identity key for an inbound message.

    Reads the flat, adapter-parsed metadata shape (``user_id`` /
    ``<origin>_user_id`` / ``phone_number``) — the shape adapters build before
    a session exists, distinct from a session's own nested ``origin_metadata``
    (see ``core.identity.derive_identity_key`` for that shape, still used by
    the hook receiver and memory extraction against live sessions).
    """
    user_id = (
        origin_metadata.get("user_id")
        or origin_metadata.get(f"{origin}_user_id")
        or origin_metadata.get("phone_number")
    )
    if not user_id:
        return None
    return f"{origin}:{user_id}"


async def resolve_or_create_bound_session(policy: InboundSessionPolicy) -> tuple[Session | None, bool]:
    """Find-or-create a session per ``policy``, returning the explicit ``is_new`` flag.

    ``is_new`` is True only when ``create`` produced the session this call —
    the signal ``handle_inbound_message`` uses to skip re-delivering a first
    message already bundled into the launch intent.
    """
    session = await policy.find()
    if session is not None:
        return await policy.reconcile(session), False

    created = await policy.create()
    if created is None:
        return None, False
    return await policy.reconcile(created), True


async def handle_inbound_message(policy: InboundSessionPolicy) -> Session | None:
    """Resolve-or-create a session and deliver the message, unless it was just bundled.

    Zero ``lifecycle_status`` check — ``is_new`` is the sole gate replacing the
    former ``initializing``-guard.
    """
    session, is_new = await resolve_or_create_bound_session(policy)
    if session is None:
        return None
    if is_new:
        return session
    await policy.dispatch(session)
    return session
