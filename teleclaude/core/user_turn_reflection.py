"""Project author-owned spans from a durable native-turn binding."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from teleclaude.core.conversation_messages import peer_segments_from_entry
from teleclaude.core.db import db
from teleclaude.core.identity import resolve_discord_author_alias
from teleclaude.core.inbound_types import TurnPartKind
from teleclaude.core.injected_text import UNSEEN_ENTRY_KINDS, TranscriptEntryKind, cut_transcript_entry, is_peer_opening

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session


@dataclass(frozen=True)
class TurnReflectionResult:
    """The receipts and disposition produced while projecting one bound turn."""

    platform_message_ids: tuple[str, ...]
    reflectable: bool
    failed: bool
    unbound: bool = False


SKIPPED_TURN_REFLECTION = TurnReflectionResult((), True, False)


async def reflect_user_turn_segments(
    session: Session,
    adapter_client: AdapterClient,
    *,
    user_text: str,
    source: str,
    binding_id: str | None,
    requires_binding: bool,
) -> TurnReflectionResult:
    """Reflect only the durable parts of a bound entry, in their stored order."""
    if binding_id is None:
        if not requires_binding:
            return await _reflect_unbound_legacy_segments(session, adapter_client, user_text, source)
        return TurnReflectionResult((), False, False, unbound=True)
    binding = await db.get_turn_binding(binding_id)
    if binding is None:
        return TurnReflectionResult((), False, False, unbound=True)
    platform_message_ids: list[str] = []
    failed = False
    for part in binding.parts:
        body = user_text[part.span_start : part.span_end]
        if not body.strip():
            continue
        try:
            if part.part_kind in (TurnPartKind.LOCAL, TurnPartKind.GITHUB):
                platform_message_ids.extend(await adapter_client.broadcast_user_input(session, body, source))
                continue
            actor_name, actor_avatar_url = resolve_discord_author_alias(
                part.author,
                owning_session_id=session.session_id,
                job_role=part.author_job_role,
            )
            message_id = await adapter_client.broadcast_peer_reflection(
                session,
                body,
                actor_name=actor_name,
                actor_avatar_url=actor_avatar_url,
            )
            if message_id is not None:
                platform_message_ids.append(message_id)
            else:
                failed = True
        except ValueError:
            failed = True
    return TurnReflectionResult(tuple(platform_message_ids), bool(binding.parts), failed)


async def _reflect_unbound_legacy_segments(
    session: Session,
    adapter_client: AdapterClient,
    user_text: str,
    source: str,
) -> TurnReflectionResult:
    """Preserve peer and local projection while keyless caller headers fail closed."""
    platform_message_ids: list[str] = []
    reflectable = failed = False
    for segment in cut_transcript_entry(user_text, is_user_entry=True):
        if segment.kind in UNSEEN_ENTRY_KINDS:
            continue
        if segment.kind is TranscriptEntryKind.IDENTITY_CONTENT:
            if not is_peer_opening(segment.opening or ""):
                continue
            peer = peer_segments_from_entry(segment.text, occurred_at=datetime.now(UTC))[0]
            actor_name, actor_avatar_url = resolve_discord_author_alias(
                peer.author,
                owning_session_id=session.session_id,
                job_role=peer.author_job_role,
            )
            reflectable = True
            message_id = await adapter_client.broadcast_peer_reflection(
                session, peer.body, actor_name=actor_name, actor_avatar_url=actor_avatar_url
            )
            if message_id is None:
                failed = True
            else:
                platform_message_ids.append(message_id)
            continue
        if not segment.text.strip():
            continue
        reflectable = True
        try:
            platform_message_ids.extend(await adapter_client.broadcast_user_input(session, segment.text, source))
        except ValueError:
            failed = True
    return TurnReflectionResult(tuple(platform_message_ids), reflectable, failed)
