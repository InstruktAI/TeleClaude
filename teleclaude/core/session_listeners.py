"""Session listeners for PUB-SUB notification on Stop events.

When an AI starts or sends a message to another session, it can register a listener.
When the target session stops, ALL listeners fire and notify their callers via tmux injection.
Listeners are one-shot (removed after firing) and session-scoped (cleaned up when caller exits).

Multiple callers can wait for the same target session (e.g., 4 AI workers waiting for a dependency).
Only one listener per caller-target pair is allowed (deduped by caller, not by target).

Storage is SQLite-backed so listeners survive daemon restarts.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from instrukt_ai_logging import get_logger

from teleclaude.constants import LOCAL_COMPUTER

logger = get_logger(__name__)
_PAIR_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}
_PAIR_LOCKS_GUARD = asyncio.Lock()


@dataclass
class SessionListener:
    """A listener waiting for a target session to stop."""

    target_session_id: str  # Session being listened to
    caller_session_id: str  # Session that wants to be notified
    caller_tmux_session: str  # Tmux session name for injection
    registered_at: datetime


@dataclass
class ConversationLink:
    """Conversation link metadata."""

    link_id: str
    mode: str
    status: str
    created_by_session_id: str
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    metadata: dict[str, object] | None  # guard: loose-dict - persisted link metadata JSON.


@dataclass
class ConversationLinkMember:
    """Conversation link member metadata."""

    link_id: str
    session_id: str
    participant_name: str | None
    participant_number: int | None
    participant_role: str | None
    computer_name: str | None
    joined_at: datetime


async def _get_pair_lock(session_a: str, session_b: str) -> asyncio.Lock:
    """Return a shared lock for a canonical direct-link session pair."""
    key = tuple(sorted((session_a, session_b)))
    async with _PAIR_LOCKS_GUARD:
        lock = _PAIR_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _PAIR_LOCKS[key] = lock
        return lock


def _to_conversation_link(row: object) -> ConversationLink:
    metadata: dict[str, object] | None = None  # guard: loose-dict - metadata JSON from DB.
    raw_metadata = getattr(row, "metadata_json", None)
    if isinstance(raw_metadata, str) and raw_metadata:
        try:
            parsed = json.loads(raw_metadata)
            if isinstance(parsed, dict):
                metadata = parsed
        except json.JSONDecodeError:
            metadata = None

    closed_at_raw = getattr(row, "closed_at", None)
    closed_at = datetime.fromisoformat(closed_at_raw) if isinstance(closed_at_raw, str) and closed_at_raw else None

    return ConversationLink(
        link_id=str(getattr(row, "link_id", "")),
        mode=str(getattr(row, "mode", "")),
        status=str(getattr(row, "status", "")),
        created_by_session_id=str(getattr(row, "created_by_session_id", "")),
        created_at=datetime.fromisoformat(str(getattr(row, "created_at", ""))),
        updated_at=datetime.fromisoformat(str(getattr(row, "updated_at", ""))),
        closed_at=closed_at,
        metadata=metadata,
    )


def _to_conversation_link_member(row: object) -> ConversationLinkMember:
    return ConversationLinkMember(
        link_id=str(getattr(row, "link_id", "")),
        session_id=str(getattr(row, "session_id", "")),
        participant_name=getattr(row, "participant_name", None),
        participant_number=getattr(row, "participant_number", None),
        participant_role=getattr(row, "participant_role", None),
        computer_name=getattr(row, "computer_name", None),
        joined_at=datetime.fromisoformat(str(getattr(row, "joined_at", ""))),
    )


async def register_listener(
    target_session_id: str,
    caller_session_id: str,
    caller_tmux_session: str,
) -> bool:
    """Register a listener for a target session's Stop event.

    Multiple callers can register for the same target.
    Only one listener per caller-target pair (deduped by caller_session_id).

    Args:
        target_session_id: The session to listen to
        caller_session_id: The session that wants notification
        caller_tmux_session: Tmux session name for message injection

    Returns:
        True if listener was newly registered, False if this caller already has one
    """
    from teleclaude.core.db import db

    is_new = await db.register_listener(
        target_session_id=target_session_id,
        caller_session_id=caller_session_id,
        caller_tmux_session=caller_tmux_session,
    )

    if is_new:
        listeners = await db.get_listeners_for_target(target_session_id)
        logger.info(
            "Registered listener: caller=%s -> target=%s (total: %d)",
            caller_session_id[:8],
            target_session_id[:8],
            len(listeners),
        )
        logger.debug(
            "Listener map snapshot: target=%s callers=%s",
            target_session_id[:8],
            ",".join(row.caller_session_id[:8] for row in listeners),
        )
    else:
        logger.debug(
            "Listener already exists: caller=%s -> target=%s",
            caller_session_id[:8],
            target_session_id[:8],
        )

    return is_new


async def unregister_listener(target_session_id: str, caller_session_id: str) -> bool:
    """Unregister a specific listener for a target session.

    Removes the listener registered by a specific caller for a specific target.
    This allows an AI to stop receiving notifications from a session without ending it.

    Args:
        target_session_id: The session to stop listening to
        caller_session_id: The session that wants to unsubscribe

    Returns:
        True if listener was found and removed, False if no such listener exists
    """
    from teleclaude.core.db import db

    removed = await db.unregister_listener(target_session_id, caller_session_id)
    if removed:
        logger.info(
            "Unregistered listener: caller=%s -> target=%s",
            caller_session_id[:8],
            target_session_id[:8],
        )
    else:
        logger.debug(
            "No listener found for caller=%s -> target=%s",
            caller_session_id[:8],
            target_session_id[:8],
        )
    return removed


async def get_listeners(target_session_id: str) -> list[SessionListener]:
    """Get all listeners for a target session."""
    from teleclaude.core.db import db

    rows = await db.get_listeners_for_target(target_session_id)
    return [
        SessionListener(
            target_session_id=row.target_session_id,
            caller_session_id=row.caller_session_id,
            caller_tmux_session=row.caller_tmux_session,
            registered_at=datetime.fromisoformat(row.registered_at),
        )
        for row in rows
    ]


async def pop_listeners(target_session_id: str) -> list[SessionListener]:
    """Remove and return all listeners for a target session (one-shot pattern).

    Called when target session stops - all callers get notified, then listeners are removed.

    Args:
        target_session_id: The session whose listeners should be removed

    Returns:
        List of removed listeners (may be empty)
    """
    from teleclaude.core.db import db

    rows = await db.pop_listeners_for_target(target_session_id)
    listeners = [
        SessionListener(
            target_session_id=row.target_session_id,
            caller_session_id=row.caller_session_id,
            caller_tmux_session=row.caller_tmux_session,
            registered_at=datetime.fromisoformat(row.registered_at),
        )
        for row in rows
    ]
    if listeners:
        logger.info(
            "Popped %d listener(s) for target %s",
            len(listeners),
            target_session_id[:8],
        )
    else:
        logger.debug("Pop listeners: none for target %s", target_session_id[:8])
    return listeners


async def cleanup_caller_listeners(caller_session_id: str) -> int:
    """Remove all listeners registered by a specific caller session.

    Called when a caller session ends to clean up its listeners.

    Args:
        caller_session_id: The session whose listeners should be removed

    Returns:
        Number of listeners removed
    """
    from teleclaude.core.db import db

    count = await db.cleanup_caller_listeners(caller_session_id)
    if count:
        logger.info(
            "Cleaned up %d listener(s) for caller session %s",
            count,
            caller_session_id[:8],
        )
    return count


async def get_all_listeners() -> dict[str, list[SessionListener]]:
    """Get all active listeners (for debugging/monitoring)."""
    from teleclaude.core.db import db

    rows = await db.get_all_listeners()
    result: dict[str, list[SessionListener]] = {}
    for row in rows:
        listener = SessionListener(
            target_session_id=row.target_session_id,
            caller_session_id=row.caller_session_id,
            caller_tmux_session=row.caller_tmux_session,
            registered_at=datetime.fromisoformat(row.registered_at),
        )
        result.setdefault(row.target_session_id, []).append(listener)
    return result


async def get_listeners_for_caller(caller_session_id: str) -> list[SessionListener]:
    """Get all listeners registered by a specific caller."""
    from teleclaude.core.db import db

    rows = await db.get_listeners_for_caller(caller_session_id)
    return [
        SessionListener(
            target_session_id=row.target_session_id,
            caller_session_id=row.caller_session_id,
            caller_tmux_session=row.caller_tmux_session,
            registered_at=datetime.fromisoformat(row.registered_at),
        )
        for row in rows
    ]


async def count_listeners() -> int:
    """Get total number of active listeners."""
    from teleclaude.core.db import db

    return await db.count_listeners()


async def get_stale_targets(max_age_minutes: int = 10) -> list[str]:
    """Get target session IDs with listeners older than max_age_minutes.

    Returns unique target session IDs where at least one listener has been
    waiting longer than the threshold. Used for periodic health checks.

    After returning, the listener's registered_at is reset to prevent
    repeated health checks every minute.

    Args:
        max_age_minutes: Maximum age in minutes before a listener is considered stale

    Returns:
        List of target session IDs that need health checks
    """
    from teleclaude.core.db import db

    threshold = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    threshold_iso = threshold.isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()

    stale_targets = await db.get_stale_listener_targets(threshold_iso)

    if stale_targets:
        logger.info("Found %d stale target(s) for health check", len(stale_targets))
        # Reset timestamps to prevent repeated checks
        for target_id in stale_targets:
            await db.reset_listener_timestamps(target_id, now_iso)

    return stale_targets


async def _notify_listeners(target_session_id: str, message: str) -> int:
    """Internal: notify all listeners with a pre-built message.

    Args:
        target_session_id: Session whose listeners to notify
        message: The notification message to send

    Returns:
        Number of listeners successfully notified
    """
    from teleclaude.core.tmux_delivery import deliver_listener_message

    listeners = await get_listeners(target_session_id)
    if not listeners:
        logger.debug("No listeners for session %s", target_session_id[:8])
        return 0

    preview = message.replace("\n", "\\n")[:160]
    logger.debug(
        "Notify listeners: target=%s callers=%s message_preview=%r",
        target_session_id[:8],
        ",".join(listener.caller_session_id[:8] for listener in listeners),
        preview,
    )
    success_count = 0
    for listener in listeners:
        delivered = await deliver_listener_message(
            listener.caller_session_id,
            listener.caller_tmux_session,
            message,
        )
        if delivered:
            logger.info("Notified caller %s", listener.caller_session_id[:8])
            success_count += 1
        else:
            logger.warning("Failed to notify caller %s", listener.caller_session_id[:8])

    return success_count


async def notify_stop(
    target_session_id: str,
    computer: str,
    title: str | None = None,
) -> int:
    """Notify listeners that a session finished its turn.

    Args:
        target_session_id: Session that finished
        computer: Computer name where session runs (for actionable command)
        title: Optional title/summary of the turn

    Returns:
        Number of listeners successfully notified
    """
    title_part = f' "{title}"' if title else ""
    location_part = f" on {computer}" if computer != LOCAL_COMPUTER else ""
    message = (
        f"Session {target_session_id[:8]}{location_part}{title_part} finished its turn. "
        f"Use teleclaude__get_session_data(computer='{computer}', "
        f"session_id='{target_session_id}') to inspect."
    )
    return await _notify_listeners(target_session_id, message)


async def notify_input_request(
    target_session_id: str,
    computer: str,
    input_message: str,
) -> int:
    """Notify listeners that a session needs input.

    Args:
        target_session_id: Session that needs input
        computer: Computer name where session runs (for actionable command)
        input_message: The input request message from the session

    Returns:
        Number of listeners successfully notified
    """
    message = (
        f"Session {target_session_id[:8]} on {computer} needs input: {input_message} "
        f"Use teleclaude__send_message(computer='{computer}', session_id='{target_session_id}', "
        f"message='your response') to respond."
    )
    return await _notify_listeners(target_session_id, message)


async def create_link(
    *,
    mode: Literal["direct_link", "gathering_link"],
    created_by_session_id: str,
    metadata: dict[str, object] | None = None,  # guard: loose-dict - persisted metadata payload.
) -> ConversationLink:
    """Create a conversation link."""
    from teleclaude.core.db import db

    metadata_json = json.dumps(metadata) if metadata is not None else None
    row = await db.create_conversation_link(
        mode=mode,
        created_by_session_id=created_by_session_id,
        metadata_json=metadata_json,
    )
    return _to_conversation_link(row)


async def add_link_member(
    *,
    link_id: str,
    session_id: str,
    participant_name: str | None = None,
    participant_number: int | None = None,
    participant_role: str | None = None,
    computer_name: str | None = None,
) -> None:
    """Create or update a link member."""
    from teleclaude.core.db import db

    await db.upsert_conversation_link_member(
        link_id=link_id,
        session_id=session_id,
        participant_name=participant_name,
        participant_number=participant_number,
        participant_role=participant_role,
        computer_name=computer_name,
    )


async def get_link_members(link_id: str) -> list[ConversationLinkMember]:
    """List members for a link."""
    from teleclaude.core.db import db

    rows = await db.list_conversation_link_members(link_id)
    return [_to_conversation_link_member(row) for row in rows]


async def get_link(link_id: str) -> ConversationLink | None:
    """Get link by ID."""
    from teleclaude.core.db import db

    row = await db.get_conversation_link(link_id)
    if row is None:
        return None
    return _to_conversation_link(row)


async def get_active_links_for_session(session_id: str) -> list[ConversationLink]:
    """Get active links containing the provided member session."""
    from teleclaude.core.db import db

    try:
        rows = await db.get_active_links_for_session(session_id)
    except RuntimeError:
        logger.debug("Link lookup skipped (db not initialized) for session %s", session_id[:8])
        return []
    return [_to_conversation_link(row) for row in rows]


async def create_or_reuse_direct_link(
    *,
    caller_session_id: str,
    target_session_id: str,
    caller_name: str | None = None,
    target_name: str | None = None,
    caller_computer: str | None = None,
    target_computer: str | None = None,
) -> tuple[ConversationLink, bool]:
    """Create or reuse an active two-member direct link."""
    from teleclaude.core.db import db

    pair_lock = await _get_pair_lock(caller_session_id, target_session_id)
    async with pair_lock:
        existing_links = await db.get_active_links_between_sessions(
            caller_session_id,
            target_session_id,
            mode="direct_link",
        )
        if existing_links:
            existing = existing_links[0]
            for duplicate in existing_links[1:]:
                await db.sever_conversation_link(duplicate.link_id)

            await add_link_member(
                link_id=existing.link_id,
                session_id=caller_session_id,
                participant_name=caller_name,
                participant_number=1,
                participant_role="peer",
                computer_name=caller_computer,
            )
            await add_link_member(
                link_id=existing.link_id,
                session_id=target_session_id,
                participant_name=target_name,
                participant_number=2,
                participant_role="peer",
                computer_name=target_computer,
            )
            return (_to_conversation_link(existing), False)

        link = await create_link(mode="direct_link", created_by_session_id=caller_session_id)
        await add_link_member(
            link_id=link.link_id,
            session_id=caller_session_id,
            participant_name=caller_name,
            participant_number=1,
            participant_role="peer",
            computer_name=caller_computer,
        )
        await add_link_member(
            link_id=link.link_id,
            session_id=target_session_id,
            participant_name=target_name,
            participant_number=2,
            participant_role="peer",
            computer_name=target_computer,
        )
        refreshed = await db.get_conversation_link(link.link_id)
        if refreshed is None:
            return (link, True)
        return (_to_conversation_link(refreshed), True)


async def resolve_link_for_sender_target(
    *,
    sender_session_id: str,
    target_session_id: str,
) -> tuple[ConversationLink, list[ConversationLinkMember]] | None:
    """Find active link containing sender and target."""
    links = await get_active_links_for_session(sender_session_id)
    for link in links:
        members = await get_link_members(link.link_id)
        if any(member.session_id == target_session_id for member in members):
            return (link, members)
    return None


async def get_peer_members(
    *,
    link_id: str,
    sender_session_id: str,
) -> list[ConversationLinkMember]:
    """Get all active members except sender."""
    members = await get_link_members(link_id)
    return [member for member in members if member.session_id != sender_session_id]


async def close_link(link_id: str) -> bool:
    """Sever a shared link for all members."""
    from teleclaude.core.db import db

    return await db.sever_conversation_link(link_id)


async def close_link_for_member(
    *,
    caller_session_id: str,
    target_session_id: str | None = None,
) -> str | None:
    """Close a link if caller is a member (optionally scoped by target member)."""
    from teleclaude.core.db import db

    if target_session_id:
        links = await db.get_active_links_between_sessions(caller_session_id, target_session_id)
        if not links:
            return None
        for link in links:
            await db.sever_conversation_link(link.link_id)
        return links[0].link_id

    links = await db.get_active_links_for_session(caller_session_id)
    if not links:
        return None
    link = links[0]
    await db.sever_conversation_link(link.link_id)
    return link.link_id


async def cleanup_session_links(session_id: str) -> int:
    """Sever all active links involving this session."""
    from teleclaude.core.db import db

    try:
        return await db.cleanup_conversation_links_for_session(session_id)
    except RuntimeError:
        logger.debug("Link cleanup skipped (db not initialized) for session %s", session_id[:8])
        return 0
