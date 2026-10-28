"""Project caller, peer and local spans directly from their native envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from teleclaude.core.conversation_messages import peer_segments_from_entry
from teleclaude.core.identity import resolve_discord_author_alias, resolve_discord_caller_header_alias
from teleclaude.core.injected_text import UNSEEN_ENTRY_KINDS, TranscriptEntryKind, cut_transcript_entry, is_peer_opening

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session


@dataclass(frozen=True)
class TurnReflectionResult:
    """The receipts and disposition produced while projecting one native turn."""

    platform_message_ids: tuple[str, ...]
    reflectable: bool
    failed: bool


SKIPPED_TURN_REFLECTION = TurnReflectionResult((), True, False)


async def reflect_user_turn_segments(
    session: Session,
    adapter_client: AdapterClient,
    *,
    user_text: str,
    source: str,
) -> TurnReflectionResult:
    """Reflect each visible structural segment in source order under its carried author."""
    platform_message_ids: list[str] = []
    reflectable = failed = False
    for segment in cut_transcript_entry(user_text, is_user_entry=True):
        if segment.kind in UNSEEN_ENTRY_KINDS:
            continue
        if segment.kind is TranscriptEntryKind.IDENTITY_CONTENT:
            assert segment.opening is not None and segment.body_span is not None
            if is_peer_opening(segment.opening):
                peer = peer_segments_from_entry(segment.text, occurred_at=datetime.now(UTC))[0]
                actor_name, actor_avatar_url = resolve_discord_author_alias(
                    peer.author,
                    owning_session_id=session.session_id,
                    job_role=peer.author_job_role,
                )
            else:
                actor_name, actor_avatar_url = resolve_discord_caller_header_alias(
                    segment.opening, owning_session_id=session.session_id
                )
            body = user_text[segment.body_span[0] : segment.body_span[1]]
            reflectable = True
            message_id = await adapter_client.broadcast_peer_reflection(
                session, body, actor_name=actor_name, actor_avatar_url=actor_avatar_url
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
