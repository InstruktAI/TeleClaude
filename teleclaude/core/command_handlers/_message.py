"""Message, voice, and file command handlers."""

import asyncio
import json
import time
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, NotRequired, TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge, tmux_io, voice_message_handler
from teleclaude.core.agent_readiness import NoComposerReadinessTimeout, await_agent_readiness
from teleclaude.core.agents import AgentName
from teleclaude.core.command_input import CommandInputError, ResolvedCommandInput, admit_command_input
from teleclaude.core.control_delivery import handoff_control_payload
from teleclaude.core.db import InboundQueueRow, db
from teleclaude.core.events import VoiceEventContext
from teleclaude.core.file_handler import format_file_input
from teleclaude.core.help_desk_relay import (
    RelayDeliveryFailed,
    divert_visitor_file,
    divert_visitor_input,
    is_visitor_input,
)
from teleclaude.core.inbound_errors import (
    InboundHoldReason,
    InboundMessageHeldError,
    SessionMessageRejectedError,
    SessionMessageRejectionReason,
)
from teleclaude.core.inbound_media import fetch_media_ref
from teleclaude.core.inbound_queue import get_inbound_queue_manager
from teleclaude.core.inbound_types import InboundMessageType
from teleclaude.core.injected_text import (
    EnvelopeName,
    InjectedTextSourceFeature,
    TranscriptEntryKind,
    authority_for_source_feature,
    caller_occurrence_key,
    identity_content_envelope,
    scan_injected_envelopes,
    semantic_envelope,
    wake_occurrence_key,
)
from teleclaude.core.interactive_procedure_input import resolve_interactive_input
from teleclaude.core.message_lifetime import retains_human_conversation_input
from teleclaude.core.models import (
    CleanupTrigger,
    MessageAuthor,
    MessageAuthorKind,
    MessageMetadata,
    Session,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.procedure_entry import EntryRefusal, resolve_inline_entry
from teleclaude.core.runtime_readiness import RuntimeReadiness, RuntimeReadinessKey
from teleclaude.core.session_cleanup import is_legacy_restricted_session
from teleclaude.core.session_compaction import session_compaction_owner
from teleclaude.core.session_idle_compaction import live_idle_close
from teleclaude.core.session_revival import revive_session
from teleclaude.core.session_runtime_gate import (
    clear_relaunch_awaiting_readiness,
    relaunch_awaiting_readiness,
    session_runtime_owner,
)
from teleclaude.core.session_status import SessionLifecycleStatus, is_agent_turn_running, is_session_terminal
from teleclaude.paths import REPO_ROOT
from teleclaude.types.commands import HandleFileCommand, HandleVoiceCommand, ProcessMessageCommand

from ._delivery_notices import notify_delivery_exhausted as notify_delivery_exhausted
from ._message_acceptance import (
    ensure_inbound_acceptance_metadata,
    record_acceptance_evidence,
    record_accepted_input_metadata,
)
from ._message_delivery import inject_inbound_text
from ._recovered_input import recovered_entry_facts, recovered_posted_at_stamp, with_recovered_notice
from ._utils import STARTUP_GATE_POLL_INTERVAL_S, STARTUP_GATE_TIMEOUT_S, StartPollingFunc

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_LEGACY_RESTRICTED_SESSION_REFUSED_EVENT = "legacy_restricted_session_refused"
_INBOUND_ORIGIN_METADATA_KEY = "origin_metadata"
_INBOUND_COMMAND_INPUT_KEY = "command_input"
_INBOUND_RECOVERED_POSTED_AT_KEY: Final = "recovered_posted_at"
_COMMAND_INPUT_SOURCE_TEXT_KEY = "source_text"
_COMMAND_INPUT_COMMAND_KEY = "command"
_COMMAND_INPUT_ARGS_KEY = "args"
_PEER_ATTENTION_HANDOFF_DECIDED_EVENT = "peer_attention_handoff_decided"
_PEER_ATTENTION_CONTROL_SOURCE_KEY_TEMPLATE = "peer-attention:{source_occurrence_id}"
_HOLD_REASON_BY_DELIVERY_REASON: dict[tmux_io.UserTurnDeliveryReason, InboundHoldReason] = {
    tmux_io.UserTurnDeliveryReason.COMPOSER_OCCUPIED: InboundHoldReason.COMPOSER_OCCUPIED,
    tmux_io.UserTurnDeliveryReason.NO_COMPOSER: InboundHoldReason.NO_COMPOSER,
}
_PEER_ATTENTION_NOTIFICATION = (
    "Peer input is pending. If unfinished work needs to resume, preserve continuation through the existing "
    "reminder mechanism, then yield voluntarily so the peer input becomes your next conversational input."
)


class _InboundCommandInput(TypedDict):
    """The human source and resolved command frozen beside accepted queue content."""

    source_text: str
    command: str
    args: str


class _InboundPayload(TypedDict, total=False):
    """Structured supplemental state stored beside one inbound queue row."""

    origin_metadata: Mapping[str, object]
    command_input: _InboundCommandInput
    recovered_posted_at: str


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
            reason=SessionMessageRejectionReason.PEER_OCCURRENCE_REQUIRED,
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


def _encode_inbound_payload(
    origin_metadata: Mapping[str, object] | None,
    command_input: _InboundCommandInput | None,
    recovered_posted_at: datetime | None = None,
) -> str | None:
    """Serialize queue-side metadata needed at delivery time."""
    if origin_metadata is None and command_input is None and recovered_posted_at is None:
        return None
    payload: _InboundPayload = {}
    if origin_metadata:
        payload["origin_metadata"] = dict(origin_metadata)
    if command_input is not None:
        payload["command_input"] = command_input
    if recovered_posted_at is not None:
        payload[_INBOUND_RECOVERED_POSTED_AT_KEY] = recovered_posted_at_stamp(recovered_posted_at)
    if not payload:
        return None
    return json.dumps(payload)


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
    origin_metadata = payload.get(_INBOUND_ORIGIN_METADATA_KEY)
    if not isinstance(origin_metadata, dict) or not origin_metadata:
        return None
    return origin_metadata


def _decode_inbound_command_input(row: InboundQueueRow) -> _InboundCommandInput | None:
    """Read durable command-source evidence without re-running command recognition."""
    payload_json = row["payload_json"]
    if not payload_json:
        return None
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    command_input = payload.get(_INBOUND_COMMAND_INPUT_KEY)
    if not isinstance(command_input, dict):
        return None
    source_text = command_input.get(_COMMAND_INPUT_SOURCE_TEXT_KEY)
    command = command_input.get(_COMMAND_INPUT_COMMAND_KEY)
    args = command_input.get(_COMMAND_INPUT_ARGS_KEY)
    if not isinstance(source_text, str) or not isinstance(command, str) or not isinstance(args, str):
        return None
    return {"source_text": source_text, "command": command, "args": args}


async def _session_message_delivery_available(session: Session) -> bool:
    """Return True when a session can accept normal message delivery.

    Headless sessions are intentionally adoptable on-demand. Initializing sessions
    are allowed to queue input and will be gated later during delivery. All other
    sessions require an existing tmux session; missing tmux is not healed here.
    A desk session that predates creation-time confinement never accepts input.
    """
    if is_legacy_restricted_session(session):
        logger.warning(_LEGACY_RESTRICTED_SESSION_REFUSED_EVENT, session_id=session.session_id)
        return False
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
    if cmd.media_ref is not None:
        cmd.file_path = str(await fetch_media_ref(cmd.media_ref, cmd.session_id))
    session = await db.get_session(cmd.session_id)
    if session:
        await client.pre_handle_command(session, cmd.origin)

    # Update origin BEFORE sending feedback so routing targets the correct adapter.
    # Without this, stale last_input_origin (e.g. "telegram" from a different edge) causes feedback
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
        if metadata.cleanup_trigger == CleanupTrigger.NEXT_TURN.value and cmd.actor_name:
            metadata.reflection_actor_id = cmd.actor_id
            metadata.reflection_actor_name = cmd.actor_name
            metadata.reflection_actor_avatar_url = cmd.actor_avatar_url
            metadata.reflection_origin = cmd.origin
            metadata.target_adapter_key = cmd.origin
        retains_transcript = (
            metadata.cleanup_trigger == CleanupTrigger.NEXT_TURN.value
            and cmd.origin is not None
            and retains_human_conversation_input(InputOrigin(cmd.origin))
        )
        return await client.send_message(
            session,
            message,
            metadata=metadata,
            ephemeral=not retains_transcript,
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
        source_message_id=cmd.source_message_id,
    )

    transcribed = await voice_message_handler.handle_voice(
        session_id=cmd.session_id,
        audio_path=cmd.file_path,
        context=context,
        send_message=_send_status,
        edit_message=_edit_status,
        delete_message=_delete_feedback,
    )
    if transcribed is None:
        return

    await _delete_feedback(cmd.session_id, cmd.message_id or "")

    logger.debug("Forwarding transcribed voice to agent: %s...", transcribed.text[:50])

    transcript_command = ProcessMessageCommand(
        session_id=cmd.session_id,
        text=transcribed.text,
        origin=cmd.origin or InputOrigin.TERMINAL.value,
        text_kind=TranscriptEntryKind.ORDINARY,
        source_feature=InjectedTextSourceFeature.VOICE,
        occurrence_key=str(transcribed.transcription_id) if transcribed.transcription_id is not None else None,
        actor_id=cmd.actor_id,
        actor_name=cmd.actor_name,
        actor_avatar_url=cmd.actor_avatar_url,
        origin_metadata=cmd.origin_metadata,
        source_message_id=cmd.source_message_id,
        recovered_posted_at=cmd.recovered_posted_at,
    )
    try:
        await accept_inbound_message(transcript_command, message_type=InboundMessageType.VOICE)
    except SessionMessageRejectedError as exc:
        await voice_message_handler.fail_voice_delivery(
            transcribed, session_id=cmd.session_id, reason=str(exc), send_message=_send_status
        )
        raise
    await voice_message_handler.accept_voice(transcribed)


_FILE_SOURCE_FEATURE_BY_ORIGIN: Mapping[str, InjectedTextSourceFeature] = {
    InputOrigin.TELEGRAM.value: InjectedTextSourceFeature.TELEGRAM,
    InputOrigin.DISCORD.value: InjectedTextSourceFeature.DISCORD,
    InputOrigin.WHATSAPP.value: InjectedTextSourceFeature.WHATSAPP,
}
_FILE_UPLOADED_NOTICE = "📎 File uploaded: {filename}"
_FILE_UPLOADED_SIZED_NOTICE = "📎 File uploaded: {filename} ({size_mb:.2f} MB)"
_BYTES_PER_MB = 1_048_576
_FILE_ORIGIN_UNSUPPORTED_TEMPLATE = "File input from origin {origin!r} has no conversation adapter producer"


async def handle_file(
    cmd: HandleFileCommand,
    client: "AdapterClient",
) -> None:
    """Accept a file upload as the session's input, delivered through the durable inbound queue.

    The queue holds the upload until the session can receive it, so a file sent to a session
    that is still starting, in idle maintenance, or idle-closed waits and keeps its place in
    the order instead of being refused.
    """
    if cmd.media_ref is not None:
        fetched = await fetch_media_ref(cmd.media_ref, cmd.session_id)
        cmd.file_path, cmd.filename, cmd.file_size = str(fetched), fetched.name, fetched.stat().st_size
    session = await db.get_session(cmd.session_id)
    if session is None:
        raise SessionMessageRejectedError(session_id=cmd.session_id, reason=SessionMessageRejectionReason.NOT_FOUND)
    if is_visitor_input(session, cmd.actor_id, None) and await divert_visitor_file(session, cmd.filename):
        return
    source_feature = _FILE_SOURCE_FEATURE_BY_ORIGIN.get(cmd.origin or "")
    if source_feature is None:
        raise ValueError(_FILE_ORIGIN_UNSUPPORTED_TEMPLATE.format(origin=cmd.origin))

    accepted = await accept_inbound_message(
        ProcessMessageCommand(
            session_id=cmd.session_id,
            text=format_file_input(session, cmd.file_path, cmd.caption),
            origin=cmd.origin or "",
            text_kind=TranscriptEntryKind.ORDINARY,
            source_feature=source_feature,
            occurrence_key=cmd.source_message_id,
            actor_id=cmd.actor_id,
            source_message_id=cmd.source_message_id,
            recovered_posted_at=cmd.recovered_posted_at,
        ),
        message_type=InboundMessageType.FILE,
    )
    if accepted is None:
        return
    notice = (
        _FILE_UPLOADED_SIZED_NOTICE.format(filename=cmd.filename, size_mb=cmd.file_size / _BYTES_PER_MB)
        if cmd.file_size > 0
        else _FILE_UPLOADED_NOTICE.format(filename=cmd.filename)
    )
    await client.send_message(session, notice, metadata=MessageMetadata(), cleanup_trigger=CleanupTrigger.NEXT_NOTICE)


def _startup_pending(session: Session) -> bool:
    """Return whether the session's agent has yet to show it can accept input.

    A session is pending while it is initializing and while a relaunch of its
    agent awaits readiness.
    """
    return session.lifecycle_status == SessionLifecycleStatus.INITIALIZING or relaunch_awaiting_readiness(
        session.session_id
    )


async def _wait_for_session_ready(session_id: str, readiness: RuntimeReadiness) -> Session | None:
    """Wait for a current session binding to reach its delivery authority.

    Returns ``None`` when the session is gone or the gate times out. A pane
    readiness wait that ends on a settled screen with no composer raises
    ``NoComposerReadinessTimeout``: the session is alive and showing something
    else, which callers hold input for rather than treat as a missing session.
    A relaunch's readiness wait ends when this returns, however it ends.
    """
    try:
        session = await _await_startup_readiness(session_id, readiness)
        if session is not None:
            await session_compaction_owner.settle_restoring(session_id)
        return session
    finally:
        clear_relaunch_awaiting_readiness(session_id)


async def _await_startup_readiness(session_id: str, readiness: RuntimeReadiness) -> Session | None:
    """Poll the session until it is no longer startup-pending or the gate budget ends."""
    deadline = time.monotonic() + STARTUP_GATE_TIMEOUT_S
    while time.monotonic() < deadline:
        session = await db.get_session(session_id)
        if not session:
            return None
        if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
            return None
        if not _startup_pending(session):
            return session
        if not session.active_agent or not session.tmux_session_name:
            await asyncio.sleep(STARTUP_GATE_POLL_INTERVAL_S)
            continue
        try:
            AgentName.from_str(session.active_agent)
        except ValueError:
            await asyncio.sleep(STARTUP_GATE_POLL_INTERVAL_S)
            continue

        readiness_key = (
            RuntimeReadinessKey.ordinary(session_id, session.runtime_run_id)
            if session.runtime_run_id is not None
            else None
        )
        ready_future = (
            readiness.register(readiness_key)
            if readiness_key is not None
            else asyncio.get_running_loop().create_future()
        )
        try:
            refreshed = await db.get_session(session_id)
            if refreshed is None:
                return None
            if not _startup_pending(refreshed) and not ready_future.done():
                ready_future.set_result(None)
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                break
            await await_agent_readiness(
                agent_name=refreshed.active_agent or session.active_agent,
                session=refreshed,
                session_id=session_id,
                ready_future=ready_future,
                quiet_s=STARTUP_GATE_POLL_INTERVAL_S,
                timeout_s=remaining_s,
                readiness=readiness,
            )
        except NoComposerReadinessTimeout:
            raise
        except TimeoutError:
            break
        finally:
            if readiness_key is not None:
                readiness.release(readiness_key, ready_future)
        return await db.get_session(session_id)
    return None


async def _hold_for_startup_readiness(session_id: str, readiness: RuntimeReadiness) -> Session:
    """Wait for the startup gate, holding the input when the agent shows no composer."""
    try:
        session = await _wait_for_session_ready(session_id, readiness)
    except NoComposerReadinessTimeout as exc:
        raise InboundMessageHeldError(session_id=session_id, reason=InboundHoldReason.NO_COMPOSER) from exc
    if not session:
        raise RuntimeError(f"Startup gate timeout for session {session_id}")
    return session


_IDLE_CLOSED_NOT_REVIVED_TEMPLATE = (
    "Idle-closed session {session_id} could not be revived; its input stays queued for retry"
)
_MAINTENANCE_RETURN_NOT_STARTED_TEMPLATE = (
    "Session {session_id} could not leave temporary maintenance; its input stays queued for retry"
)
_CLOSED_BEFORE_INJECTION_TEMPLATE = "Session {session_id} closed before its input was injected; delivery is retried"


async def _deliverable_session(session_id: str) -> Session:
    """The session a queued row is delivered to; an idle-closed conversation is resumed, never rejected.

    The idle cycle closes a conversation session only to spare resources while its person is
    away. Input accepted for it across that close continues the conversation: delivery waits
    for a close in flight to end, then revives the same session. A session closed any other
    way rejects the row.
    """
    session = await db.get_session(session_id)
    if not session:
        raise SessionMessageRejectedError(session_id=session_id, reason=SessionMessageRejectionReason.NOT_FOUND)
    attempt = session_compaction_owner.active_attempt(session)
    if attempt is not None:
        if not await session_compaction_owner.restore_ordinary(session_id, attempt.attempt_id):
            raise RuntimeError(_MAINTENANCE_RETURN_NOT_STARTED_TEMPLATE.format(session_id=session_id))
        async with session_runtime_owner(session_id, wait=True):
            session = await db.get_session(session_id) or session
    if not is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        return session
    if not live_idle_close(session):
        raise SessionMessageRejectedError(session_id=session_id, reason=SessionMessageRejectionReason.CLOSED)
    async with session_runtime_owner(session_id, wait=True):
        session = await db.get_session(session_id) or session
    if not is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        return session
    if not await revive_session(session_id):
        raise RuntimeError(_IDLE_CLOSED_NOT_REVIVED_TEMPLATE.format(session_id=session_id))
    return await db.get_session(session_id) or session


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
    row_source_feature = InjectedTextSourceFeature(row["source_feature"])
    row_text_kind = TranscriptEntryKind(row["text_kind"])
    procedure_wake_occurrence_id = (
        wake_occurrence_key(message_text) if row_text_kind is TranscriptEntryKind.PLATFORM_CONTROL else None
    )
    is_procedure_wake = row_source_feature is InjectedTextSourceFeature.PROCEDURE_ACTIVATION
    origin_metadata, command_input = _decode_inbound_origin_metadata(row), _decode_inbound_command_input(row)
    authority = authority_for_source_feature(row_source_feature)

    session = await _deliverable_session(session_id)

    if _startup_pending(session):
        session = await _hold_for_startup_readiness(session_id, client.runtime_readiness)

    if not await _session_message_delivery_available(session):
        raise SessionMessageRejectedError(session_id=session_id, reason=SessionMessageRejectionReason.UNAVAILABLE)
    await ensure_inbound_acceptance_metadata(
        session, row, origin_metadata, command_input["source_text"] if command_input else None
    )

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

    await _start_input_turn()
    is_active_agent_delivery = active_agent is not None and session.lifecycle_status != "headless"
    if is_active_agent_delivery:
        logger.info(
            "session_input_delivery_started",
            inbound_row_id=row["id"],
            session_id=session_id,
            source_occurrence_id=row["occurrence_key"],
        )
    results: tuple[object, ...] | None = None
    delivery_session = session
    while results is None:
        async with session_runtime_owner(session_id, wait=True):
            # A close can end the session between the checks above and ownership; the row is
            # then delivered again, through the resume of an idle-closed conversation.
            current = await db.get_session(session_id)
            if current is None or is_session_terminal(
                lifecycle_status=current.lifecycle_status, closed_at=current.closed_at
            ):
                raise RuntimeError(_CLOSED_BEFORE_INJECTION_TEMPLATE.format(session_id=session_id))
            if procedure_wake_occurrence_id is not None and (
                is_procedure_wake
                or await db.procedure_event_wake_matches(
                    session_id=session_id,
                    occurrence_id=procedure_wake_occurrence_id,
                )
            ):
                if row["occurrence_key"] != procedure_wake_occurrence_id:
                    return
                admitted = await db.admit_procedure_event_wake(
                    session_id=session_id,
                    occurrence_id=procedure_wake_occurrence_id,
                    session=current,
                )
                # A refused procedure wake leaves its event pending in the inbox. An ordinary control wake
                # still owes its pending payloads a delivery boundary, so it goes on to injection.
                if not admitted and is_procedure_wake:
                    return
            # A relaunch can be marked between the readiness check above and
            # ownership; the mark is read again now that no relaunch is mid-flight.
            if not relaunch_awaiting_readiness(session_id):
                results = await asyncio.gather(
                    inject_inbound_text(
                        delivery_session,
                        message_text,
                        active_agent=active_agent,
                        authority=authority,
                        readiness=client.runtime_readiness,
                    ),
                    return_exceptions=True,
                )
        if results is None:
            delivery_session = await _hold_for_startup_readiness(session_id, client.runtime_readiness)
    tmux_result = results[0]
    if (
        isinstance(tmux_result, tmux_io.UserTurnDeliveryResult)
        and tmux_result.outcome is tmux_io.UserTurnDeliveryOutcome.HELD
    ):
        raise InboundMessageHeldError(session_id=session_id, reason=_HOLD_REASON_BY_DELIVERY_REASON[tmux_result.reason])
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
    await start_polling(session_id, delivery_session.tmux_session_name)
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


def _canonical_caller_content(cmd: ProcessMessageCommand) -> tuple[str, int | None, int | None]:
    """Return the accepted caller envelope, adding K only from command authority."""
    if cmd.source_feature is not InjectedTextSourceFeature.CALLER_SEND or cmd.caller_session_id is None:
        return cmd.text, cmd.caller_origin_prefix_len, cmd.caller_origin_suffix_len
    envelopes = scan_injected_envelopes(cmd.text)
    if len(envelopes) != 1 or envelopes[0].kind is not TranscriptEntryKind.IDENTITY_CONTENT:
        raise SessionMessageRejectedError(
            session_id=cmd.session_id, reason=SessionMessageRejectionReason.CALLER_IDENTITY_COMPATIBILITY
        )
    envelope = envelopes[0]
    if envelope.envelope_span != (0, len(cmd.text)):
        raise SessionMessageRejectedError(
            session_id=cmd.session_id, reason=SessionMessageRejectionReason.CALLER_IDENTITY_COMPATIBILITY
        )
    if caller_occurrence_key(envelope.opening) is not None:
        return cmd.text, envelope.body_span[0], len(cmd.text) - envelope.body_span[1]
    if (
        cmd.occurrence_key is None
        or cmd.caller_author_kind is None
        or cmd.caller_author_display is None
        or cmd.caller_origin_prefix_len != envelope.body_span[0]
        or cmd.caller_origin_suffix_len != len(cmd.text) - envelope.body_span[1]
    ):
        raise SessionMessageRejectedError(
            session_id=cmd.session_id, reason=SessionMessageRejectionReason.CALLER_IDENTITY_COMPATIBILITY
        )
    body = cmd.text[envelope.body_span[0] : envelope.body_span[1]]
    canonical = identity_content_envelope(envelope.opening, body, cmd.occurrence_key).rendered
    canonical_envelope = scan_injected_envelopes(canonical)[0]
    return (
        canonical,
        canonical_envelope.body_span[0],
        len(canonical) - canonical_envelope.body_span[1],
    )


async def _diverted(session: Session, cmd: ProcessMessageCommand) -> bool:
    """Relay a visitor's message to the escalation thread; ``False`` when the relay has just ended."""
    try:
        return await divert_visitor_input(session, cmd.text, cmd.actor_name)
    except RelayDeliveryFailed as exc:
        raise SessionMessageRejectedError(
            session_id=session.session_id, reason=SessionMessageRejectionReason.UNAVAILABLE, detail=str(exc)
        ) from exc


async def process_message(
    cmd: ProcessMessageCommand,
    client: "AdapterClient",
    start_polling: StartPollingFunc,
) -> None:
    """Enqueue an incoming user message for durable delivery to the session."""
    del client, start_polling
    await accept_inbound_message(cmd)


async def accept_inbound_message(
    cmd: ProcessMessageCommand, *, message_type: InboundMessageType = InboundMessageType.TEXT
) -> int | None:
    """Accept input for a session into the durable inbound queue; the accepted row, or ``None``.

    ``None`` is a message the queue already holds, or one whose delivery needs nothing: either
    way the input is accepted. ``message_type`` records what kind of input the text is.
    """
    session_id = cmd.session_id
    logger.debug("Enqueueing message for session %s: %s...", session_id, cmd.text[:50])

    session = await db.get_session(session_id)
    if not session:
        raise SessionMessageRejectedError(session_id=session_id, reason=SessionMessageRejectionReason.NOT_FOUND)
    if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        raise SessionMessageRejectedError(session_id=session_id, reason=SessionMessageRejectionReason.CLOSED)
    wake_key = wake_occurrence_key(cmd.text) if cmd.text_kind is TranscriptEntryKind.PLATFORM_CONTROL else None
    wake_observed_inbound_id = await db.latest_inbound_row_id(session_id=session_id) if wake_key is not None else None
    if wake_key is not None and is_agent_turn_running(
        last_input_at=session.last_message_sent_at,
        last_agent_stop_at=session.last_agent_stop_at,
        last_agent_idle_at=session.last_agent_idle_at,
    ):
        await db.clear_procedure_event_wake_opportunity(session_id=session_id, occurrence_id=wake_key)
        return None
    if is_visitor_input(session, cmd.actor_id, cmd.caller_session_id) and await _diverted(session, cmd):
        return None
    if not await _session_message_delivery_available(session):
        raise SessionMessageRejectedError(session_id=session_id, reason=SessionMessageRejectionReason.UNAVAILABLE)

    peer_attention_snapshot = _capture_peer_attention_snapshot(cmd, session)

    origin = cmd.origin or ""
    content, caller_prefix_len, caller_suffix_len = _canonical_caller_content(cmd)
    command_input: _InboundCommandInput | None = None
    project_root = Path(session.project_path) if session.project_path else REPO_ROOT
    resolved_input = resolve_interactive_input(cmd.text, cmd.command_input_mode, project_root)
    if isinstance(resolved_input, ResolvedCommandInput):
        try:
            admit_command_input(cmd.sender_human_role)
            inline = resolve_inline_entry(
                procedure_token=resolved_input.command,
                arguments=resolved_input.args,
                project_root=project_root,
                entry_facts=(
                    recovered_entry_facts(cmd.recovered_posted_at) if cmd.recovered_posted_at is not None else None
                ),
            )
        except (CommandInputError, EntryRefusal) as exc:
            raise SessionMessageRejectedError(
                session_id=session_id,
                reason=SessionMessageRejectionReason.ADMISSION_REFUSED,
                detail=str(exc),
            ) from exc
        content = inline.loader
        command_input = {"source_text": cmd.text, "command": inline.procedure_id, "args": inline.arguments}
    elif cmd.recovered_posted_at is not None:
        content = with_recovered_notice(content, cmd.recovered_posted_at)

    async def _record_after_insert(_row_id: int) -> None:
        accepted_at = await record_accepted_input_metadata(
            session_id=session_id,
            origin=origin,
            message_text=content,
            origin_metadata=cmd.origin_metadata,
            visible_source_text=(command_input["source_text"] if command_input else None),
            caller_session_id=cmd.caller_session_id,
        )
        await record_acceptance_evidence(
            session_id=session_id,
            row_id=_row_id,
            accepted_at=accepted_at,
            runtime_turn_id=session.runtime_turn_id,
        )
        await db.record_procedure_event_wake_acceptance(
            session_id=session_id,
            occurrence_id=wake_key,
            inbound_row_id=_row_id,
            observed_inbound_id=wake_observed_inbound_id,
            observed_session=session,
        )

    row_id = await get_inbound_queue_manager().enqueue(
        session_id=session_id,
        origin=origin,
        content=content,
        message_type=message_type.value,
        text_kind=cmd.text_kind,
        source_feature=cmd.source_feature,
        occurrence_key=cmd.occurrence_key,
        payload_json=_encode_inbound_payload(cmd.origin_metadata, command_input, cmd.recovered_posted_at),
        actor_id=cmd.actor_id,
        actor_name=cmd.actor_name,
        actor_avatar_url=cmd.actor_avatar_url,
        source_message_id=cmd.source_message_id or cmd.occurrence_key,
        source_channel_id=cmd.source_channel_id,
        caller_session_id=cmd.caller_session_id,
        caller_author=_caller_author_from_command(cmd),
        caller_job_role=cmd.caller_job_role,
        caller_origin_prefix_len=caller_prefix_len,
        caller_origin_suffix_len=caller_suffix_len,
        post_insert_callback=_record_after_insert,
    )
    if peer_attention_snapshot is not None:
        await _handoff_peer_attention(
            session_id=session_id,
            snapshot=peer_attention_snapshot,
        )
    if row_id is not None and caller_suffix_len:
        logger.info(
            "conversation_envelope_committed",
            outcome="success",
            inbound_row_id=row_id,
            caller_session_id=cmd.caller_session_id,
            target_session_id=session_id,
            response_boundary=True,
        )
    return row_id
