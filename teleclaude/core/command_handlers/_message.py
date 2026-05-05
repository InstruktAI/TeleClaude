"""Message, voice, and file command handlers."""

import asyncio
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import TELECLAUDE_SYSTEM_PREFIX
from teleclaude.core import tmux_bridge, tmux_io, voice_message_handler
from teleclaude.core.conversation_messages import (
    LinkedDirectOutputClassification,
    classify_linked_direct_conversation_output,
    is_conversation_bridge_message,
    parse_linked_output_message,
)
from teleclaude.core.db import InboundQueueRow, db
from teleclaude.core.events import FileEventContext, VoiceEventContext
from teleclaude.core.file_handler import handle_file as handle_file_upload
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.inbound_queue import get_inbound_queue_manager
from teleclaude.core.models import CleanupTrigger, MessageMetadata, Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import get_link, resolve_link_for_sender_target
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.types.commands import HandleFileCommand, HandleVoiceCommand, ProcessMessageCommand

from ._utils import STARTUP_GATE_POLL_INTERVAL_S, STARTUP_GATE_TIMEOUT_S, StartPollingFunc

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


def _encode_inbound_payload(origin_metadata: Mapping[str, object] | None) -> str | None:
    """Serialize queue-side metadata needed at delivery time."""
    if origin_metadata is None:
        return None
    payload = dict(origin_metadata)
    if not payload:
        return None
    return json.dumps({"origin_metadata": payload})


def _decode_inbound_origin_metadata(row: InboundQueueRow) -> Mapping[str, object] | None:
    """Decode typed origin metadata carried through the inbound queue."""
    payload_json = row["payload_json"]
    if not payload_json:
        return None
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        logger.warning("Invalid inbound payload_json for row %d", row["id"])
        return None
    if not isinstance(payload, dict):
        return None
    origin_metadata = payload.get("origin_metadata")
    if not isinstance(origin_metadata, dict) or not origin_metadata:
        return None
    return origin_metadata


async def _session_message_delivery_available(session: Session) -> bool:
    """Return True when a session can accept normal message delivery.

    Headless sessions are intentionally adoptable on-demand. Initializing sessions
    are allowed to queue input and will be gated later during delivery. All other
    sessions require an existing tmux session; missing tmux is not healed here.
    """
    if session.lifecycle_status in {"headless", "initializing"}:
        return True
    if not session.tmux_session_name:
        return False
    return await tmux_bridge.session_exists(session.tmux_session_name, log_missing=False)


async def _classify_direct_link_noop_output(
    *,
    session_id: str,
    text: str,
    source_channel_id: str | None,
) -> tuple[str | None, str, LinkedDirectOutputClassification] | None:
    """Return direct-link noop classification metadata, or None when output should pass."""
    parsed = parse_linked_output_message(text)
    if parsed is None:
        return None

    link_id = source_channel_id
    if source_channel_id:
        link = await get_link(source_channel_id)
        if link is None or link.mode != "direct_link":
            return None
    else:
        resolved = await resolve_link_for_sender_target(
            sender_session_id=parsed.sender_session_id,
            target_session_id=session_id,
        )
        if resolved is None or resolved[0].mode != "direct_link":
            return None
        link_id = resolved[0].link_id

    classification = classify_linked_direct_conversation_output(text)
    if classification.emit:
        return None
    return (link_id, parsed.sender_session_id, classification)


async def handle_voice(
    cmd: HandleVoiceCommand,
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Handle voice input for a session."""
    session = await db.get_session(cmd.session_id)
    if session:
        await client.pre_handle_command(session, cmd.origin)

    # Update origin BEFORE sending feedback so routing targets the correct adapter.
    # Without this, stale last_input_origin (e.g. "web" from a different edge) causes feedback
    # to broadcast and track wrong message_ids, preventing cleanup.
    if cmd.origin:
        await db.update_session(cmd.session_id, last_input_origin=cmd.origin)

    async def _send_status(
        session_id: str,
        message: str,
        metadata: MessageMetadata,
    ) -> str | None:
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found for voice status", session_id)
            return None
        # Inject actor info into transcription displays so adapters can
        # attribute the transcription to the sender (e.g. Discord webhook).
        if metadata.is_transcription and cmd.actor_name:
            metadata.reflection_actor_id = cmd.actor_id
            metadata.reflection_actor_name = cmd.actor_name
            metadata.reflection_actor_avatar_url = cmd.actor_avatar_url
        return await client.send_message(
            session,
            message,
            metadata=metadata,
        )

    async def _delete_feedback(session_id: str, message_id: str) -> None:
        normalized_message_id = str(message_id).strip() if message_id else ""
        if not normalized_message_id or normalized_message_id.lower() == "none":
            logger.debug("Skipping voice message cleanup for session %s because message_id is empty", session_id)
            return

        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found for voice delete", session_id)
            return
        await client.delete_message(session, normalized_message_id)

    context = VoiceEventContext(
        session_id=cmd.session_id,
        file_path=cmd.file_path,
        duration=cmd.duration,
        message_id=cmd.message_id,
        message_thread_id=cmd.message_thread_id,
        origin=cmd.origin,
    )

    transcribed = await voice_message_handler.handle_voice(
        session_id=cmd.session_id,
        audio_path=cmd.file_path,
        context=context,
        send_message=_send_status,
        delete_message=_delete_feedback,
    )
    if not transcribed:
        return

    await _delete_feedback(cmd.session_id, cmd.message_id or "")

    logger.debug("Forwarding transcribed voice to agent: %s...", transcribed[:50])

    # Drop pending QoS payloads before forwarding transcribed voice.
    session = await db.get_session(cmd.session_id)
    if session:
        await client.break_threaded_turn(session)

    await process_message(
        ProcessMessageCommand(
            session_id=cmd.session_id,
            text=transcribed,
            origin=cmd.origin or InputOrigin.TERMINAL.value,
            actor_id=cmd.actor_id,
            actor_name=cmd.actor_name,
            actor_avatar_url=cmd.actor_avatar_url,
            origin_metadata=cmd.origin_metadata,
        ),
        client,
        start_polling,
    )


async def handle_file(
    cmd: HandleFileCommand,
    client: "AdapterClient",
) -> None:
    """Handle file upload for a session."""

    async def _send_notice(
        session_id: str,
        message: str,
        metadata: MessageMetadata,
    ) -> str | None:
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found for file notice", session_id)
            return None
        return await client.send_message(
            session,
            message,
            metadata=metadata,
            cleanup_trigger=CleanupTrigger.NEXT_NOTICE,
        )

    context = FileEventContext(
        session_id=cmd.session_id,
        file_path=cmd.file_path,
        filename=cmd.filename,
        caption=cmd.caption,
        file_size=cmd.file_size,
    )

    await handle_file_upload(
        session_id=cmd.session_id,
        file_path=cmd.file_path,
        filename=cmd.filename,
        context=context,
        send_message=_send_notice,
    )


async def _wait_for_session_ready(session_id: str) -> Session | None:
    """Wait for session lifecycle to exit ``initializing`` with a bounded timeout.

    Returns the refreshed session once ready, or ``None`` on timeout.
    """
    deadline = time.monotonic() + STARTUP_GATE_TIMEOUT_S
    logger.debug(
        "Startup gate: waiting for session %s to exit initializing (timeout=%.1fs)",
        session_id,
        STARTUP_GATE_TIMEOUT_S,
    )
    while time.monotonic() < deadline:
        session = await db.get_session(session_id)
        if not session:
            return None
        if session.lifecycle_status != "initializing":
            logger.debug(
                "Startup gate: session %s ready (status=%s)",
                session_id,
                session.lifecycle_status,
            )
            return session
        await asyncio.sleep(STARTUP_GATE_POLL_INTERVAL_S)

    logger.warning(
        "Startup gate: timeout waiting for session %s to exit initializing after %.1fs",
        session_id,
        STARTUP_GATE_TIMEOUT_S,
    )
    return None


async def deliver_inbound(
    row: InboundQueueRow,
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Delivery core extracted from process_message. Called by the inbound queue worker.

    Raises on any failure so the worker can retry with backoff.
    """
    session_id = row["session_id"]
    message_text = row["content"]

    logger.debug("Delivering inbound row %d for session %s: %s...", row["id"], session_id, message_text[:50])
    origin_metadata = _decode_inbound_origin_metadata(row)

    session = await db.get_session(session_id)
    if not session:
        raise SessionMessageRejectedError(session_id=session_id, reason="not_found")
    if session.closed_at or session.lifecycle_status in {"closed", "closing"}:
        raise SessionMessageRejectedError(session_id=session_id, reason="closed")

    # Gate: wait for session to exit "initializing" before injecting into tmux.
    if session.lifecycle_status == "initializing":
        session = await _wait_for_session_ready(session_id)
        if not session:
            raise RuntimeError(f"Startup gate timeout for session {session_id}")

    if not await _session_message_delivery_available(session):
        raise SessionMessageRejectedError(session_id=session_id, reason="unavailable")

    # DB update must precede broadcast so echo guard reads the persisted state.
    accepted_at = datetime.now(UTC).isoformat()
    if is_conversation_bridge_message(message_text):
        await db.update_session(
            session_id,
            last_message_sent=message_text[:200],
            last_message_sent_at=accepted_at,
            last_input_origin=row["origin"],
            last_conversation_injected_at=accepted_at,
        )
    else:
        await db.update_session(
            session_id,
            last_message_sent=message_text[:200],
            last_message_sent_at=accepted_at,
            last_input_origin=row["origin"],
        )
    if origin_metadata:
        await db.update_origin_metadata(session_id, row["origin"], dict(origin_metadata))

    is_system_message = message_text.startswith(TELECLAUDE_SYSTEM_PREFIX) and not is_conversation_bridge_message(
        message_text
    )

    active_agent = session.active_agent

    async def _break_turn() -> None:
        try:
            await client.break_threaded_turn(session)
        except Exception as exc:
            logger.warning("break_threaded_turn failed (non-fatal): session=%s error=%s", session_id, exc)

    async def _tmux_inject() -> bool:
        if is_system_message:
            logger.debug("Skipping tmux injection for system message: session=%s", session_id)
            return True
        sanitized_text = tmux_io.wrap_bracketed_paste(message_text, active_agent=active_agent)
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        return await tmux_io.process_text(
            session,
            sanitized_text,
            working_dir=working_dir,
            active_agent=active_agent,
        )

    await _break_turn()
    results = await asyncio.gather(_tmux_inject(), return_exceptions=True)
    tmux_result = results[0]
    if isinstance(tmux_result, Exception):
        raise tmux_result
    if tmux_result is False:
        raise RuntimeError(f"tmux delivery failed for session {session_id}")
    if is_system_message:
        return

    await db.update_last_activity(session_id)
    await start_polling(session_id, session.tmux_session_name)
    logger.debug("Started polling for session %s", session_id)


async def process_message(
    cmd: ProcessMessageCommand,
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Enqueue an incoming user message for durable delivery to the session."""
    del client, start_polling

    session_id = cmd.session_id
    logger.debug("Enqueueing message for session %s: %s...", session_id, cmd.text[:50])

    session = await db.get_session(session_id)
    if not session:
        raise SessionMessageRejectedError(session_id=session_id, reason="not_found")
    if session.closed_at or session.lifecycle_status in {"closed", "closing"}:
        raise SessionMessageRejectedError(session_id=session_id, reason="closed")
    if not await _session_message_delivery_available(session):
        raise SessionMessageRejectedError(session_id=session_id, reason="unavailable")

    noop_direct_output = await _classify_direct_link_noop_output(
        session_id=session_id,
        text=cmd.text,
        source_channel_id=cmd.source_channel_id,
    )
    if noop_direct_output is not None:
        link_id, source_session_id, classification = noop_direct_output
        logger.info(
            "Dropping linked direct output before enqueue",
            extra={
                "source_session_id": source_session_id,
                "target_session_id": session_id,
                "link_id": link_id,
                "role": "assistant",
                "reason": classification.reason,
                "preview": classification.preview,
            },
        )
        return

    await get_inbound_queue_manager().enqueue(
        session_id=session_id,
        origin=cmd.origin or "",
        content=cmd.text,
        payload_json=_encode_inbound_payload(cmd.origin_metadata),
        actor_id=cmd.actor_id,
        actor_name=cmd.actor_name,
        actor_avatar_url=cmd.actor_avatar_url,
        source_message_id=cmd.source_message_id,
        source_channel_id=cmd.source_channel_id,
    )
