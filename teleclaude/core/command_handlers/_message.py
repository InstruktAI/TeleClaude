"""Message, voice, and file command handlers."""

import asyncio
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge, tmux_io, voice_message_handler
from teleclaude.core.db import InboundQueueRow, PeerBundleSegmentInput, db
from teleclaude.core.events import FileEventContext, VoiceEventContext
from teleclaude.core.file_handler import handle_file as handle_file_upload
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.inbound_queue import get_inbound_queue_manager
from teleclaude.core.inbound_types import InboundMessageType
from teleclaude.core.models import (
    CleanupTrigger,
    MessageAuthor,
    MessageAuthorKind,
    MessageMetadata,
    PeerBundleSegmentWireDict,
    Session,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_status import is_session_terminal
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


async def _record_accepted_input_metadata(
    *,
    session_id: str,
    origin: str,
    message_text: str,
    origin_metadata: Mapping[str, object] | None,
) -> None:
    """Persist the accepted-input fields owned by the core acceptance boundary."""
    await db.update_session(
        session_id,
        last_message_sent=message_text[:200],
        last_message_sent_at=datetime.now(UTC).isoformat(),
        last_input_origin=origin,
    )
    if origin_metadata:
        await db.update_origin_metadata(session_id, origin, dict(origin_metadata))


def _accepted_input_fields_match(session: Session, *, origin: str, message_text: str) -> bool:
    """Return whether session state already represents this accepted input."""
    return (
        session.last_message_sent == message_text[:200]
        and session.last_message_sent_at is not None
        and session.last_input_origin == origin
    )


def _origin_metadata_contains(
    session: Session,
    *,
    origin: str,
    origin_metadata: Mapping[str, object] | None,
) -> bool:
    """Return whether the session origin section already contains the queued metadata."""
    if not origin_metadata:
        return True
    section = session.get_origin_section(origin)
    return all(section.get(key) == value for key, value in origin_metadata.items())


async def _ensure_inbound_acceptance_metadata(
    session: Session,
    row: InboundQueueRow,
    origin_metadata: Mapping[str, object] | None,
) -> None:
    """Backfill accepted metadata for rows queued before enqueue-time writes existed."""
    session_id = row["session_id"]
    origin = row["origin"]
    message_text = row["content"]

    if not _accepted_input_fields_match(session, origin=origin, message_text=message_text):
        await _record_accepted_input_metadata(
            session_id=session_id,
            origin=origin,
            message_text=message_text,
            origin_metadata=origin_metadata,
        )
        return

    if not _origin_metadata_contains(session, origin=origin, origin_metadata=origin_metadata):
        await db.update_origin_metadata(session_id, origin, dict(origin_metadata or {}))


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
        if cmd.origin_metadata:
            await db.update_origin_metadata(cmd.session_id, cmd.origin, dict(cmd.origin_metadata))

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
            metadata.reflection_origin = cmd.origin
        return await client.send_message(
            session,
            message,
            metadata=metadata,
        )

    async def _edit_status(
        session_id: str,
        message_id: str,
        message: str,
        metadata: MessageMetadata,
    ) -> bool:
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found for voice status edit", session_id)
            return False
        return await client.edit_message(session, message_id, message, metadata=metadata)

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
        actor_id=cmd.actor_id,
        actor_name=cmd.actor_name,
        actor_avatar_url=cmd.actor_avatar_url,
        voice_transcription_id=cmd.voice_transcription_id,
        notice_message_id=cmd.notice_message_id,
    )

    transcribed = await voice_message_handler.handle_voice(
        session_id=cmd.session_id,
        audio_path=cmd.file_path,
        context=context,
        send_message=_send_status,
        edit_message=_edit_status,
        delete_message=_delete_feedback,
    )
    if not transcribed:
        return

    await _delete_feedback(cmd.session_id, cmd.message_id or "")

    logger.debug("Forwarding transcribed voice to agent: %s...", transcribed[:50])

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
    is_reminder_origin = row["origin"] == InputOrigin.REMINDER.value
    is_reminder_type = row["message_type"] == InboundMessageType.REMINDER.value
    if is_reminder_origin != is_reminder_type:
        raise RuntimeError(f"Invalid reminder inbound contract for row {row['id']}")
    is_reminder = is_reminder_origin

    logger.debug("Delivering inbound row %d for session %s: %s...", row["id"], session_id, message_text[:50])
    origin_metadata = _decode_inbound_origin_metadata(row)

    session = await db.get_session(session_id)
    if not session:
        raise SessionMessageRejectedError(session_id=session_id, reason="not_found")
    if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        raise SessionMessageRejectedError(session_id=session_id, reason="closed")

    # Gate: wait for session to exit "initializing" before injecting into tmux.
    if session.lifecycle_status == "initializing":
        session = await _wait_for_session_ready(session_id)
        if not session:
            raise RuntimeError(f"Startup gate timeout for session {session_id}")

    if not await _session_message_delivery_available(session):
        raise SessionMessageRejectedError(session_id=session_id, reason="unavailable")

    if not is_reminder:
        await _ensure_inbound_acceptance_metadata(session, row, origin_metadata)

    active_agent = session.active_agent

    async def _start_input_turn() -> None:
        try:
            await client.start_input_turn(session)
        except Exception as exc:
            logger.warning("start_input_turn failed (non-fatal): session=%s error=%s", session_id, exc)

    async def _tmux_inject() -> bool:
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        if active_agent and session.lifecycle_status != "headless":
            return await tmux_io.inject_user_turn(
                session,
                message_text,
                active_agent=active_agent,
            )
        return await tmux_io.process_text(
            session,
            message_text,
            working_dir=working_dir,
            active_agent=active_agent,
        )

    if not is_reminder:
        await _start_input_turn()
    results = await asyncio.gather(_tmux_inject(), return_exceptions=True)
    tmux_result = results[0]
    if isinstance(tmux_result, Exception):
        raise tmux_result
    if tmux_result is False:
        raise RuntimeError(f"tmux delivery failed for session {session_id}")

    await db.update_last_activity(session_id)
    await start_polling(session_id, session.tmux_session_name)
    logger.debug("Started polling for session %s", session_id)


def _caller_author_from_command(cmd: ProcessMessageCommand) -> MessageAuthor | None:
    """Rebuild the typed caller event author from a command's flat propagated fields."""
    if not cmd.caller_session_id or not cmd.caller_author_kind or not cmd.caller_author_display:
        return None
    return MessageAuthor(
        kind=MessageAuthorKind(cmd.caller_author_kind),
        display=cmd.caller_author_display,
        session_id=cmd.caller_session_id,
        agent_runtime=cmd.caller_agent_runtime,
        thinking_mode=cmd.caller_thinking_mode,
        machine_role=cmd.caller_machine_role,
    )


def _peer_bundle_segment_from_wire(segment: PeerBundleSegmentWireDict) -> PeerBundleSegmentInput:
    """Rebuild one durable bundle segment input from its cross-computer wire dict."""
    author = MessageAuthor(
        kind=MessageAuthorKind(segment["author_kind"]),
        display=segment["author_display"],
        session_id=segment["original_source_session_id"],
        agent_runtime=segment["author_agent_runtime"],
        thinking_mode=segment["author_thinking_mode"],
        machine_role=segment["author_machine_role"],
    )
    return PeerBundleSegmentInput(
        original_source_session_id=segment["original_source_session_id"],
        author=author,
        author_job_role=segment["author_job_role"],
        occurred_at=datetime.fromisoformat(segment["occurred_at"]),
        body=segment["body"],
    )


async def _persist_peer_bundle_from_command(cmd: ProcessMessageCommand) -> None:
    """Persist a cross-computer-delivered peer bundle on the receiving computer's own DB.

    The structural counterpart to same-computer delivery's direct local
    write (`conversation_bundle_delivery.py`'s `_persist_peer_bundle_segments`):
    cross-computer delivery cannot write into a remote DB directly, so the
    sending computer carries the bundle across the wire on the command
    itself, and the receiving computer persists it here, once, BEFORE the
    message is accepted into the inbound queue. Propagates on failure —
    caught by `execute_command_envelope`'s standard error response, which
    the sender reads and treats as a failed delivery (no cursor advance,
    retried next pass, same-computer symmetry) — never swallowed. A
    swallowed failure here would accept a bridge turn with no bundle behind
    it: permanently unrelayable, since nothing retries structural
    persistence for an already-accepted row.
    """
    if not cmd.peer_bundle_key or not cmd.peer_bundle_link_id or not cmd.peer_bundle_source_session_id:
        return
    if not cmd.peer_bundle_segments:
        return
    await db.create_peer_bundle(
        bundle_key=cmd.peer_bundle_key,
        link_id=cmd.peer_bundle_link_id,
        source_session_id=cmd.peer_bundle_source_session_id,
        target_session_id=cmd.session_id,
        segments=[_peer_bundle_segment_from_wire(segment) for segment in cmd.peer_bundle_segments],
    )


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
    if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        raise SessionMessageRejectedError(session_id=session_id, reason="closed")
    if not await _session_message_delivery_available(session):
        raise SessionMessageRejectedError(session_id=session_id, reason="unavailable")

    # Durable structural provenance is persisted BEFORE queue acceptance: a
    # cross-computer bundle that fails to persist must reject the message
    # outright (propagates from here), not accept a bridge turn with no
    # bundle behind it that nothing later retries.
    await _persist_peer_bundle_from_command(cmd)

    origin = cmd.origin or ""

    async def _record_after_insert(_row_id: int) -> None:
        await _record_accepted_input_metadata(
            session_id=session_id,
            origin=origin,
            message_text=cmd.text,
            origin_metadata=cmd.origin_metadata,
        )

    row_id = await get_inbound_queue_manager().enqueue(
        session_id=session_id,
        origin=origin,
        content=cmd.text,
        payload_json=_encode_inbound_payload(cmd.origin_metadata),
        actor_id=cmd.actor_id,
        actor_name=cmd.actor_name,
        actor_avatar_url=cmd.actor_avatar_url,
        source_message_id=cmd.source_message_id,
        source_channel_id=cmd.source_channel_id,
        caller_session_id=cmd.caller_session_id,
        caller_author=_caller_author_from_command(cmd),
        caller_job_role=cmd.caller_job_role,
        caller_origin_prefix_len=cmd.caller_origin_prefix_len,
        caller_origin_suffix_len=cmd.caller_origin_suffix_len,
        post_insert_callback=_record_after_insert,
    )
    if row_id is not None and (cmd.caller_origin_suffix_len or cmd.peer_bundle_segments):
        logger.info(
            "conversation_envelope_committed",
            outcome="success",
            inbound_row_id=row_id,
            caller_session_id=cmd.caller_session_id or cmd.peer_bundle_source_session_id,
            target_session_id=session_id,
            response_boundary=True,
        )
