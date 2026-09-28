"""Message polling, parsing, and handling for RedisTransport."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from fastapi import HTTPException
from instrukt_ai_logging import get_logger
from pydantic import TypeAdapter
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.api.auth import CallerIdentity, caller_for_role_resolution, caller_from_carried_identity
from teleclaude.constants import LOGIN_REQUIRED_DETAIL
from teleclaude.core import command_handlers
from teleclaude.core.agent_status_projection import project_peer_agent_status
from teleclaude.core.command_dispatch import execute_command_envelope
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentAttentionObservation,
    SessionOutputStoppedPayload,
    SystemCommand,
    SystemCommandContext,
    parse_command_string,
)
from teleclaude.core.models import JsonDict, RedisInboundMessage
from teleclaude.core.models._types import json_int
from teleclaude.core.operation_outcome_delivery import deliver_remote_operation_outcome
from teleclaude.core.operations import get_operations_service
from teleclaude.core.session_listeners import (
    INFERRED_STALL_EVIDENCE_METADATA_KEY,
    INFERRED_STALL_PANE_TAIL_FIELD,
    INFERRED_STALL_REASON_FIELD,
    InferredStallEvidence,
    NotificationKind,
    StopNotificationVariant,
    build_inferred_stall_evidence,
    deliver_remote_distress_notification,
    deliver_remote_stop_notification,
)
from teleclaude.core.session_message_projection import (
    SessionMessageProjectionOptions,
    build_session_messages_dto,
)
from teleclaude.core.session_pane import get_session_pane
from teleclaude.core.session_status import AgentStatusReason, AgentStatusValue
from teleclaude.events.envelope import EventVisibility
from teleclaude.history.service import (
    HistoryRelayCommand,
    HistoryShowRequest,
    build_history_detail_payload,
    build_history_search_payload,
    parse_history_agents,
)
from teleclaude.mirrors.store import MirrorAccess, history_access_for_caller
from teleclaude.types.commands import command_from_dict
from teleclaude.utils.transcript_discovery import SessionId

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

_AGENT_STATUS_FIELD = "agent_status"
_AGENT_STATUS_EXACT_FIELD = "agent_status_exact"

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
_HISTORY_SHOW_REQUEST_ADAPTER: TypeAdapter[HistoryShowRequest] = TypeAdapter(HistoryShowRequest)
_TAIL_CHARS_FIELD = "tail_chars"
_DEFAULT_TAIL_CHARS = 10000


def _history_access_for_relayed_caller(parsed: RedisInboundMessage) -> MirrorAccess:
    caller = caller_from_carried_identity(
        CallerIdentity(
            session_id=parsed.session_id or "",
            system_role=parsed.system_role,
            human_role=parsed.human_role,
            email=parsed.human_email,
            principal=parsed.caller_principal,
        )
    )
    access = history_access_for_caller(caller)
    if access is None:
        raise PermissionError(LOGIN_REQUIRED_DETAIL)
    return access


def _session_message_projection_options(data: JsonDict) -> SessionMessageProjectionOptions:
    include_tools_raw = data.get("include_tools")
    return SessionMessageProjectionOptions(
        since=str(data["since"]) if data.get("since") is not None else None,
        include_tools=include_tools_raw if isinstance(include_tools_raw, bool) else None,
        include_thinking=bool(data.get("include_thinking")),
        tail_chars=json_int(data.get(_TAIL_CHARS_FIELD) or _DEFAULT_TAIL_CHARS),
        tail_scope=str(data.get("tail_scope") or "all"),
    )


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
                command = command_from_dict(parsed.command_payload)
                command.request_id = message_id
                result = await execute_command_envelope(command, source_computer=parsed.initiator)
                response_json = json.dumps(result)
                await self.send_response(message_id, response_json)
                logger.debug(
                    "Handled redis command payload",
                    command_type=str(command.command_type),
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
            if cmd_name in {
                "list_sessions",
                "list_projects",
                "list_projects_with_todos",
                "get_session_messages",
                "get_session_pane",
                HistoryRelayCommand.SEARCH.value,
                HistoryRelayCommand.SHOW.value,
                "get_session_final_output",
                "get_operation",
            }:
                # ``get_computer_info`` round-trip removed — identity now ships in the heartbeat
                # payload (see ``_heartbeat.py``); peers read it directly in ``discover_peers``.
                if cmd_name == "get_operation":
                    requested_operation_id = str((parsed.origin_metadata or {}).get("operation_id") or "")
                    try:
                        caller = caller_for_role_resolution(
                            CallerIdentity(
                                session_id=parsed.session_id or "",
                                system_role=parsed.system_role,
                                human_role=parsed.human_role,
                                email=parsed.human_email,
                                principal=parsed.caller_principal,
                            )
                        )
                        operation_receipt = await get_operations_service().get_operation_for_caller(
                            operation_id=requested_operation_id,
                            caller_session_id=parsed.session_id or "",
                            caller=caller,
                        )
                        payload = dict(operation_receipt)
                    except HTTPException as exc:
                        response_json = json.dumps({"status": "error", "error": str(exc.detail)})
                        await self.send_response(message_id, response_json)
                        return
                elif cmd_name == "list_sessions":
                    payload = [s.to_peer_dict() for s in await command_handlers.list_sessions()]
                elif cmd_name == "list_projects":
                    payload = [project.to_dict() for project in await command_handlers.list_projects()]
                elif cmd_name == "get_session_messages":
                    options = _session_message_projection_options(parsed.origin_metadata or {})
                    dto = await build_session_messages_dto(
                        parsed.session_id or "",
                        recipient_email=parsed.human_email,
                        recipient_role=parsed.human_role,
                        options=options,
                    )
                    payload = dto.model_dump(mode="json")
                    exact_status = dto.agent_status or AgentStatusValue.UNKNOWN
                    payload[_AGENT_STATUS_FIELD] = project_peer_agent_status(exact_status).value
                    payload[_AGENT_STATUS_EXACT_FIELD] = exact_status.value
                elif cmd_name == "get_session_pane":
                    pane = await get_session_pane(parsed.session_id or "")
                    payload = {
                        "session_id": pane.session_id,
                        "runtime": pane.runtime,
                        "captured_at": pane.captured_at.isoformat(),
                        "available": pane.available,
                        "text": pane.text,
                    }
                elif cmd_name == HistoryRelayCommand.SEARCH.value:
                    search_data = parsed.origin_metadata or {}
                    agent_filter = str(search_data.get("agent") or "all")
                    agents = parse_history_agents(agent_filter)
                    limit_value = search_data.get("limit")
                    limit = limit_value if isinstance(limit_value, int) else 20
                    include_workers_value = search_data.get("include_workers")
                    include_workers = include_workers_value if isinstance(include_workers_value, bool) else False
                    access = _history_access_for_relayed_caller(parsed)
                    payload = await asyncio.to_thread(
                        build_history_search_payload,
                        computer=self.computer_name,
                        query=str(search_data.get("q") or ""),
                        agents=agents,
                        limit=limit,
                        access=access,
                        include_workers=include_workers,
                        identity=(str(search_data["identity"]) if search_data.get("identity") is not None else None),
                        project=(str(search_data["project"]) if search_data.get("project") is not None else None),
                    )
                elif cmd_name == HistoryRelayCommand.SHOW.value:
                    show_data = _HISTORY_SHOW_REQUEST_ADAPTER.validate_python(parsed.origin_metadata or {})
                    session_id = str(SessionId(show_data["session_id"]))
                    agents = parse_history_agents(show_data["agent"])
                    access = _history_access_for_relayed_caller(parsed)
                    payload = await asyncio.to_thread(
                        build_history_detail_payload,
                        session_id,
                        access=access,
                        agents=agents,
                        include_thinking=show_data["thinking"],
                        raw=show_data["raw"],
                    )
                elif cmd_name == "get_session_final_output":
                    final_output_session = await db.get_session(parsed.session_id or "")
                    payload = {
                        "session_id": parsed.session_id or "",
                        "last_output_raw": final_output_session.last_output_raw if final_output_session else None,
                        "last_output_stop_at": (
                            final_output_session.last_output_stop_at.isoformat()
                            if final_output_session and final_output_session.last_output_stop_at
                            else None
                        ),
                    }
                else:
                    payload = [project.to_dict() for project in await command_handlers.list_projects_with_todos()]

                response_json = json.dumps({"status": "success", "data": payload})
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
            )
            return {"status": "success", "data": {"delivered": delivered}}

        return {"status": "error", "error": f"unsupported agent notification: {cmd_name}"}

    def _parse_redis_message(self, data: dict[bytes, bytes]) -> RedisInboundMessage:
        """Decode raw Redis stream entry into typed RedisInboundMessage."""
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
            human_email=_decode_redis_text(data, b"human_email"),
            human_role=_decode_redis_text(data, b"human_role"),
            caller_principal=_decode_redis_text(data, b"caller_principal"),
            system_role=_decode_redis_text(data, b"system_role"),
            job=_decode_redis_text(data, b"job"),
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
