"""Message polling, principal validation, and intake dispatch for RedisTransport.

Caller-facing commands and reads go to relayed intake, where the owning
computer resolves the principal and applies its object-scoped role decision.
The transport validates that a principal exists before decoding the rest of
each relayed entry.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.caller_identity import NoIdentityCliCaller, caller_from_principal
from teleclaude.constants import SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core import command_handlers
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.endpoints import LIVE_ROOTS
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentAttentionObservation,
    SessionOutputStoppedPayload,
    SystemCommand,
    SystemCommandContext,
    parse_command_string,
)
from teleclaude.core.help_desk_relay import RELAY_REPLY_OWNER_COMMAND, answer_owner_query
from teleclaude.core.inbound.adoption import EXPORT_CONVERSATION_SESSIONS_COMMAND, export_local_conversation_sessions
from teleclaude.core.inbound.models import ConversationRef
from teleclaude.core.models import JsonDict, RedisInboundMessage
from teleclaude.core.operation_outcome_delivery import deliver_remote_operation_outcome
from teleclaude.core.origins import InputOrigin
from teleclaude.core.relayed_intake import (
    RelayedReadNotFound,
    RelayRead,
    dispatch_relayed_command,
    execute_relayed_read,
)
from teleclaude.core.session_listeners import (
    DELIVERY_BLOCK_EVIDENCE_METADATA_KEY,
    DELIVERY_BLOCK_PANE_TAIL_FIELD,
    INFERRED_STALL_EVIDENCE_METADATA_KEY,
    INFERRED_STALL_PANE_TAIL_FIELD,
    INFERRED_STALL_REASON_FIELD,
    STARTUP_DELIVERY_UNCERTAIN_EVIDENCE_METADATA_KEY,
    DeliveryBlockEvidence,
    InferredStallEvidence,
    NotificationKind,
    StartupDeliveryUncertainEvidence,
    StopNotificationVariant,
    build_inferred_stall_evidence,
    deliver_remote_distress_notification,
    deliver_remote_stop_notification,
)
from teleclaude.core.session_status import AgentStatusReason
from teleclaude.events.envelope import EventVisibility
from teleclaude.history.service import HistoryRelayCommand

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

_NOT_FOUND_KIND = "not_found"
_REFUSED_BY_TARGET_KIND = "refused_by_target"
_KIND_FIELD = "kind"
_DETAIL_FIELD = "detail"
_STATUS_FIELD = "status"
_ERROR_FIELD = "error"
_DATA_FIELD = "data"
_SUCCESS_STATUS = "success"
_ERROR_STATUS = "error"
_EXPORT_REFUSED_EVENT = "conversation_export_refused"
_EXPORT_REFUSED_DETAIL = "conversation sessions are exported only to another computer's daemon"
_LIST_PROJECTS_COMMAND = "list_projects"
_LIST_PROJECTS_WITH_TODOS_COMMAND = "list_projects_with_todos"
_GET_SESSION_FINAL_OUTPUT_COMMAND = "get_session_final_output"
_LAST_OUTPUT_RAW_FIELD = "last_output_raw"
_LAST_OUTPUT_STOP_AT_FIELD = "last_output_stop_at"
_SESSION_ID_FIELD = "session_id"
_EXPORT_CONVERSATION_ARGUMENT_COUNT = 3
_RELAYED_READ_COMMANDS = frozenset(
    {
        RelayRead.SESSION_MESSAGES.value,
        RelayRead.SESSION_PANE.value,
        RelayRead.OPERATION.value,
        RelayRead.SESSIONS.value,
        RelayRead.SESSION_RECORD.value,
        HistoryRelayCommand.SEARCH.value,
        HistoryRelayCommand.SHOW.value,
    }
)

_DB_EXCEPTIONS = (SQLAlchemyError, OSError, RuntimeError, ValueError, TypeError)
_MESSAGE_EXCEPTIONS = (
    RedisError,
    SQLAlchemyError,
    OSError,
    RuntimeError,
    LookupError,
    ValueError,
    TypeError,
    UnicodeError,
    json.JSONDecodeError,
)
_DECODE_EXCEPTIONS = (binascii.Error, UnicodeError, ValueError)
_SYSTEM_COMMAND_PAYLOAD_REJECTED_EVENT = "system_command_payload_rejected"
_ATTENTION_OBSERVATION_METADATA_KEY = "attention_observation"
_ATTENTION_PROVIDER_KEY = "provider"
_ATTENTION_NATIVE_EVENT_KEY = "native_event"
_ATTENTION_DETAILS_KEY = "details"
_ATTENTION_OBSERVED_AT_KEY = "observed_at"
_ATTENTION_INGRESS_ID_KEY = "ingress_id"
_UNKNOWN_STOP_NOTIFICATION_VARIANT_EVENT = "unknown_stop_notification_variant"
_INVALID_STOP_NOTIFICATION_VARIANT_ERROR = "invalid stop notification variant"
_INVALID_STOP_NOTIFICATION_VARIANT_RESPONSE: JsonDict = {
    "status": "error",
    "error": _INVALID_STOP_NOTIFICATION_VARIANT_ERROR,
}
_STOP_NOTIFICATION_OCCURRED_AT_INDEX = 6
_DISTRESS_NOTIFICATION_OCCURRED_AT_INDEX = 6
_OPERATION_OUTCOME_OCCURRED_AT_INDEX = 6
_WIRE_ABSENT = "-"


def _wire_moment_arg(args: list[str], index: int) -> datetime | None:
    """Read an optional occurrence moment: absent from an older sender, `-` from one that knew none."""
    if len(args) <= index or args[index] == _WIRE_ABSENT:
        return None
    return parse_iso_datetime(args[index])


def _decode_redis_text(data: dict[bytes, bytes], key: bytes) -> str | None:
    """Decode an optional UTF-8 text field from a Redis payload."""
    return data.get(key, b"").decode("utf-8") or None


def _optional_string(value: object) -> str | None:
    """Return a non-empty string from decoded wire metadata."""
    return value if isinstance(value, str) and value else None


def _attention_observation_from_metadata(metadata: JsonDict | None) -> AgentAttentionObservation | None:
    """Decode additive parent-attention evidence at the remote transport boundary."""
    if metadata is None:
        return None
    raw_observation = metadata.get(_ATTENTION_OBSERVATION_METADATA_KEY)
    if not isinstance(raw_observation, dict):
        return None
    details = raw_observation.get(_ATTENTION_DETAILS_KEY)
    return AgentAttentionObservation(
        provider=_optional_string(raw_observation.get(_ATTENTION_PROVIDER_KEY)),
        native_event=_optional_string(raw_observation.get(_ATTENTION_NATIVE_EVENT_KEY)),
        details=MappingProxyType(dict(details)) if isinstance(details, dict) else MappingProxyType({}),
        observed_at=parse_iso_datetime(raw_observation.get(_ATTENTION_OBSERVED_AT_KEY)),
        ingress_id=_optional_string(raw_observation.get(_ATTENTION_INGRESS_ID_KEY)),
    )


def _inferred_stall_evidence_from_metadata(metadata: JsonDict | None) -> InferredStallEvidence | None:
    """Decode additive daemon-side stall evidence, ignoring older unknown shapes."""
    if metadata is None:
        return None
    raw_evidence = metadata.get(INFERRED_STALL_EVIDENCE_METADATA_KEY)
    if not isinstance(raw_evidence, dict):
        return None
    raw_reason = raw_evidence.get(INFERRED_STALL_REASON_FIELD)
    try:
        reason = AgentStatusReason(str(raw_reason))
    except ValueError:
        logger.warning("Ignoring malformed inferred stall reason", reason=raw_reason)
        return None
    raw_pane_tail = raw_evidence.get(INFERRED_STALL_PANE_TAIL_FIELD)
    pane_tail = raw_pane_tail if isinstance(raw_pane_tail, str) else None
    try:
        return build_inferred_stall_evidence(reason, pane_tail)
    except ValueError:
        logger.warning("Ignoring unsupported inferred stall reason", reason=reason)
        return None


def _delivery_block_evidence_from_metadata(metadata: JsonDict | None) -> DeliveryBlockEvidence | None:
    """Decode additive daemon-side delivery evidence, ignoring older unknown shapes."""
    if metadata is None:
        return None
    raw_evidence = metadata.get(DELIVERY_BLOCK_EVIDENCE_METADATA_KEY)
    if not isinstance(raw_evidence, dict):
        return None
    raw_pane_tail = raw_evidence.get(DELIVERY_BLOCK_PANE_TAIL_FIELD)
    return DeliveryBlockEvidence(pane_tail=raw_pane_tail if isinstance(raw_pane_tail, str) else "")


def _startup_delivery_uncertain_evidence_from_metadata(
    metadata: JsonDict | None,
) -> StartupDeliveryUncertainEvidence | None:
    """Decode additive daemon-side startup evidence, ignoring older unknown shapes."""
    if metadata is None:
        return None
    if not isinstance(metadata.get(STARTUP_DELIVERY_UNCERTAIN_EVIDENCE_METADATA_KEY), dict):
        return None
    return StartupDeliveryUncertainEvidence()


class _MessagingMixin:  # pyright: ignore[reportUnusedClass]
    """Mixin: Redis stream polling, message parsing, command dispatch."""

    if TYPE_CHECKING:
        client: AdapterClient
        computer_name: str
        message_stream_maxlen: int
        _running: bool

        def _reset_idle_poll_log_throttle(self) -> None:
            """Reset idle-poll logging state."""
            raise NotImplementedError

        def _maybe_log_idle_poll(self, *, message_stream: str) -> None:
            """Log or suppress an idle-poll event."""
            _ = message_stream
            raise NotImplementedError

        async def _get_redis(self) -> Redis:
            """Return an active Redis client."""
            raise NotImplementedError

        async def send_response(self, message_id: str, data: str) -> str:
            """Send a Redis request/response payload."""
            _ = (message_id, data)
            raise NotImplementedError

        async def _handle_redis_error(self, context: str, exc: Exception) -> None:
            """Handle a Redis failure and schedule reconnect behavior."""
            _ = (context, exc)
            raise NotImplementedError

    async def _get_last_processed_message_id(self) -> str | None:
        """Get last processed Redis message ID from database.

        Returns:
            Last message ID or None if not found
        """
        try:
            key = f"redis_last_message_id:{self.computer_name}"
            return await db.get_system_setting(key)
        except _DB_EXCEPTIONS as e:
            logger.warning("Failed to get last processed message ID: %s", e)
            return None

    async def _set_last_processed_message_id(self, message_id: str) -> None:
        """Persist last processed Redis message ID to database.

        Args:
            message_id: Redis stream message ID
        """
        try:
            key = f"redis_last_message_id:{self.computer_name}"
            await db.set_system_setting(key, message_id)
        except _DB_EXCEPTIONS as e:
            logger.error("Failed to persist last processed message ID: %s", e)

    async def _poll_redis_messages(self) -> None:
        """Background task: Poll messages:{computer_name} stream for incoming messages."""

        message_stream = f"messages:{self.computer_name}"
        self._reset_idle_poll_log_throttle()

        # Load last processed message ID from database (prevents re-processing on restart)
        last_id_str = await self._get_last_processed_message_id()
        if last_id_str:
            last_id = last_id_str.encode("utf-8")
            logger.info("Starting Redis message polling: %s (resuming from last_id=%s)", message_stream, last_id_str)
        else:
            # First startup - use current time to avoid processing old messages
            last_id = b"$"  # $ means "latest" in Redis
            logger.info("Starting Redis message polling: %s (from current time - first startup)", message_stream)

        while self._running:
            try:
                # Read messages from stream (blocking)
                # logger.debug(
                #     "About to XREAD from %s with last_id=%s, block=1000ms",
                #     message_stream,
                #     last_id,
                # )

                redis_client = await self._get_redis()
                messages: list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]] = await redis_client.xread(
                    {message_stream.encode("utf-8"): last_id},
                    block=1000,  # Block for 1 second
                    count=5,
                )

                # logger.debug(
                #     "XREAD returned %d stream(s) with messages",
                #     len(messages) if messages else 0,
                # )

                if not messages:
                    self._maybe_log_idle_poll(message_stream=message_stream)
                    continue

                self._reset_idle_poll_log_throttle()

                # Process commands
                for (
                    stream_name,
                    stream_messages,
                ) in messages:
                    stream_name_str: str = stream_name.decode("utf-8")
                    logger.debug(
                        "Stream %s has %d message(s)",
                        stream_name_str,
                        len(stream_messages),
                    )

                    for message_id, data in stream_messages:
                        logger.debug(
                            "Processing message %s with data keys: %s",
                            message_id.decode("utf-8"),
                            [k.decode("utf-8") for k in data.keys()],
                        )

                        # Persist last_id BEFORE processing to prevent re-processing on restart
                        # This is critical for commands that call os._exit(0) (e.g., restart)
                        last_id = message_id
                        msg_id_str: str = last_id.decode("utf-8")
                        await self._set_last_processed_message_id(msg_id_str)
                        logger.debug("Saved last_id %s before processing", msg_id_str)

                        # Process message with Redis message_id for response correlation
                        await self._handle_incoming_message(msg_id_str, data)

            except asyncio.CancelledError:
                break
            except _MESSAGE_EXCEPTIONS as e:
                await self._handle_redis_error("Message polling error", e)

    async def _handle_incoming_message(self, message_id: str, data: dict[bytes, bytes]) -> Any:
        """Handle incoming message from Redis stream.

        Args:
            message_id: Redis stream entry ID (used for response correlation via output:{computer}:{message_id})
            data: Message data dict from Redis stream
        """
        try:
            parsed = self._parse_redis_message(data)

            if parsed.msg_type == "system":
                return await self._handle_system_message(data)

            if parsed.command_payload is not None:
                result = await dispatch_relayed_command(
                    parsed.command_payload,
                    parsed.caller_principal,
                    request_id=message_id,
                    source_computer=parsed.initiator,
                )
                response_json = json.dumps(result)
                await self.send_response(message_id, response_json)
                logger.debug(
                    "Handled redis command payload",
                    command_type=str(parsed.command_payload.get("command_type")),
                    message_id=message_id,
                    response_len=len(response_json),
                )
                return

            if not parsed.command:
                logger.warning("Invalid message data: %s", data)
                return

            cmd_name, cmd_args = parse_command_string(parsed.command)
            if cmd_name in {"stop_notification", "distress_notification", "operation_outcome"}:
                result = await self._handle_agent_notification_command(cmd_name, cmd_args, parsed.origin_metadata)
                response_json = json.dumps(result)
                await self.send_response(message_id, response_json)
                return
            if cmd_name in _RELAYED_READ_COMMANDS:
                try:
                    payload = await execute_relayed_read(cmd_name, parsed)
                    response_envelope: JsonDict = {
                        _STATUS_FIELD: _SUCCESS_STATUS,
                        _DATA_FIELD: payload,
                    }
                except RelayedReadNotFound as exc:
                    response_envelope = {
                        _STATUS_FIELD: "error",
                        _ERROR_FIELD: {_KIND_FIELD: _NOT_FOUND_KIND, _DETAIL_FIELD: str(exc)},
                    }
                except PermissionError as exc:
                    response_envelope = {
                        _STATUS_FIELD: "error",
                        _ERROR_FIELD: {_KIND_FIELD: _REFUSED_BY_TARGET_KIND, _DETAIL_FIELD: str(exc)},
                    }
                await self.send_response(message_id, json.dumps(response_envelope))
                return

            if cmd_name == EXPORT_CONVERSATION_SESSIONS_COMMAND:
                # Conversation keys, session ids and endpoints are this computer's private
                # records: only another daemon, forwarding on its own account, may read them.
                if parsed.caller_principal != SYSTEM_DAEMON_PRINCIPAL:
                    logger.warning(_EXPORT_REFUSED_EVENT, caller_principal=parsed.caller_principal)
                    refusal: JsonDict = {
                        _STATUS_FIELD: _ERROR_STATUS,
                        _ERROR_FIELD: {_KIND_FIELD: _REFUSED_BY_TARGET_KIND, _DETAIL_FIELD: _EXPORT_REFUSED_DETAIL},
                    }
                    await self.send_response(message_id, json.dumps(refusal))
                    return
                conversation = (
                    ConversationRef(
                        origin=InputOrigin(cmd_args[0]),
                        key_field=cmd_args[1],
                        key=cmd_args[2],
                        reaches_every_computer=True,
                    )
                    if len(cmd_args) == _EXPORT_CONVERSATION_ARGUMENT_COUNT
                    else None
                )
                exported = await export_local_conversation_sessions(db, LIVE_ROOTS, conversation)
                await self.send_response(
                    message_id,
                    json.dumps({_STATUS_FIELD: _SUCCESS_STATUS, _DATA_FIELD: [item.to_dict() for item in exported]}),
                )
                return

            if cmd_name == RELAY_REPLY_OWNER_COMMAND:
                try:
                    owner_answer = await answer_owner_query(cmd_args, parsed.caller_principal)
                    owner_envelope: JsonDict = {_STATUS_FIELD: _SUCCESS_STATUS, _DATA_FIELD: owner_answer.value}
                except PermissionError as exc:
                    owner_envelope = {
                        _STATUS_FIELD: _ERROR_STATUS,
                        _ERROR_FIELD: {_KIND_FIELD: _REFUSED_BY_TARGET_KIND, _DETAIL_FIELD: str(exc)},
                    }
                await self.send_response(message_id, json.dumps(owner_envelope))
                return

            if cmd_name in {
                _LIST_PROJECTS_COMMAND,
                _LIST_PROJECTS_WITH_TODOS_COMMAND,
                _GET_SESSION_FINAL_OUTPUT_COMMAND,
            }:
                # ``get_computer_info`` round-trip removed — identity now ships in the heartbeat
                # payload (see ``_heartbeat.py``); peers read it directly in ``discover_peers``.
                if cmd_name == _LIST_PROJECTS_COMMAND:
                    payload = [project.to_dict() for project in await command_handlers.list_projects()]
                elif cmd_name == _GET_SESSION_FINAL_OUTPUT_COMMAND:
                    final_output_session = await db.get_session(parsed.session_id or "")
                    payload = {
                        _SESSION_ID_FIELD: parsed.session_id or "",
                        _LAST_OUTPUT_RAW_FIELD: final_output_session.last_output_raw if final_output_session else None,
                        _LAST_OUTPUT_STOP_AT_FIELD: (
                            final_output_session.last_output_stop_at.isoformat()
                            if final_output_session and final_output_session.last_output_stop_at
                            else None
                        ),
                    }
                else:
                    payload = [project.to_dict() for project in await command_handlers.list_projects_with_todos()]

                response_json = json.dumps({_STATUS_FIELD: _SUCCESS_STATUS, _DATA_FIELD: payload})
                await self.send_response(message_id, response_json)
                return

            logger.warning("Unsupported Redis string command: %s", parsed.command)
            await self.send_response(
                message_id,
                json.dumps({"status": "error", "error": f"Unsupported Redis string command: {parsed.command}"}),
            )

        except _MESSAGE_EXCEPTIONS as e:
            logger.error("Failed to handle incoming message: %s", e, exc_info=True)
            # Send error response if possible
            try:
                error_response = json.dumps({"status": "error", "error": str(e)})
                await self.send_response(message_id, error_response)
            except (RedisError, OSError, RuntimeError, ValueError, TypeError):
                logger.debug("Failed to send Redis error response for %s", message_id, exc_info=True)

    async def _handle_agent_notification_command(
        self, cmd_name: str, args: list[str], origin_metadata: JsonDict | None
    ) -> JsonDict:
        """Handle direct caller-notification commands delivered across computers.

        These arrive on the initiator's own daemon, naming a session that was
        created elsewhere — there is no local row for it, and so no local
        listener row either. Delivery resolves the caller (also named on the
        wire) and injects straight into its host pane, rather than re-entering
        the generic agent-event pipeline built for locally-owned sessions.
        """
        if cmd_name == "stop_notification":
            if len(args) < 3:
                logger.warning(
                    "stop_notification requires at least 3 args (session_id, source_computer, "
                    "caller_session_id), got %d",
                    len(args),
                )
                return {"status": "error", "error": "invalid stop_notification args"}

            target_session_id = args[0]
            source_computer = args[1]
            caller_session_id = args[2]
            title_b64 = args[3] if len(args) > 3 and args[3] != "-" else None
            occurrence_key = args[4] if len(args) > 4 else None
            notification_variant = StopNotificationVariant.INSPECT
            if len(args) > 5:
                try:
                    notification_variant = StopNotificationVariant(args[5])
                except ValueError:
                    logger.warning(_UNKNOWN_STOP_NOTIFICATION_VARIANT_EVENT, variant=args[5])
                    return dict(_INVALID_STOP_NOTIFICATION_VARIANT_RESPONSE)
            resolved_title = None

            if title_b64:
                try:
                    resolved_title = base64.b64decode(title_b64).decode()
                except _DECODE_EXCEPTIONS as e:
                    logger.warning("Failed to decode stop_notification title: %s", e)

            await deliver_remote_stop_notification(
                caller_session_id=caller_session_id,
                target_session_id=target_session_id,
                computer=source_computer,
                title=resolved_title,
                occurrence_key=occurrence_key,
                variant=notification_variant,
                occurred_at=_wire_moment_arg(args, _STOP_NOTIFICATION_OCCURRED_AT_INDEX),
            )
            return {"status": "success", "data": None}

        if cmd_name == "distress_notification":
            if len(args) < 5:
                return {"status": "error", "error": "invalid distress_notification args"}
            target_session_id, source_computer, caller_session_id, raw_kind, title_b64 = args[:5]
            occurrence_key = args[5] if len(args) > 5 else None
            try:
                notification_kind = NotificationKind(raw_kind)
            except ValueError:
                return {"status": "error", "error": "invalid distress notification kind"}
            title = None
            if title_b64 != "-":
                try:
                    title = base64.b64decode(title_b64).decode()
                except _DECODE_EXCEPTIONS:
                    return {"status": "error", "error": "invalid distress notification title"}
            delivered = await deliver_remote_distress_notification(
                caller_session_id,
                target_session_id,
                source_computer,
                notification_kind,
                title,
                occurrence_key,
                _attention_observation_from_metadata(origin_metadata),
                _inferred_stall_evidence_from_metadata(origin_metadata),
                _delivery_block_evidence_from_metadata(origin_metadata),
                _startup_delivery_uncertain_evidence_from_metadata(origin_metadata),
                occurred_at=_wire_moment_arg(args, _DISTRESS_NOTIFICATION_OCCURRED_AT_INDEX),
            )
            return {"status": "success", "data": {"delivered": delivered}}

        if cmd_name == "operation_outcome":
            if len(args) < 5:
                return {"status": "error", "error": "invalid operation_outcome args"}
            operation_id, owning_computer, caller_session_id, kind, outcome = args[:5]
            slug = args[5] if len(args) > 5 and args[5] != "-" else None
            delivered = await deliver_remote_operation_outcome(
                caller_session_id,
                operation_id,
                owning_computer,
                kind,
                outcome,
                slug,
                occurred_at=_wire_moment_arg(args, _OPERATION_OUTCOME_OCCURRED_AT_INDEX),
            )
            return {"status": "success", "data": {"delivered": delivered}}

        return {"status": "error", "error": f"unsupported agent notification: {cmd_name}"}

    def _parse_redis_message(self, data: dict[bytes, bytes]) -> RedisInboundMessage:
        """Decode raw Redis stream entry into typed RedisInboundMessage."""
        caller_principal = _decode_redis_text(data, b"caller_principal")
        if caller_principal is None or isinstance(caller_from_principal(caller_principal), NoIdentityCliCaller):
            raise ValueError("Malformed Redis stream entry: missing or invalid caller principal")
        msg_type = _decode_redis_text(data, b"type") or ""
        session_id = _decode_redis_text(data, b"session_id")
        command = _decode_redis_text(data, b"command") or ""
        command_payload: JsonDict | None = None
        command_payload_raw = _decode_redis_text(data, b"command_payload")
        if command_payload_raw:
            parsed_command_payload = json.loads(command_payload_raw)
            if not isinstance(parsed_command_payload, dict):
                raise ValueError("command_payload must be a JSON object")
            command_payload = cast(JsonDict, parsed_command_payload)
        # origin is a client-stamped session concept (InputOrigin), carried in the
        # command payload only for genuine user-input relays. System RPCs and
        # internal ops carry none — the transport neither requires nor invents it.
        origin_raw = _decode_redis_text(data, b"origin")
        launch_intent = None
        launch_intent_raw = _decode_redis_text(data, b"launch_intent")
        if launch_intent_raw:
            try:
                parsed_intent = json.loads(launch_intent_raw)
                if isinstance(parsed_intent, dict):
                    launch_intent = cast(JsonDict, parsed_intent)
            except json.JSONDecodeError:
                logger.warning("Invalid launch_intent JSON in message")
        origin_metadata: JsonDict | None = None
        origin_metadata_raw = _decode_redis_text(data, b"origin_metadata")
        if origin_metadata_raw:
            try:
                parsed_origin_metadata = json.loads(origin_metadata_raw)
                if isinstance(parsed_origin_metadata, dict):
                    origin_metadata = cast(JsonDict, parsed_origin_metadata)
            except json.JSONDecodeError:
                logger.warning("Invalid origin_metadata JSON in message")

        return RedisInboundMessage(
            msg_type=msg_type,
            session_id=session_id,
            command=command,
            command_payload=command_payload,
            actor_id=_decode_redis_text(data, b"actor_id"),
            actor_name=_decode_redis_text(data, b"actor_name"),
            actor_avatar_url=_decode_redis_text(data, b"actor_avatar_url"),
            platform_message_id=_decode_redis_text(data, b"platform_message_id"),
            initiator=_decode_redis_text(data, b"initiator"),
            project_path=_decode_redis_text(data, b"project_path"),
            title=_decode_redis_text(data, b"title"),
            origin=origin_raw,
            origin_metadata=origin_metadata,
            launch_intent=launch_intent,
            caller_principal=caller_principal,
        )

    async def _handle_system_message(self, data: dict[bytes, bytes]) -> None:
        """Handle incoming system message from Redis stream.

        System messages are daemon-level commands, not session-specific.

        Args:
            data: System message data dict from Redis stream
        """
        command = data.get(b"command", b"").decode("utf-8")
        from_computer = data.get(b"from_computer", b"").decode("utf-8")

        if not command:
            logger.warning("Invalid system command data: %s", data)
            return

        logger.info("Received system command '%s' from %s", command, from_computer)

        payload: SessionOutputStoppedPayload | None = None
        try:
            known_command = SystemCommand(command)
        except ValueError:
            known_command = None

        if known_command is SystemCommand.SESSION_OUTPUT_STOPPED:
            raw_args = data.get(b"args", b"")
            decoded_args: object = None
            if raw_args:
                try:
                    decoded_args = json.loads(raw_args.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeError):
                    decoded_args = None
            payload = SessionOutputStoppedPayload.from_dict(decoded_args)
            if payload is None:
                logger.warning(_SYSTEM_COMMAND_PAYLOAD_REJECTED_EVENT, command=command, from_computer=from_computer)
                return

        event_bus.emit(
            "system_command",
            SystemCommandContext(
                command=command,
                from_computer=from_computer or "unknown",
                payload=payload,
            ),
            visibility=EventVisibility.CLUSTER,
        )
