"""Message, voice, and file command handlers."""

import asyncio
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import TELECLAUDE_SYSTEM_PREFIX
from teleclaude.core import polling_coordinator, tmux_bridge, tmux_io, voice_message_handler
from teleclaude.core.db import InboundQueueRow, db
from teleclaude.core.events import FileEventContext, VoiceEventContext
from teleclaude.core.feature_flags import is_threaded_output_enabled
from teleclaude.core.file_handler import handle_file as handle_file_upload
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.models import CleanupTrigger, MessageMetadata, Session
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.types.commands import HandleFileCommand, HandleVoiceCommand, ProcessMessageCommand

from ._utils import STARTUP_GATE_POLL_INTERVAL_S, STARTUP_GATE_TIMEOUT_S, StartPollingFunc

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


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
    # Without this, stale last_input_origin (e.g. "api" from TUI) causes feedback
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
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found for voice delete", session_id)
            return
        await client.delete_message(session, str(message_id))

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

    if cmd.message_id:
        session = await db.get_session(cmd.session_id)
        if session:
            await client.delete_message(session, str(cmd.message_id))

    logger.debug("Forwarding transcribed voice to agent: %s...", transcribed[:50])

    # Reset threaded output state so the next agent output starts a fresh message.
    # The next agent output will start a fresh message block at the bottom.
    session = await db.get_session(cmd.session_id)
    if session:
        await client.break_threaded_turn(session)

    await process_message(
        ProcessMessageCommand(
            session_id=cmd.session_id,
            text=transcribed,
            origin=cmd.origin or "api",
            actor_id=cmd.actor_id,
            actor_name=cmd.actor_name,
            actor_avatar_url=cmd.actor_avatar_url,
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
    await db.update_session(
        session_id,
        last_message_sent=message_text[:200],
        last_message_sent_at=datetime.now(UTC).isoformat(),
        last_input_origin=row["origin"],
    )

    linked_output_prefix = f"{TELECLAUDE_SYSTEM_PREFIX} Linked output from "
    direct_conversation_prefix = f"{TELECLAUDE_SYSTEM_PREFIX} Direct Conversation]"
    is_system_message = message_text.startswith(TELECLAUDE_SYSTEM_PREFIX) and not (
        message_text.startswith(linked_output_prefix) or message_text.startswith(direct_conversation_prefix)
    )

    active_agent = session.active_agent

    async def _broadcast() -> None:
        if not row["origin"]:
            return
        try:
            await client.broadcast_user_input(
                session,
                message_text,
                row["origin"],
                actor_id=row["actor_id"],
                actor_name=row["actor_name"],
                actor_avatar_url=row["actor_avatar_url"],
            )
        except Exception as exc:
            logger.warning("broadcast_user_input failed (non-fatal): session=%s error=%s", session_id, exc)

    async def _break_turn() -> None:
        if not is_threaded_output_enabled(active_agent):
            return
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

    results = await asyncio.gather(_tmux_inject(), _broadcast(), _break_turn(), return_exceptions=True)
    tmux_result = results[0]
    if isinstance(tmux_result, Exception):
        raise tmux_result
    if tmux_result is False:
        raise RuntimeError(f"tmux delivery failed for session {session_id}")
    if is_system_message:
        return

    if (active_agent or "").lower() == "codex":
        polling_coordinator.seed_codex_prompt_from_message(session_id, message_text)

    await db.update_last_activity(session_id)
    await start_polling(session_id, session.tmux_session_name)
    logger.debug("Started polling for session %s", session_id)


async def process_message(
    cmd: ProcessMessageCommand,
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Enqueue an incoming user message for durable delivery to the session."""
    from teleclaude.core.inbound_queue import get_inbound_queue_manager

    session_id = cmd.session_id
    logger.debug("Enqueueing message for session %s: %s...", session_id, cmd.text[:50])

    session = await db.get_session(session_id)
    if not session:
        raise SessionMessageRejectedError(session_id=session_id, reason="not_found")
    if session.closed_at or session.lifecycle_status in {"closed", "closing"}:
        raise SessionMessageRejectedError(session_id=session_id, reason="closed")
    if not await _session_message_delivery_available(session):
        raise SessionMessageRejectedError(session_id=session_id, reason="unavailable")

    await get_inbound_queue_manager().enqueue(
        session_id=session_id,
        origin=cmd.origin or "",
        content=cmd.text,
        actor_id=cmd.actor_id,
        actor_name=cmd.actor_name,
        actor_avatar_url=cmd.actor_avatar_url,
        source_message_id=cmd.source_message_id,
        source_channel_id=cmd.source_channel_id,
    )
