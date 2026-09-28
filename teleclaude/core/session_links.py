"""Conversation-link ownership and lifecycle for live session pairs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.db_models import ConversationLinkMode
from teleclaude.core.inbound_errors import DirectLinkExclusivityError

logger = get_logger(__name__)
_ENDPOINT_LOCKS: dict[str, asyncio.Lock] = {}
_ENDPOINT_LOCKS_GUARD = asyncio.Lock()


@dataclass
class ConversationLink:
    """Conversation link metadata."""

    link_id: str
    mode: ConversationLinkMode
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


async def _get_endpoint_lock(session_id: str) -> asyncio.Lock:
    """Return the shared lock guarding one session's direct-link membership."""
    async with _ENDPOINT_LOCKS_GUARD:
        lock = _ENDPOINT_LOCKS.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            _ENDPOINT_LOCKS[session_id] = lock
        return lock


@asynccontextmanager
async def _direct_link_endpoints_locked(session_a: str, session_b: str) -> AsyncIterator[None]:
    """Hold both endpoints' locks so exclusivity is decided atomically with creation."""
    first, second = sorted((session_a, session_b))
    first_lock = await _get_endpoint_lock(first)
    second_lock = await _get_endpoint_lock(second) if second != first else None
    async with first_lock:
        if second_lock is None:
            yield
            return
        async with second_lock:
            yield


def _to_conversation_link(row: object) -> ConversationLink:
    """Convert one persisted row to its link contract."""
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
        mode=ConversationLinkMode(str(getattr(row, "mode", ""))),
        status=str(getattr(row, "status", "")),
        created_by_session_id=str(getattr(row, "created_by_session_id", "")),
        created_at=datetime.fromisoformat(str(getattr(row, "created_at", ""))),
        updated_at=datetime.fromisoformat(str(getattr(row, "updated_at", ""))),
        closed_at=closed_at,
        metadata=metadata,
    )


def _to_conversation_link_member(row: object) -> ConversationLinkMember:
    """Convert one persisted row to its link-member contract."""
    return ConversationLinkMember(
        link_id=str(getattr(row, "link_id", "")),
        session_id=str(getattr(row, "session_id", "")),
        participant_name=getattr(row, "participant_name", None),
        participant_number=getattr(row, "participant_number", None),
        participant_role=getattr(row, "participant_role", None),
        computer_name=getattr(row, "computer_name", None),
        joined_at=datetime.fromisoformat(str(getattr(row, "joined_at", ""))),
    )


async def create_link(
    *,
    mode: ConversationLinkMode,
    created_by_session_id: str,
    metadata: dict[str, object] | None = None,  # guard: loose-dict - persisted metadata payload.
) -> ConversationLink:
    """Create a conversation link."""
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
    rows = await db.list_conversation_link_members(link_id)
    return [_to_conversation_link_member(row) for row in rows]


async def get_link(link_id: str) -> ConversationLink | None:
    """Get link by ID."""
    row = await db.get_conversation_link(link_id)
    return _to_conversation_link(row) if row is not None else None


async def get_active_links_for_session(session_id: str) -> list[ConversationLink]:
    """Get active links containing the provided member session."""
    try:
        rows = await db.get_active_links_for_session(session_id)
    except RuntimeError:
        logger.debug("Link lookup skipped (db not initialized) for session %s", session_id)
        return []
    return [_to_conversation_link(row) for row in rows]


async def active_direct_peer(
    session_id: str,
    *,
    allowed_peer_session_id: str | None = None,
) -> ConversationLinkMember | None:
    """Return the peer holding this session in a direct conversation, if any."""
    for link in await get_active_links_for_session(session_id):
        if link.mode != ConversationLinkMode.DIRECT:
            continue
        members = await get_link_members(link.link_id)
        peers = [member for member in members if member.session_id != session_id]
        if allowed_peer_session_id is not None and any(peer.session_id == allowed_peer_session_id for peer in peers):
            continue
        if peers:
            return peers[0]
    return None


async def create_or_reuse_direct_link(
    *,
    caller_session_id: str,
    target_session_id: str,
    caller_name: str | None = None,
    target_name: str | None = None,
    caller_computer: str | None = None,
    target_computer: str | None = None,
) -> tuple[ConversationLink, bool]:
    """Create or reuse a direct link while enforcing endpoint exclusivity."""
    async with _direct_link_endpoints_locked(caller_session_id, target_session_id):
        existing_links = await db.get_active_links_between_sessions(
            caller_session_id,
            target_session_id,
            mode=ConversationLinkMode.DIRECT,
        )
        if not existing_links:
            for endpoint_id, other_id in (
                (caller_session_id, target_session_id),
                (target_session_id, caller_session_id),
            ):
                blocking_peer = await active_direct_peer(endpoint_id, allowed_peer_session_id=other_id)
                if blocking_peer is not None:
                    raise DirectLinkExclusivityError(
                        endpoint_session_id=endpoint_id,
                        peer_session_id=blocking_peer.session_id,
                        peer_name=blocking_peer.participant_name,
                        link_id=blocking_peer.link_id,
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
            return _to_conversation_link(existing), False

        link = await create_link(mode=ConversationLinkMode.DIRECT, created_by_session_id=caller_session_id)
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
        now_iso = datetime.now(UTC).isoformat()
        await db.upsert_conversation_delivery_state(
            link_id=link.link_id,
            source_session_id=caller_session_id,
            target_session_id=target_session_id,
            delivered_through_ts=now_iso,
        )
        await db.upsert_conversation_delivery_state(
            link_id=link.link_id,
            source_session_id=target_session_id,
            target_session_id=caller_session_id,
            delivered_through_ts=now_iso,
        )
        refreshed = await db.get_conversation_link(link.link_id)
        return (_to_conversation_link(refreshed), True) if refreshed is not None else (link, True)


async def resolve_link_for_sender_target(
    *,
    sender_session_id: str,
    target_session_id: str,
) -> tuple[ConversationLink, list[ConversationLinkMember]] | None:
    """Find active link containing sender and target."""
    for link in await get_active_links_for_session(sender_session_id):
        members = await get_link_members(link.link_id)
        if any(member.session_id == target_session_id for member in members):
            return link, members
    return None


async def get_peer_members(*, link_id: str, sender_session_id: str) -> list[ConversationLinkMember]:
    """Get all active members except sender."""
    members = await get_link_members(link_id)
    return [member for member in members if member.session_id != sender_session_id]


async def close_link(link_id: str) -> bool:
    """Sever a shared link for all members."""
    return await db.sever_conversation_link(link_id)


async def close_link_for_member(
    *,
    caller_session_id: str,
    target_session_id: str | None = None,
) -> str | None:
    """Close a link if caller is a member (optionally scoped by target member)."""
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
    try:
        return await db.cleanup_conversation_links_for_session(session_id)
    except RuntimeError:
        logger.debug("Link cleanup skipped (db not initialized) for session %s", session_id)
        return 0
