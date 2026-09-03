"""Message, voice, and file command handlers."""

import asyncio
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, NotRequired, TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge, tmux_io, voice_message_handler
from teleclaude.core.control_delivery import handoff_control_payload
from teleclaude.core.db import InboundQueueRow, PeerBundleSegmentInput, db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import FileEventContext, SessionLifecycleContext, TeleClaudeEvents, VoiceEventContext
from teleclaude.core.file_handler import handle_file as handle_file_upload
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.inbound_queue import get_inbound_queue_manager
from teleclaude.core.injected_text import (
    EnvelopeName,
    InjectedTextSourceFeature,
    TranscriptEntryKind,
    semantic_envelope,
    visible_input_update,
)
from teleclaude.core.models import (
    CleanupTrigger,
    MessageAuthor,
    MessageAuthorKind,
    MessageMetadata,
    PeerBundleSegmentWireDict,
    Session,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_status import is_agent_turn_running, is_session_terminal
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.events.envelope import EventVisibility
from teleclaude.types.commands import HandleFileCommand, HandleVoiceCommand, ProcessMessageCommand

from ._utils import STARTUP_GATE_POLL_INTERVAL_S, STARTUP_GATE_TIMEOUT_S, StartPollingFunc

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_CONTINUATION_DELIVERY_FAILURE_NOTICE = (
    "Restart continuation stimulus could not be confirmed delivered. Session kept alive for inspection."
)
_CALLER_SEND_DELIVERY_EXHAUSTED_EVENT = "caller_send_delivery_exhausted"
_CALLER_SEND_DELIVERY_FAILURE_NOTICE_TEMPLATE = (
    "Delivery to session {target_session_id} was exhausted before reaching its agent."
)
_CALLER_SEND_CONTROL_SOURCE_KEY_TEMPLATE = "caller-send-delivery-exhausted:{inbound_row_id}"
_PEER_ATTENTION_HANDOFF_DECIDED_EVENT = "peer_attention_handoff_decided"
_PEER_ATTENTION_MISSING_OCCURRENCE_REASON = "peer_occurrence_required"
_PEER_ATTENTION_CONTROL_SOURCE_KEY_TEMPLATE = "peer-attention:{source_occurrence_id}"
_PEER_ATTENTION_NOTIFICATION = (
    "Peer input is pending. If unfinished work needs to resume, preserve continuation through the existing "
    "reminder mechanism, then yield voluntarily so the peer input becomes your next conversational input."
)


class _CallerSendDeliveryExhaustedOutcome(StrEnum):
    """Closed terminal outcomes for a caller-send delivery exhaustion."""

    CALLER_NOTIFIED = "caller_notified"
    UNADDRESSABLE = "unaddressable"
    NOTIFICATION_FAILED = "notification_failed"


class _CallerSendDeliveryExhaustedReason(StrEnum):
    """Closed reasons for each caller-send delivery exhaustion outcome."""

    CALLER_NOTIFIED = "caller_notified"
    CALLER_TERMINAL = "caller_terminal"
    CALLER_NOT_LOCAL = "caller_not_local"
    CALLER_ABSENT = "caller_absent"
    SELF_SEND = "self_send"
    CALLER_BECAME_UNAVAILABLE = "caller_became_unavailable"
    HANDOFF_ERROR = "handoff_error"


class _PeerAttentionHandoffOutcome(StrEnum):
    """Closed outcomes for a peer-attention handoff decision."""

    ENQUEUED = "enqueued"
    SKIPPED = "skipped"


class _PeerAttentionHandoffReason(StrEnum):
    """Closed running-turn reasons for a peer-attention handoff decision."""

    TARGET_TURN_RUNNING = "target_turn_running"
    TARGET_TURN_NOT_RUNNING = "target_turn_not_running"


class _DeliveryLogFields(TypedDict):
    """Body-free facts emitted with an active-agent delivery decision."""

    inbound_row_id: int
    session_id: str
    source_occurrence_id: str | None
    outcome: str
    stage: str
    reason: str
    paste_performed: bool
    platform_enter_sent: bool
    existing_input_preserved: bool
    separator_newlines: int


class _CallerSendDeliveryExhaustedLogFields(TypedDict):
    """Body-free correlations for one terminal caller-send exhaustion decision."""

    inbound_row_id: int
    target_session_id: str
    caller_session_id: str | None
    source_occurrence_id: str | None
    outcome: _CallerSendDeliveryExhaustedOutcome
    reason: _CallerSendDeliveryExhaustedReason
    control_payload_row_id: NotRequired[int]


class _PeerAttentionSnapshot(TypedDict):
    """Pre-acceptance target state used for one peer-attention decision."""

    source_occurrence_id: str
    observed_last_input_at: datetime | None
    observed_last_agent_stop_at: datetime | None
    observed_last_agent_idle_at: datetime | None


class _PeerAttentionHandoffLogFields(TypedDict):
    """Body-free correlations and evidence for one peer-attention decision."""

    source_occurrence_id: str
    observed_last_input_at: datetime | None
    observed_last_agent_stop_at: datetime | None
    observed_last_agent_idle_at: datetime | None
    target_session_id: str
    outcome: _PeerAttentionHandoffOutcome
    reason: _PeerAttentionHandoffReason
    control_payload_row_id: NotRequired[int]


def _capture_peer_attention_snapshot(
    cmd: ProcessMessageCommand,
    session: Session,
) -> _PeerAttentionSnapshot | None:
    """Capture the target state that determines a peer-attention handoff."""
    if cmd.source_feature is not InjectedTextSourceFeature.PEER_BUNDLE:
        return None
    if not cmd.occurrence_key:
        raise SessionMessageRejectedError(
            session_id=cmd.session_id,
            reason=_PEER_ATTENTION_MISSING_OCCURRENCE_REASON,
        )
    return {
        "source_occurrence_id": cmd.occurrence_key,
        "observed_last_input_at": session.last_message_sent_at,
        "observed_last_agent_stop_at": session.last_agent_stop_at,
        "observed_last_agent_idle_at": session.last_agent_idle_at,
    }


async def _handoff_peer_attention(
    *,
    session_id: str,
    snapshot: _PeerAttentionSnapshot,
) -> None:
    """Persist one attention notice when peer input reached a working target."""
    target_turn_running = is_agent_turn_running(
        last_input_at=snapshot["observed_last_input_at"],
        last_agent_stop_at=snapshot["observed_last_agent_stop_at"],
        last_agent_idle_at=snapshot["observed_last_agent_idle_at"],
    )
    reason = (
        _PeerAttentionHandoffReason.TARGET_TURN_RUNNING
        if target_turn_running
        else _PeerAttentionHandoffReason.TARGET_TURN_NOT_RUNNING
    )
    outcome = _PeerAttentionHandoffOutcome.SKIPPED
    fields: _PeerAttentionHandoffLogFields = {
        "source_occurrence_id": snapshot["source_occurrence_id"],
        "observed_last_input_at": snapshot["observed_last_input_at"],
        "observed_last_agent_stop_at": snapshot["observed_last_agent_stop_at"],
        "observed_last_agent_idle_at": snapshot["observed_last_agent_idle_at"],
        "target_session_id": session_id,
        "outcome": outcome,
        "reason": reason,
    }
    if target_turn_running:
        control_payload_row_id = await handoff_control_payload(
            session_id=session_id,
            body=_PEER_ATTENTION_NOTIFICATION,
            source_key=_PEER_ATTENTION_CONTROL_SOURCE_KEY_TEMPLATE.format(
                source_occurrence_id=snapshot["source_occurrence_id"]
            ),
            envelope=semantic_envelope(EnvelopeName.NOTIFICATION),
            wake_source_feature=InjectedTextSourceFeature.PEER_BUNDLE,
        )
        outcome = _PeerAttentionHandoffOutcome.ENQUEUED
        fields["outcome"] = outcome
        fields["control_payload_row_id"] = control_payload_row_id
    logger.info(_PEER_ATTENTION_HANDOFF_DECIDED_EVENT, **fields)


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
        **visible_input_update(message_text),
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
        # The voice workflow snapshots the sender for its explicit, origin
        # targeted UI update; adapters only receive ordinary plain text.
        if metadata.cleanup_trigger == "next_turn" and cmd.actor_name:
            metadata.reflection_actor_id = cmd.actor_id
            metadata.reflection_actor_name = cmd.actor_name
            metadata.reflection_actor_avatar_url = cmd.actor_avatar_url
            metadata.reflection_origin = cmd.origin
            metadata.target_adapter_key = cmd.origin
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
            text_kind=TranscriptEntryKind.ORDINARY,
            source_feature=InjectedTextSourceFeature.VOICE,
            occurrence_key=str(cmd.voice_transcription_id) if cmd.voice_transcription_id is not None else None,
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
    if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        raise SessionMessageRejectedError(session_id=session_id, reason="closed")

    # Gate: wait for session to exit "initializing" before injecting into tmux.
    if session.lifecycle_status == "initializing":
        session = await _wait_for_session_ready(session_id)
        if not session:
            raise RuntimeError(f"Startup gate timeout for session {session_id}")

    if not await _session_message_delivery_available(session):
        raise SessionMessageRejectedError(session_id=session_id, reason="unavailable")

    await _ensure_inbound_acceptance_metadata(session, row, origin_metadata)

    active_agent = session.active_agent

    def _delivery_log_fields(result: tmux_io.UserTurnDeliveryResult) -> _DeliveryLogFields:
        """Return body-free correlations and facts for one terminal delivery decision."""
        return {
            "inbound_row_id": row["id"],
            "session_id": session_id,
            "source_occurrence_id": row["occurrence_key"],
            "outcome": result.outcome.value,
            "stage": result.stage.value,
            "reason": result.reason.value,
            "paste_performed": result.paste_performed,
            "platform_enter_sent": result.platform_enter_sent,
            "existing_input_preserved": result.existing_input_preserved,
            "separator_newlines": 2,
        }

    async def _start_input_turn() -> None:
        try:
            await client.start_input_turn(session)
        except Exception as exc:
            logger.warning("start_input_turn failed (non-fatal): session=%s error=%s", session_id, exc)

    async def _tmux_inject() -> tmux_io.UserTurnDeliveryResult | bool:
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

    await _start_input_turn()
    is_active_agent_delivery = active_agent is not None and session.lifecycle_status != "headless"
    if is_active_agent_delivery:
        logger.info(
            "session_input_delivery_started",
            inbound_row_id=row["id"],
            session_id=session_id,
            source_occurrence_id=row["occurrence_key"],
        )
    results = await asyncio.gather(_tmux_inject(), return_exceptions=True)
    tmux_result = results[0]
    if isinstance(tmux_result, Exception):
        if is_active_agent_delivery:
            logger.info(
                "session_input_delivery_decided",
                inbound_row_id=row["id"],
                session_id=session_id,
                source_occurrence_id=row["occurrence_key"],
                outcome=tmux_io.UserTurnDeliveryOutcome.FAILED.value,
                stage=tmux_io.UserTurnDeliveryStage.CONFIRMATION.value,
                reason=tmux_io.UserTurnDeliveryReason.EXECUTION_ERROR.value,
            )
        raise tmux_result
    if isinstance(tmux_result, tmux_io.UserTurnDeliveryResult):
        logger.info("session_input_delivery_decided", **_delivery_log_fields(tmux_result))
        if not tmux_result.succeeded:
            raise RuntimeError(f"tmux delivery failed for session {session_id}: {tmux_result.reason.value}")
    elif tmux_result is False:
        raise RuntimeError(f"tmux delivery failed for session {session_id}")

    await db.update_last_activity(session_id)
    await start_polling(session_id, session.tmux_session_name)
    logger.debug("Started polling for session %s", session_id)


def _record_caller_send_delivery_exhausted(
    row: InboundQueueRow,
    *,
    outcome: _CallerSendDeliveryExhaustedOutcome,
    reason: _CallerSendDeliveryExhaustedReason,
    control_payload_row_id: int | None = None,
) -> None:
    """Emit one body-free terminal decision for an exhausted caller-send row."""
    fields: _CallerSendDeliveryExhaustedLogFields = {
        "inbound_row_id": row["id"],
        "target_session_id": row["session_id"],
        "caller_session_id": row["caller_session_id"],
        "source_occurrence_id": row["occurrence_key"],
        "outcome": outcome,
        "reason": reason,
    }
    if control_payload_row_id is not None:
        fields["control_payload_row_id"] = control_payload_row_id
    logger.info(_CALLER_SEND_DELIVERY_EXHAUSTED_EVENT, **fields)


def _session_is_addressable(session: Session | None) -> bool:
    """Return whether a local session can receive a control-delivery handoff."""
    return session is not None and not is_session_terminal(
        lifecycle_status=session.lifecycle_status,
        closed_at=session.closed_at,
    )


async def _notify_caller_send_delivery_exhausted(row: InboundQueueRow) -> None:
    """Persist an exhaustion notice only for the original live local caller."""
    caller_session_id = row["caller_session_id"]
    target_session_id = row["session_id"]
    if caller_session_id is None:
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.CALLER_ABSENT,
        )
        return
    if caller_session_id == target_session_id:
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.SELF_SEND,
        )
        return

    caller_session = await db.get_session(caller_session_id)
    if caller_session is None:
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.CALLER_NOT_LOCAL,
        )
        return
    if not _session_is_addressable(caller_session):
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.CALLER_TERMINAL,
        )
        return

    notice_body = _CALLER_SEND_DELIVERY_FAILURE_NOTICE_TEMPLATE.format(target_session_id=target_session_id)
    try:
        control_payload_row_id = await handoff_control_payload(
            session_id=caller_session_id,
            body=notice_body,
            source_key=_CALLER_SEND_CONTROL_SOURCE_KEY_TEMPLATE.format(inbound_row_id=row["id"]),
            envelope=semantic_envelope(
                EnvelopeName.NOTIFICATION,
                body=notice_body,
            ),
        )
    except SessionMessageRejectedError:
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.CALLER_BECAME_UNAVAILABLE,
        )
        return
    except Exception:
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.NOTIFICATION_FAILED,
            reason=_CallerSendDeliveryExhaustedReason.HANDOFF_ERROR,
        )
        raise

    if not _session_is_addressable(await db.get_session(caller_session_id)):
        _record_caller_send_delivery_exhausted(
            row,
            outcome=_CallerSendDeliveryExhaustedOutcome.UNADDRESSABLE,
            reason=_CallerSendDeliveryExhaustedReason.CALLER_BECAME_UNAVAILABLE,
            control_payload_row_id=control_payload_row_id,
        )
        return
    _record_caller_send_delivery_exhausted(
        row,
        outcome=_CallerSendDeliveryExhaustedOutcome.CALLER_NOTIFIED,
        reason=_CallerSendDeliveryExhaustedReason.CALLER_NOTIFIED,
        control_payload_row_id=control_payload_row_id,
    )


async def notify_delivery_exhausted(row: InboundQueueRow, client: "AdapterClient") -> None:
    """Present terminal delivery exhaustion for sources with a return channel."""
    if row["source_feature"] == InjectedTextSourceFeature.CALLER_SEND.value:
        await _notify_caller_send_delivery_exhausted(row)
        return
    if row["source_feature"] != InjectedTextSourceFeature.AGENT_RESTART.value:
        return
    session = await db.get_session(row["session_id"])
    if session is None or is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        return
    event_bus.emit(
        TeleClaudeEvents.AGENT_READINESS_TIMEOUT,
        SessionLifecycleContext(session_id=session.session_id),
        visibility=EventVisibility.LOCAL,
    )
    await client.send_message(session, _CONTINUATION_DELIVERY_FAILURE_NOTICE)
    logger.info(
        "agent_restart_continuation_delivery_failed",
        outcome="operator_notified",
        session_active=True,
        session_id=session.session_id,
        inbound_row_id=row["id"],
        occurrence_key=row["occurrence_key"],
    )


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

    peer_attention_snapshot = _capture_peer_attention_snapshot(cmd, session)

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
        text_kind=cmd.text_kind,
        source_feature=cmd.source_feature,
        occurrence_key=cmd.occurrence_key,
        payload_json=_encode_inbound_payload(cmd.origin_metadata),
        actor_id=cmd.actor_id,
        actor_name=cmd.actor_name,
        actor_avatar_url=cmd.actor_avatar_url,
        source_message_id=cmd.source_message_id or cmd.occurrence_key,
        source_channel_id=cmd.source_channel_id,
        caller_session_id=cmd.caller_session_id,
        caller_author=_caller_author_from_command(cmd),
        caller_job_role=cmd.caller_job_role,
        caller_origin_prefix_len=cmd.caller_origin_prefix_len,
        caller_origin_suffix_len=cmd.caller_origin_suffix_len,
        post_insert_callback=_record_after_insert,
    )
    if peer_attention_snapshot is not None:
        await _handoff_peer_attention(
            session_id=session_id,
            snapshot=peer_attention_snapshot,
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
