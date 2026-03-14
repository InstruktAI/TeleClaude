"""Message polling, parsing, and handling for RedisTransport."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import TYPE_CHECKING, Any, cast

from instrukt_ai_logging import get_logger

from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    SystemCommandContext,
    build_agent_payload,
    parse_command_string,
)
from teleclaude.core.models import JsonDict, JsonValue, MessageMetadata, RedisInboundMessage, SessionLaunchIntent
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    GetSessionDataCommand,
    KeysCommand,
    ProcessMessageCommand,
    RestartAgentCommand,
    ResumeAgentCommand,
    RunAgentCommand,
    StartAgentCommand,
)

logger = get_logger(__name__)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from teleclaude.core.adapter_client import AdapterClient


class _MessagingMixin:  # pyright: ignore[reportUnusedClass]
    """Mixin: Redis stream polling, message parsing, command dispatch."""

    if TYPE_CHECKING:
        client: AdapterClient
        computer_name: str
        message_stream_maxlen: int
        _running: bool

        def _reset_idle_poll_log_throttle(self) -> None: ...
        def _maybe_log_idle_poll(self, *, message_stream: str) -> None: ...
        async def _get_redis(self) -> Redis: ...
        async def send_response(self, message_id: str, data: str) -> str: ...
        async def _handle_redis_error(self, context: str, exc: Exception) -> None: ...

    async def _get_last_processed_message_id(self) -> str | None:
        """Get last processed Redis message ID from database.

        Returns:
            Last message ID or None if not found
        """
        try:
            key = f"redis_last_message_id:{self.computer_name}"
            return await db.get_system_setting(key)
        except Exception as e:
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
        except Exception as e:
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
            except Exception as e:
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

            if not parsed.command:
                logger.warning("Invalid message data: %s", data)
                return

            cmd_name, cmd_args = parse_command_string(parsed.command)
            if cmd_name in {"stop_notification", "input_notification"}:
                result = await self._handle_agent_notification_command(cmd_name, cmd_args)
                response_json = json.dumps(result)
                await self.send_response(message_id, response_json)
                return
            if cmd_name in {"list_sessions", "list_projects", "list_projects_with_todos", "get_computer_info"}:
                from teleclaude.core import command_handlers  # pylint: disable=C0415

                if cmd_name == "list_sessions":
                    payload = [s.to_dict() for s in await command_handlers.list_sessions()]
                elif cmd_name == "list_projects":
                    payload = [project.to_dict() for project in await command_handlers.list_projects()]
                elif cmd_name == "list_projects_with_todos":
                    payload = [project.to_dict() for project in await command_handlers.list_projects_with_todos()]
                else:
                    payload = (await command_handlers.get_computer_info()).to_dict()

                response_json = json.dumps({"status": "success", "data": payload})
                await self.send_response(message_id, response_json)
                return

            # Normalize via mapper
            command = CommandMapper.map_redis_input(
                command_str=parsed.command,
                session_id=parsed.session_id,
                project_path=parsed.project_path,
                title=parsed.title,
                channel_metadata=parsed.channel_metadata,
                launch_intent=parsed.launch_intent,
                origin=parsed.origin,
                initiator=parsed.initiator,
            )
            command.request_id = message_id

            launch_intent_obj = None
            if isinstance(parsed.launch_intent, dict):
                launch_intent_obj = SessionLaunchIntent.from_dict(parsed.launch_intent)
            metadata = MessageMetadata(
                channel_metadata=parsed.channel_metadata,
                project_path=parsed.project_path,
                title=parsed.title,
                launch_intent=launch_intent_obj,
            )

            if parsed.initiator:
                # Ensure target_computer set for stop forwarding
                metadata.channel_metadata = metadata.channel_metadata or {}
                metadata.channel_metadata["target_computer"] = parsed.initiator

            logger.info(">>> About to call command service for: %s", command.command_type)
            result = await self._execute_command(command)
            logger.info(">>> command service completed for: %s", command.command_type)

            # Result is always envelope: {"status": "success/error", "data": ..., "error": ...}
            response_json = json.dumps(result)
            logger.info(
                ">>> About to send_response for message_id: %s, response length: %d", message_id, len(response_json)
            )
            await self.send_response(message_id, response_json)
            logger.info(">>> send_response completed for message_id: %s", message_id)

        except Exception as e:
            logger.error("Failed to handle incoming message: %s", e, exc_info=True)
            # Send error response if possible
            try:
                error_response = json.dumps({"status": "error", "error": str(e)})
                await self.send_response(message_id, error_response)
            except Exception:
                pass

    async def _handle_agent_notification_command(self, cmd_name: str, args: list[str]) -> JsonDict:
        """Handle stop_notification/input_notification commands as agent_event payloads."""
        if cmd_name == "stop_notification":
            if len(args) < 2:
                logger.warning(
                    "stop_notification requires at least 2 args (session_id, source_computer), got %d", len(args)
                )
                return {"status": "error", "error": "invalid stop_notification args"}

            target_session_id = args[0]
            source_computer = args[1]
            title_b64 = args[2] if len(args) > 2 and args[2] != "-" else None
            output_b64 = args[3] if len(args) > 3 else None
            resolved_title = None
            linked_output = None

            if title_b64:
                try:
                    resolved_title = base64.b64decode(title_b64).decode()
                except Exception as e:
                    logger.warning("Failed to decode stop_notification title: %s", e)
            if output_b64:
                try:
                    linked_output = base64.b64decode(output_b64).decode()
                except Exception as e:
                    logger.warning("Failed to decode stop_notification linked output: %s", e)

            event_data: JsonDict = {
                "session_id": target_session_id,
                "source_computer": source_computer,
            }
            if resolved_title:
                event_data["title"] = resolved_title
            if linked_output:
                event_data["linked_output"] = linked_output

            context = AgentEventContext(
                session_id=target_session_id,
                event_type=AgentHookEvents.AGENT_STOP,
                data=build_agent_payload(AgentHookEvents.AGENT_STOP, event_data),
            )
            if self.client.agent_event_handler:
                await self.client.agent_event_handler(context)
            return {"status": "success", "data": None}

        return {"status": "error", "error": f"unsupported agent notification: {cmd_name}"}

    async def _execute_command(self, command: object) -> JsonDict:
        """Execute a command via command service and return an envelope."""
        try:
            cmds = get_command_service()
            if isinstance(command, CreateSessionCommand):
                data = await cmds.create_session(command)
                return {"status": "success", "data": cast(JsonValue, data)}
            if isinstance(command, ProcessMessageCommand):
                await cmds.process_message(command)
                return {"status": "success", "data": None}
            if isinstance(command, KeysCommand):
                await cmds.keys(command)
                return {"status": "success", "data": None}
            if isinstance(command, StartAgentCommand):
                await cmds.start_agent(command)
                return {"status": "success", "data": None}
            if isinstance(command, ResumeAgentCommand):
                await cmds.resume_agent(command)
                return {"status": "success", "data": None}
            if isinstance(command, RestartAgentCommand):
                data = await cmds.restart_agent(command)
                return {"status": "success", "data": list(data)}
            if isinstance(command, RunAgentCommand):
                await cmds.run_agent_command(command)
                return {"status": "success", "data": None}
            if isinstance(command, GetSessionDataCommand):
                data = await cmds.get_session_data(command)
                return {"status": "success", "data": cast(JsonValue, data)}
            if isinstance(command, CloseSessionCommand):
                await cmds.close_session(command)
                return {"status": "success", "data": None}
            raise ValueError(f"Unsupported command type: {type(command).__name__}")
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _parse_redis_message(self, data: dict[bytes, bytes]) -> RedisInboundMessage:
        """Decode raw Redis stream entry into typed RedisInboundMessage."""
        msg_type = data.get(b"type", b"").decode("utf-8")
        session_id = data.get(b"session_id", b"").decode("utf-8") or None
        command = data.get(b"command", b"").decode("utf-8")
        origin = data.get(b"origin", b"").decode("utf-8") or InputOrigin.REDIS.value

        channel_metadata: JsonDict | None = None
        if b"channel_metadata" in data:
            try:
                parsed = json.loads(data[b"channel_metadata"].decode("utf-8"))
                if isinstance(parsed, dict):
                    channel_metadata = parsed
            except json.JSONDecodeError:
                logger.warning("Invalid channel_metadata JSON in message")

        initiator = data.get(b"initiator", b"").decode("utf-8") or None
        project_path = data.get(b"project_path", b"").decode("utf-8") or None
        title = data.get(b"title", b"").decode("utf-8") or None
        launch_intent_raw = data.get(b"launch_intent", b"").decode("utf-8") or None
        launch_intent = None
        if launch_intent_raw:
            try:
                parsed_intent = json.loads(launch_intent_raw)
                if isinstance(parsed_intent, dict):
                    launch_intent = cast(JsonDict, parsed_intent)
            except json.JSONDecodeError:
                logger.warning("Invalid launch_intent JSON in message")

        return RedisInboundMessage(
            msg_type=msg_type,
            session_id=session_id,
            command=command,
            channel_metadata=channel_metadata,
            initiator=initiator,
            project_path=project_path,
            title=title,
            origin=origin,
            launch_intent=launch_intent,
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

        event_bus.emit(
            "system_command",
            SystemCommandContext(
                command=command,
                from_computer=from_computer or "unknown",
            ),
        )
