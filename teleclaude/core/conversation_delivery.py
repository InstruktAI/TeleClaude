"""Restart-safe conversation replay based on transcript truth and directional cursors."""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import LOCAL_COMPUTER
from teleclaude.core.agents import AgentName
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.conversation_messages import format_bundled_conversation_message
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import get_active_links_for_session, get_peer_members
from teleclaude.output_projection.conversation_projector import project_entries
from teleclaude.output_projection.models import WEB_POLICY
from teleclaude.types.commands import ProcessMessageCommand
from teleclaude.utils.transcript import _get_entries_for_agent, _parse_timestamp

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.command_service import CommandService
    from teleclaude.core.models import Session

logger = get_logger(__name__)


@dataclass(frozen=True)
class ConversationSegment:
    """Visible conversation content that should be mirrored to linked peers."""

    role: str
    text: str
    timestamp: datetime | None


def _later_timestamp(first: datetime | None, second: datetime | None) -> datetime | None:
    """Return the later of two optional timestamps."""
    if first is None:
        return second
    if second is None:
        return first
    return first if first >= second else second


def _delivery_key(
    *,
    link_id: str,
    source_session_id: str,
    target_session_id: str,
    role: str,
    from_timestamp: datetime,
    to_timestamp: datetime | None,
) -> str:
    """Build a deterministic dedupe key for one mirrored conversation slice."""
    to_iso = to_timestamp.isoformat() if to_timestamp else "-"
    return f"linked:{link_id}:{source_session_id}:{target_session_id}:{role}:{from_timestamp.isoformat()}:{to_iso}"


def _target_computer_name(peer_computer_name: str | None) -> str:
    """Normalize the peer routing computer name."""
    if not peer_computer_name or peer_computer_name in {LOCAL_COMPUTER, "local"}:
        return config.computer.name
    return peer_computer_name


def _sender_identity(
    source_session: Session,
    *,
    source_computer: str | None,
) -> tuple[str, str, str]:
    """Build sender display and actor identity values."""
    sender_label = source_session.title or source_session.session_id
    sender_computer = source_computer or source_session.computer_name or config.computer.name
    actor_id = f"system:{sender_computer}:{source_session.session_id}"
    return sender_label, sender_computer, actor_id


async def _collect_visible_conversation_segments_since(
    transcript_path: str,
    agent_name: AgentName,
    since_timestamp: datetime,
) -> list[ConversationSegment]:
    """Collect visible user and assistant text after the provided cursor."""

    def _collect() -> list[ConversationSegment]:
        entries = _get_entries_for_agent(transcript_path, agent_name)
        if not entries:
            return []

        segments: list[ConversationSegment] = []
        current_role: str | None = None
        current_parts: list[str] = []
        current_timestamp: datetime | None = None

        for block in project_entries(entries, WEB_POLICY, since=since_timestamp.isoformat()):
            if block.role not in {"user", "assistant"} or block.block_type != "text":
                continue
            raw_text = str(block.block.get("text", "")).strip()
            if not raw_text:
                continue
            block_timestamp = _parse_timestamp(block.timestamp) if block.timestamp else None
            if current_role == block.role:
                current_parts.append(raw_text)
                current_timestamp = block_timestamp or current_timestamp
                continue
            if current_role and current_parts:
                segments.append(
                    ConversationSegment(
                        role=current_role,
                        text="\n\n".join(current_parts).strip(),
                        timestamp=current_timestamp,
                    )
                )
            current_role = block.role
            current_parts = [raw_text]
            current_timestamp = block_timestamp

        if current_role and current_parts:
            segments.append(
                ConversationSegment(
                    role=current_role,
                    text="\n\n".join(current_parts).strip(),
                    timestamp=current_timestamp,
                )
            )
        return segments

    return await asyncio.to_thread(_collect)


async def _deliver_bundle(
    *,
    source_session: Session,
    link_id: str,
    target_session_id: str,
    target_computer: str,
    segments: list[ConversationSegment],
    since_timestamp: datetime,
    source_computer: str | None,
    client: AdapterClient,
    command_service: CommandService,
) -> tuple[bool, datetime | None]:
    """Deliver all segments since the cursor as ONE bundled bridge message.

    Returns ``(handed_off, latest_segment_timestamp)``. Latest timestamp is
    the cursor advancement target on success — the caller writes it to
    ``conversation_delivery_state`` only when handed_off is True. Empty
    segments yields ``(False, None)``; callers must skip cursor advancement.
    """
    if not segments:
        return False, None

    sender_label, sender_computer, actor_id = _sender_identity(source_session, source_computer=source_computer)
    actor_name = f"system@{sender_computer}"
    origin = (source_session.last_input_origin or "").strip() or InputOrigin.TERMINAL.value

    bundle_segments = [(seg.role, seg.timestamp, seg.text) for seg in segments]
    framed_message = format_bundled_conversation_message(
        sender_label=sender_label,
        sender_session_id=source_session.session_id,
        sender_computer=sender_computer,
        segments=bundle_segments,
    )

    latest_ts: datetime | None = None
    for seg in segments:
        if seg.timestamp is not None and (latest_ts is None or seg.timestamp > latest_ts):
            latest_ts = seg.timestamp
    upper_bound = latest_ts or since_timestamp

    source_message_id = _delivery_key(
        link_id=link_id,
        source_session_id=source_session.session_id,
        target_session_id=target_session_id,
        role="bundle",
        from_timestamp=since_timestamp,
        to_timestamp=upper_bound,
    )

    if target_computer == config.computer.name:
        await command_service.process_message(
            ProcessMessageCommand(
                session_id=target_session_id,
                text=framed_message,
                origin=origin,
                actor_id=actor_id,
                actor_name=actor_name,
                source_message_id=source_message_id,
                source_channel_id=link_id,
            )
        )
        return True, latest_ts

    await client.send_request(
        computer_name=target_computer,
        command=f"message {shlex.quote(framed_message)}",
        session_id=target_session_id,
        metadata=MessageMetadata(
            origin=origin,
            actor_id=actor_id,
            actor_name=actor_name,
            platform_message_id=source_message_id,
        ),
    )
    return True, latest_ts


async def deliver_pending_conversation_updates(
    source_session_id: str,
    *,
    client: AdapterClient,
    command_service: CommandService | None = None,
    source_computer: str | None = None,
) -> int:
    """Replay visible conversation activity since the last TeleClaude injection."""
    source_session = await db.get_session(source_session_id)
    if source_session is None:
        return 0
    if source_session.last_conversation_injected_at is None:
        return 0
    if not source_session.native_log_file or not source_session.active_agent:
        return 0

    try:
        agent_name = AgentName.from_str(source_session.active_agent)
    except ValueError:
        return 0

    service = command_service or get_command_service()
    links = await get_active_links_for_session(source_session_id)
    if not links:
        return 0

    delivered = 0
    for link in links:
        peers = await get_peer_members(link_id=link.link_id, sender_session_id=source_session_id)
        for peer in peers:
            persisted = await db.get_conversation_delivery_state(
                link_id=link.link_id,
                source_session_id=source_session_id,
                target_session_id=peer.session_id,
            )
            cursor_dt = (
                parse_iso_datetime(persisted.delivered_through_ts)
                if persisted and persisted.delivered_through_ts
                else None
            )
            since_timestamp = _later_timestamp(source_session.last_conversation_injected_at, cursor_dt)
            if since_timestamp is None:
                continue

            segments = await _collect_visible_conversation_segments_since(
                source_session.native_log_file,
                agent_name,
                since_timestamp,
            )
            if not segments:
                continue

            target_computer = _target_computer_name(peer.computer_name)
            try:
                handed_off, latest_ts = await _deliver_bundle(
                    source_session=source_session,
                    link_id=link.link_id,
                    target_session_id=peer.session_id,
                    target_computer=target_computer,
                    segments=segments,
                    since_timestamp=since_timestamp,
                    source_computer=source_computer,
                    client=client,
                    command_service=service,
                )
            except Exception as exc:
                logger.warning(
                    "Conversation delivery failed: source=%s peer=%s link=%s error=%s",
                    source_session_id,
                    peer.session_id,
                    link.link_id,
                    exc,
                )
                continue
            if not handed_off:
                continue
            delivered += 1
            if latest_ts is None:
                continue
            await db.upsert_conversation_delivery_state(
                link_id=link.link_id,
                source_session_id=source_session_id,
                target_session_id=peer.session_id,
                delivered_through_ts=latest_ts.isoformat(),
            )

    return delivered


async def reconcile_outstanding_conversation_deliveries(
    computer_name: str,
    *,
    client: AdapterClient,
    command_service: CommandService | None = None,
) -> int:
    """Startup repair for conversation deliveries that were not mirrored before restart."""
    sessions = await db.list_sessions(computer_name=computer_name, include_headless=True)
    repaired = 0
    for session in sessions:
        if session.closed_at is not None or session.last_conversation_injected_at is None:
            continue
        repaired += await deliver_pending_conversation_updates(
            session.session_id,
            client=client,
            command_service=command_service,
            source_computer=session.computer_name,
        )
    return repaired


# Debounce window for coalescing rapid agent_stops on the same source session
# into a single bundled delivery. Codex emits agent_stops after each tool turn,
# so without coalescing, a multi-turn task fans out N separate deliveries to
# every linked peer. Reset semantics: each new agent_stop within this window
# postpones the firing by another full window.
_DEBOUNCE_WINDOW_S: float = 10.0
_pending_deliveries: dict[str, asyncio.Task[None]] = {}


def schedule_debounced_delivery(
    source_session_id: str,
    *,
    client: AdapterClient,
    command_service: CommandService | None = None,
    source_computer: str | None = None,
) -> None:
    """Coalesce N rapid agent_stops on this source into one delayed delivery.

    Cancels any pending timer for ``source_session_id`` and starts a fresh
    ``_DEBOUNCE_WINDOW_S`` timer. When the timer fires, runs
    ``deliver_pending_conversation_updates`` once. Synchronous (not a
    coroutine) because the caller doesn't want to await — it just signals
    that delivery should run after the window quiets.
    """
    pending = _pending_deliveries.pop(source_session_id, None)
    if pending is not None and not pending.done():
        pending.cancel()

    async def _run() -> None:
        try:
            await asyncio.sleep(_DEBOUNCE_WINDOW_S)
        except asyncio.CancelledError:
            return
        try:
            await deliver_pending_conversation_updates(
                source_session_id,
                client=client,
                command_service=command_service,
                source_computer=source_computer,
            )
        except Exception as exc:
            logger.warning(
                "Debounced conversation delivery failed: source=%s error=%s",
                source_session_id,
                exc,
            )
        finally:
            _pending_deliveries.pop(source_session_id, None)

    task = asyncio.create_task(_run(), name=f"conversation-delivery-{source_session_id}")
    _pending_deliveries[source_session_id] = task
