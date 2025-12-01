"""Redis adapter for AI-to-AI communication via Redis Streams.

This adapter enables reliable cross-computer messaging for TeleClaude using
Redis Streams as the transport layer. It bypasses Telegram's bot-to-bot
messaging restriction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from redis.asyncio import Redis

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import EventType, TeleClaudeEvents, parse_command_string
from teleclaude.core.models import (
    ChannelMetadata,
    MessageMetadata,
    PeerInfo,
    RedisAdapterMetadata,
)
from teleclaude.core.protocols import RemoteExecutionProtocol

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = logging.getLogger(__name__)


class RedisAdapter(BaseAdapter, RemoteExecutionProtocol):
    """Adapter for AI-to-AI communication via Redis Streams.

    Uses Redis Streams for reliable, ordered message delivery between computers.

    Implements RemoteExecutionProtocol for cross-computer orchestration.

    Architecture:
    - Each computer polls its message stream: messages:{computer_name}
    - Each session has an output stream: output:{session_id}
    - Computer registry uses Redis keys with TTL for heartbeats

    Message flow:
    - Comp1 → XADD messages:comp2 → Comp2 polls → executes message
    - Comp2 → XADD output:session_id → Comp1 polls → streams to MCP
    """

    def __init__(self, adapter_client: "AdapterClient"):
        """Initialize Redis adapter.

        Args:
            adapter_client: AdapterClient instance for event emission
        """
        super().__init__()

        # Store adapter client reference (ONLY interface to daemon)
        self.client = adapter_client

        # Get global config singleton
        self.redis: Redis
        self._message_poll_task: Optional[asyncio.Task[None]] = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        self._output_stream_listeners: dict[str, asyncio.Task[None]] = {}  # session_id -> listener task
        self._running = False

        # Extract Redis configuration from global config
        self.redis_url = config.redis.url
        self.redis_password = config.redis.password
        self.computer_name = config.computer.name

        # Redis connection settings
        self.max_connections = config.redis.max_connections
        self.socket_timeout = config.redis.socket_timeout

        # Stream configuration
        self.message_stream_maxlen = config.redis.message_stream_maxlen
        self.output_stream_maxlen = config.redis.output_stream_maxlen
        self.output_stream_ttl = config.redis.output_stream_ttl

        # Heartbeat config
        self.heartbeat_interval = 30  # Send heartbeat every 30s
        self.heartbeat_ttl = 60  # Key expires after 60s

        # Track pending new_session requests for response
        self._pending_new_session_request: Optional[str] = None

        logger.info("RedisAdapter initialized for computer: %s", self.computer_name)

    async def start(self) -> None:
        """Initialize Redis connection and start background tasks."""
        if self._running:
            logger.warning("RedisAdapter already running")
            return

        # Create Redis client with TLS support
        self.redis = Redis.from_url(  # type: ignore[misc]  # Redis library returns type[Redis] with Any
            self.redis_url,
            password=self.redis_password,
            max_connections=self.max_connections,
            socket_timeout=self.socket_timeout,
            decode_responses=False,  # We handle decoding manually
            ssl_cert_reqs=ssl.CERT_NONE,  # Disable certificate verification for self-signed certs
        )

        # Test connection
        try:
            await self.redis.ping()  # type: ignore[misc]  # Redis.ping() returns Awaitable[bool] | bool | Any
            logger.info("Redis connection successful")
        except Exception as e:
            logger.error("Failed to connect to Redis: %s", e)
            raise

        self._running = True

        # Start background tasks
        self._message_poll_task = asyncio.create_task(self._poll_redis_messages())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info("RedisAdapter started")

    async def stop(self) -> None:
        """Stop adapter and cleanup resources."""
        if not self._running:
            return

        self._running = False

        # Cancel background tasks
        if self._message_poll_task:
            self._message_poll_task.cancel()
            try:
                await self._message_poll_task
            except asyncio.CancelledError:
                pass

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Cancel all output stream listeners
        for _, task in list(self._output_stream_listeners.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._output_stream_listeners.clear()

        # Close Redis connection
        if self.redis:
            await self.redis.aclose()

        logger.info("RedisAdapter stopped")

    async def _get_last_processed_message_id(self) -> Optional[str]:
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

    async def send_message(self, session: "Session", text: str, metadata: MessageMetadata) -> str:
        """Send message chunk to Redis output stream.

        Args:
            session: Session object
            text: Message text (output chunk)
            metadata: Optional metadata (ignored for Redis)

        Returns:
            Redis stream entry ID as message_id
        """

        # Trust contract: create_channel already set up metadata
        output_stream = session.adapter_metadata.redis.channel_id

        # Send to Redis stream
        message_id_bytes: bytes = await self.redis.xadd(
            output_stream,
            {
                b"chunk": text.encode("utf-8"),
                b"timestamp": str(time.time()).encode("utf-8"),
                b"session_id": session.session_id.encode("utf-8"),
            },
            maxlen=self.output_stream_maxlen,
        )

        logger.debug("Sent to Redis stream %s: %s", output_stream, message_id_bytes)
        return message_id_bytes.decode("utf-8")

    async def edit_message(self, session: "Session", message_id: str, text: str, metadata: MessageMetadata) -> bool:
        """Redis streams don't support editing - send new message instead.

        Args:
            session: Session object
            message_id: Message ID (ignored)
            text: New text
            metadata: Optional metadata

        Returns:
            True (always succeeds by sending new message)
        """
        await self.send_message(session, text, metadata)
        return True

    async def delete_message(self, session: "Session", message_id: str) -> bool:
        """Delete message from Redis stream.

        Args:
            session: Session object
            message_id: Redis stream entry ID

        Returns:
            True if successful
        """

        # Trust contract: create_channel already set up metadata
        output_stream = session.adapter_metadata.redis.output_stream

        try:
            await self.redis.xdel(output_stream, message_id)
            return True
        except Exception as e:
            logger.error("Failed to delete message %s: %s", message_id, e)
            return False

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """Send error envelope to Redis output stream.

        Args:
            session_id: Session that encountered error
            error_message: Human-readable error description
        """

        try:
            output_stream = f"output:{session_id}"
            await self.redis.xadd(
                output_stream,
                {
                    b"type": b"error",
                    b"error": error_message.encode("utf-8"),
                    b"timestamp": str(time.time()).encode("utf-8"),
                    b"session_id": session_id.encode("utf-8"),
                },
                maxlen=self.output_stream_maxlen,
            )
            logger.debug("Sent error to Redis stream %s: %s", output_stream, error_message)
        except Exception as e:
            logger.error("Failed to send error feedback for session %s: %s", session_id, e)

    async def send_file(
        self,
        session: "Session",
        file_path: str,
        metadata: MessageMetadata,
        caption: Optional[str] = None,
    ) -> str:
        """Send file - not supported by Redis adapter.

        Args:
            session: Session object
            file_path: Path to file
            metadata: Optional metadata
            caption: Optional caption

        Returns:
            Empty string (not supported)
        """
        logger.warning("send_file not supported by RedisAdapter")
        return ""

    async def send_general_message(self, text: str, metadata: MessageMetadata) -> str:
        """Send general message (not implemented for Redis).

        Redis adapter is session-specific, no general channel.

        Args:
            text: Message text
            metadata: Optional metadata

        Returns:
            Empty string
        """
        logger.warning("send_general_message not supported by RedisAdapter")
        return ""

    async def create_channel(
        self, session: "Session", title: str, metadata: ChannelMetadata  # type: ignore[name-defined]
    ) -> str:
        """Create Redis streams for session.

        For AI-to-AI sessions (with target_computer): Creates command + output streams.
        For local sessions (no target_computer): Creates only output stream.

        Args:
            session: Session object
            title: Channel title
            metadata: Optional ChannelMetadata (may contain target_computer for AI-to-AI sessions)

        Returns:
            Output stream name as channel_id
        """

        output_stream = f"output:{session.session_id}"

        # Get or create redis metadata in adapter namespace
        redis_meta = session.adapter_metadata.redis
        if not redis_meta:
            redis_meta = RedisAdapterMetadata()
            session.adapter_metadata.redis = redis_meta

        redis_meta.channel_id = output_stream
        redis_meta.output_stream = output_stream

        # Store target computer from metadata if present
        if metadata.target_computer:
            redis_meta.target_computer = metadata.target_computer
            logger.info(
                "Created Redis streams for AI-to-AI session %s: target=%s, output=%s",
                session.session_id[:8],
                metadata.target_computer,
                output_stream,
            )
        else:
            logger.debug(
                "Created Redis output stream for local session %s: %s (no target computer)",
                session.session_id[:8],
                output_stream,
            )

        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)

        return output_stream

    async def update_channel_title(self, session: "Session", title: str) -> bool:  # type: ignore[name-defined]
        """Update channel title (no-op for Redis).

        Args:
            session: Session object
            title: New title

        Returns:
            True
        """
        return True

    async def close_channel(self, session: "Session") -> bool:  # type: ignore[name-defined]
        """No-op: Redis has no persistent channels to close.

        Args:
            session: Session object

        Returns:
            True (always succeeds)
        """
        return True

    async def reopen_channel(self, session: "Session") -> bool:  # type: ignore[name-defined]
        """No-op: Redis has no persistent channels to reopen.

        Args:
            session: Session object

        Returns:
            True (always succeeds)
        """
        return True

    async def delete_channel(self, session: "Session") -> bool:  # type: ignore[name-defined]
        """Delete Redis stream.

        Args:
            session: Session object

        Returns:
            True if successful
        """

        # Trust contract: create_channel already set up metadata
        output_stream = session.adapter_metadata.redis.output_stream

        try:
            await self.redis.delete(output_stream)
            return True
        except Exception as e:
            logger.error("Failed to delete stream %s: %s", output_stream, e)
            return False

    async def _get_online_computers(self) -> list[str]:
        """Get list of online computer names from Redis heartbeat keys.

        Reusable helper for discovering online computers without enriching
        with computer_info. Used by discover_peers() and session aggregation.

        Returns:
            List of computer names (excluding self)
        """

        try:
            # Find all heartbeat keys
            keys: object = await self.redis.keys(b"computer:*:heartbeat")
            logger.debug("Found %d heartbeat keys", len(keys))  # type: ignore[arg-type]

            computers = []
            for key in keys:  # type: ignore[misc, attr-defined]
                # Get data
                data_bytes: object = await self.redis.get(key)  # type: ignore[misc]
                if data_bytes:
                    # Redis returns bytes - decode to str for json.loads
                    data_str: str = data_bytes.decode("utf-8")  # type: ignore[attr-defined]
                    info_obj: object = json.loads(data_str)
                    if not isinstance(info_obj, dict):
                        continue
                    info: dict[str, object] = info_obj

                    computer_name: str = str(info["computer_name"])

                    # Skip self
                    if computer_name == self.computer_name:
                        continue

                    computers.append(computer_name)

            return sorted(computers)

        except Exception as e:
            logger.error("Failed to get online computers: %s", e)
            return []

    async def discover_peers(self) -> list[PeerInfo]:
        """Discover peers via Redis heartbeat keys.

        Returns:
            List of PeerInfo instances with peer computer information
        """
        logger.info(">>> discover_peers() called, self.redis=%s", "present" if self.redis else "None")

        try:
            # Find all heartbeat keys
            keys: object = await self.redis.keys(b"computer:*:heartbeat")
            logger.info(">>> discover_peers found %d heartbeat keys: %s", len(keys), keys)  # type: ignore[arg-type]

            peers = []
            for key in keys:  # type: ignore[misc, attr-defined]  # key is Any from Redis.keys() iteration, keys is object
                # Get data
                data_bytes: object = await self.redis.get(key)  # type: ignore[misc]  # Redis.get() returns Any
                if data_bytes:
                    # Redis returns bytes - decode to str for json.loads
                    data_str: str = data_bytes.decode("utf-8")  # type: ignore[attr-defined]  # Redis returns bytes
                    info_obj: object = json.loads(data_str)
                    if not isinstance(info_obj, dict):
                        continue
                    info: dict[str, object] = info_obj

                    last_seen_str: object = info.get("last_seen", "")
                    try:
                        last_seen_dt = datetime.fromisoformat(str(last_seen_str))
                    except (ValueError, TypeError):
                        last_seen_dt = datetime.now()

                    computer_name: str = str(info["computer_name"])

                    # Skip self
                    if computer_name == self.computer_name:
                        logger.debug("Skipping self: %s", computer_name)
                        continue

                    logger.debug("Requesting computer_info from %s", computer_name)

                    # Request computer info via get_computer_info command
                    # Transport layer generates request_id from Redis message ID
                    computer_info = None
                    try:
                        message_id = await self.send_request(computer_name, "get_computer_info", MessageMetadata())
                        logger.debug("Sent get_computer_info to %s, message_id=%s", computer_name, message_id[:15])

                        # Wait for response (short timeout) - use read_response for one-shot query
                        response_data = await self.client.read_response(message_id, timeout=3.0)
                        envelope_obj: object = json.loads(response_data.strip())
                        if not isinstance(envelope_obj, dict):
                            continue
                        envelope: dict[str, object] = envelope_obj

                        # Unwrap envelope response
                        status: object = envelope.get("status")
                        if status == "error":
                            error_msg: object = envelope.get("error")
                            logger.warning("Computer %s returned error: %s", computer_name, error_msg)
                            continue

                        # Extract data from success envelope
                        computer_info = envelope.get("data")
                        if not computer_info or not isinstance(computer_info, dict):
                            logger.warning("Invalid response data from %s: %s", computer_name, type(computer_info))
                            continue

                        logger.debug("Received valid computer_info from %s", computer_name)

                    except (TimeoutError, Exception) as e:
                        logger.warning("Failed to get info from %s: %s", computer_name, e)
                        continue  # Skip this peer if request fails

                    # Extract peer info with type conversions
                    user_val: object = computer_info.get("user")
                    host_val: object = computer_info.get("host")
                    ip_val: object = computer_info.get("ip")

                    peers.append(
                        PeerInfo(
                            name=computer_name,
                            status="online",
                            last_seen=last_seen_dt,
                            adapter_type="redis",
                            user=str(user_val) if user_val else None,
                            host=str(host_val) if host_val else None,
                            ip=str(ip_val) if ip_val else None,
                        )
                    )

            return sorted(peers, key=lambda p: p.name)  # type: ignore[misc]  # lambda inferred as Callable[[Any], Any]

        except Exception as e:
            logger.error("Failed to discover peers: %s", e)
            return []

    def get_max_message_length(self) -> int:
        """Get max message length for Redis (unlimited, but use 4KB for safety).

        Returns:
            4096 characters
        """
        return 4096

    def get_ai_session_poll_interval(self) -> float:
        """Get polling interval for AI sessions.

        Returns:
            0.5 seconds (fast polling for real-time AI communication)
        """
        return 0.5

    async def _poll_redis_messages(self) -> None:
        """Background task: Poll messages:{computer_name} stream for incoming messages."""

        message_stream = f"messages:{self.computer_name}"

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
                logger.debug(
                    "About to XREAD from %s with last_id=%s, block=1000ms",
                    message_stream,
                    last_id,
                )

                messages: object = await self.redis.xread(
                    {message_stream.encode("utf-8"): last_id},
                    block=1000,  # Block for 1 second
                    count=5,
                )

                logger.debug(
                    "XREAD returned %d stream(s) with messages",
                    len(messages) if messages else 0,  # type: ignore[arg-type]  # messages is Any from Redis
                )

                if not messages:
                    logger.debug("No messages received, continuing poll loop")
                    continue

                # Process commands
                for stream_name, stream_messages in messages:  # type: ignore[misc, attr-defined]  # stream_name/stream_messages are Any from Redis, messages is object
                    # stream_name and stream_messages come from Redis xread() - types are Any
                    stream_name_str: str = stream_name.decode("utf-8") if isinstance(stream_name, bytes) else str(stream_name)  # type: ignore[misc]  # stream_name is Any
                    logger.debug(
                        "Stream %s has %d message(s)",
                        stream_name_str,
                        len(stream_messages),  # type: ignore[misc]  # stream_messages is Any from Redis
                    )

                    for message_id, data in stream_messages:  # type: ignore[misc]  # message_id/data are Any from Redis
                        logger.debug(
                            "Processing message %s with data keys: %s",
                            message_id.decode("utf-8") if isinstance(message_id, bytes) else message_id,  # type: ignore[misc]  # message_id is Any
                            [k.decode("utf-8") if isinstance(k, bytes) else k for k in data.keys()],  # type: ignore[misc]  # k is Any from data.keys()
                        )

                        # Persist last_id BEFORE processing to prevent re-processing on restart
                        # This is critical for deploy commands that call os._exit(0)
                        last_id = message_id
                        msg_id_str: str = last_id.decode("utf-8") if isinstance(last_id, bytes) else str(last_id)  # type: ignore[misc]  # last_id is Any
                        await self._set_last_processed_message_id(msg_id_str)
                        logger.debug("Saved last_id %s before processing", msg_id_str)

                        # Process message with Redis message_id for response correlation
                        await self._handle_incoming_message(msg_id_str, data)  # type: ignore[misc]  # data is Any from Redis

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Message polling error: %s", e)
                await asyncio.sleep(5)  # Back off on error

    async def _handle_incoming_message(self, message_id: str, data: dict[bytes, bytes]) -> Any:  # type: ignore[explicit-any]
        """Handle incoming message from Redis stream.

        Args:
            message_id: Redis stream entry ID (used for response correlation via output:{message_id})
            data: Message data dict from Redis stream
        """
        try:
            # Check if this is a system message
            msg_type = data.get(b"type", b"").decode("utf-8")
            if msg_type == "system":
                return await self._handle_system_message(data)

            # Extract session_id if present (for session commands)
            # Empty for ephemeral requests (list_projects, get_computer_info)
            session_id = data.get(b"session_id", b"").decode("utf-8")
            message_str = data.get(b"command", b"").decode(
                "utf-8"
            )  # Field name stays "command" for protocol compatibility

            if not message_str:
                logger.warning("Invalid message data: %s", data)
                return

            logger.info("Received message for session %s: %s", session_id[:8], message_str[:50])

            # Parse message using centralized parser FIRST
            cmd_name, args = parse_command_string(message_str)
            if not cmd_name:
                logger.warning("Empty message received for session %s", session_id[:8])
                return

            # Emit event to daemon via client
            event_type: EventType = cmd_name  # type: ignore[assignment]

            # MESSAGE and CLAUDE events use text in payload (keep message as single string)
            # Other commands use args list
            payload: dict[str, object]
            if event_type == TeleClaudeEvents.MESSAGE:
                # Join args back into single text string for MESSAGE events
                payload = {"session_id": session_id, "text": " ".join(args) if args else ""}
                logger.debug("Emitting MESSAGE event with text: %s", " ".join(args) if args else "(empty)")
            elif event_type == TeleClaudeEvents.CLAUDE:
                # Join args back into single string for /claude command (passed to handle_claude_session)
                payload = {"session_id": session_id, "args": [" ".join(args)] if args else []}
                logger.debug("Emitting CLAUDE event with args: %s", [" ".join(args)] if args else [])
            else:
                payload = {"session_id": session_id, "args": args}
                logger.debug("Emitting %s event with args: %s", event_type, args)

            # Build MessageMetadata from message data
            metadata_to_send = MessageMetadata()

            # Add session-level data to payload instead of metadata
            if b"project_dir" in data:
                payload["project_dir"] = data[b"project_dir"].decode("utf-8")
            if b"title" in data:
                payload["title"] = data[b"title"].decode("utf-8")
            if b"channel_metadata" in data:
                try:
                    metadata_obj: object = json.loads(data[b"channel_metadata"].decode("utf-8"))
                    payload["channel_metadata"] = metadata_obj
                except json.JSONDecodeError:
                    logger.warning("Invalid channel_metadata JSON in message")

            logger.info(">>> About to call handle_event for event_type: %s", event_type)
            result = await self.client.emit(
                event=event_type,
                payload=payload,
                metadata=metadata_to_send,
            )
            logger.info(
                ">>> handle_event completed for event_type: %s, result type: %s", event_type, type(result).__name__
            )

            # Start output stream listener for new AI-to-AI sessions
            if event_type == "new_session" and isinstance(result, dict) and result.get("status") == "success":  # type: ignore[misc]  # result is Any | bool from emit()
                result_data = result.get("data")
                if isinstance(result_data, dict):
                    new_session_id = result_data.get("session_id")
                    if new_session_id:
                        self._start_output_stream_listener(str(new_session_id))
                        logger.debug("Started output stream listener for session: %s", new_session_id)

            # Result is always envelope: {"status": "success/error", "data": ..., "error": ...}
            response_json = json.dumps(result)
            logger.info(
                ">>> About to send_response for message_id: %s, response length: %d", message_id[:8], len(response_json)
            )
            await self.send_response(message_id, response_json)
            logger.info(">>> send_response completed for message_id: %s", message_id[:8])

        except Exception as e:
            logger.error("Failed to handle incoming message: %s", e)

    async def _handle_system_message(self, data: dict[bytes, bytes]) -> None:
        """Handle incoming system message from Redis stream.

        System messages are daemon-level commands, not session-specific.

        Args:
            data: System message data dict from Redis stream
        """
        command = data.get(b"command", b"").decode("utf-8")
        from_computer = data.get(b"from_computer", b"").decode("utf-8")
        args_json = data.get(b"args", b"{}").decode("utf-8")

        if not command:
            logger.warning("Invalid system command data: %s", data)
            return

        # Parse args
        args_obj: object
        try:
            args_obj = json.loads(args_json)
        except json.JSONDecodeError:
            args_obj = {}

        logger.info("Received system command '%s' from %s", command, from_computer)

        # Emit SYSTEM_COMMAND event to daemon
        payload_dict: dict[str, object] = {
            "command": command,
            "args": args_obj,
            "from_computer": from_computer,
        }
        await self.client.emit(
            event=TeleClaudeEvents.SYSTEM_COMMAND,
            payload=payload_dict,
            metadata=MessageMetadata(),
        )

    async def _heartbeat_loop(self) -> None:
        """Background task: Send heartbeat every N seconds."""

        logger.info("Heartbeat loop started for computer: %s", self.computer_name)
        while self._running:
            try:
                await self._send_heartbeat()
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat failed: %s", e)
                await asyncio.sleep(self.heartbeat_interval)

    async def _send_heartbeat(self) -> None:
        """Send minimal Redis key with TTL as heartbeat (presence ping only)."""
        logger.debug("_send_heartbeat called for %s", self.computer_name)

        key = f"computer:{self.computer_name}:heartbeat"

        # Minimal payload - just alive ping
        payload: dict[str, str] = {
            "computer_name": self.computer_name,
            "last_seen": datetime.now().isoformat(),
        }

        # Set key with auto-expiry
        await self.redis.setex(
            key,
            self.heartbeat_ttl,
            json.dumps(payload),
        )

        logger.debug("Sent heartbeat: %s", key)

    # === AI-to-AI Session Output Stream Listeners ===

    def _start_output_stream_listener(self, session_id: str) -> None:
        """Start background task to poll output stream for incoming messages from initiator.

        Args:
            session_id: Session ID to listen for
        """
        if session_id in self._output_stream_listeners:
            logger.warning("Output stream listener already running for session %s", session_id[:8])
            return

        task = asyncio.create_task(self._poll_output_stream_for_messages(session_id))
        self._output_stream_listeners[session_id] = task
        logger.info("Started output stream listener for AI-to-AI session %s", session_id[:8])

    async def _poll_output_stream_for_messages(self, session_id: str) -> None:
        """Poll output stream for incoming messages from session initiator.

        This enables bidirectional communication in AI-to-AI sessions where
        the output stream is shared between initiator and remote.

        Args:
            session_id: Session ID to poll
        """

        output_stream = f"output:{session_id}"
        last_id = b"$"  # Start from current position
        logger.info("Starting output stream message polling for session %s", session_id[:8])

        try:
            while self._running:
                # Check if session still exists
                session = await db.get_session(session_id)
                if not session or session.closed:
                    logger.info("Session %s closed, stopping output stream listener", session_id[:8])
                    break

                # Read from output stream
                messages = await self.redis.xread({output_stream.encode("utf-8"): last_id}, block=1000, count=5)

                if not messages:
                    continue

                # Process incoming messages from initiator
                for _stream_name, stream_messages in messages:  # type: ignore[misc]  # messages is Any from Redis
                    for message_id, data in stream_messages:  # type: ignore[misc]  # stream_messages is Any from Redis
                        last_id = message_id

                        # Check if this is a message FROM the initiator (not our own output)
                        chunk_bytes: bytes = data.get(b"chunk", b"")  # type: ignore[misc]  # data is Any from Redis
                        chunk = chunk_bytes.decode("utf-8")

                        if not chunk:
                            continue

                        # Skip exit markers and system messages
                        if "__EXIT__" in chunk or chunk.startswith("[") or "⏳" in chunk:
                            continue

                        # This is a message from the initiator - trigger MESSAGE event
                        logger.info("Received message from initiator for session %s: %s", session_id[:8], chunk[:50])
                        message_payload: dict[str, object] = {"session_id": session_id, "text": chunk.strip()}
                        await self.client.emit(
                            event=TeleClaudeEvents.MESSAGE,
                            payload=message_payload,
                            metadata=MessageMetadata(),
                        )

        except asyncio.CancelledError:
            logger.debug("Output stream listener cancelled for session %s", session_id[:8])
        except Exception as e:
            logger.error("Output stream listener error for session %s: %s", session_id[:8], e)
        finally:
            # Cleanup
            if session_id in self._output_stream_listeners:
                del self._output_stream_listeners[session_id]
            logger.info("Stopped output stream listener for session %s", session_id[:8])

    # === Session Observation (Interest Window) ===

    async def signal_observation(
        self,
        target_computer: str,
        session_id: str,
        duration_seconds: int,
    ) -> None:
        """Signal interest in observing a session on target computer.

        Creates a Redis key with TTL that tells the target computer
        to broadcast session output to Redis stream during the observation window.

        Args:
            target_computer: Computer hosting the session
            session_id: Session to observe
            duration_seconds: How long to observe (TTL for Redis key)
        """

        key = f"observation:{target_computer}:{session_id}"
        observation_data: dict[str, object] = {
            "observer": self.computer_name,
            "started_at": time.time(),
        }
        data = json.dumps(observation_data)

        # Set key with TTL - auto-expires after duration
        await self.redis.setex(key, duration_seconds, data)
        logger.info(
            "Signaled observation: %s observing %s on %s for %ds",
            self.computer_name,
            session_id[:8],
            target_computer,
            duration_seconds,
        )

    async def is_session_observed(self, session_id: str) -> bool:
        """Check if any observer is watching this session.

        Args:
            session_id: Session ID to check

        Returns:
            True if someone is observing this session
        """

        key = f"observation:{self.computer_name}:{session_id}"
        exists = await self.redis.exists(key)
        return bool(exists)

    # === Request/Response pattern for ephemeral queries (list_projects, etc.) ===

    async def send_request(
        self, computer_name: str, command: str, metadata: MessageMetadata, session_id: Optional[str] = None
    ) -> str:
        """Send request to remote computer's message stream.

        Used for ephemeral queries (list_projects, etc.) and session commands.

        Args:
            computer_name: Target computer name
            command: Command to send
            session_id: Optional TeleClaude session ID (for session commands)
            metadata: Optional metadata (title, project_dir for session creation)

        Returns:
            Redis stream entry ID (used for response correlation)
        """

        message_stream = f"messages:{computer_name}"

        # Build message data
        data: dict[bytes, bytes] = {
            b"command": command.encode("utf-8"),
            b"timestamp": str(time.time()).encode("utf-8"),
            b"initiator": self.computer_name.encode("utf-8"),
        }

        # Add session_id if provided (for session commands)
        if session_id:
            data[b"session_id"] = session_id.encode("utf-8")

        # Add optional session creation metadata
        if metadata.title:
            data[b"title"] = metadata.title.encode("utf-8")
        if metadata.project_dir:
            data[b"project_dir"] = metadata.project_dir.encode("utf-8")
        if metadata.channel_metadata:
            data[b"channel_metadata"] = json.dumps(metadata.channel_metadata).encode("utf-8")

        # Send to Redis stream - XADD returns unique message_id
        # This message_id is used for response correlation (receiver sends response to output:{message_id})
        message_id_bytes: bytes = await self.redis.xadd(message_stream, data, maxlen=self.message_stream_maxlen)  # type: ignore[arg-type]  # Redis xadd signature expects wider dict type
        message_id = message_id_bytes.decode("utf-8")

        logger.debug("XADD returned message_id=%s", message_id)
        logger.info("Sent request to %s: message_id=%s, command=%s", computer_name, message_id[:15], command[:50])
        return message_id

    async def send_response(self, message_id: str, data: str) -> str:
        """Send response for an ephemeral request directly to Redis stream.

        Used by command handlers (list_projects, etc.) to respond without DB session.

        Args:
            message_id: Redis stream entry ID from the original request
            data: Response data (typically JSON)

        Returns:
            Redis stream entry ID of the response
        """

        output_stream = f"output:{message_id}"
        logger.debug(
            "send_response() sending to stream=%s for message_id=%s (data_length=%d)",
            output_stream,
            message_id,
            len(data),
        )

        response_id_bytes: bytes = await self.redis.xadd(
            output_stream,
            {
                b"chunk": data.encode("utf-8"),
                b"timestamp": str(time.time()).encode("utf-8"),
                b"message_id": message_id.encode("utf-8"),
            },
            maxlen=self.output_stream_maxlen,
        )

        logger.debug(
            "send_response() completed for message_id=%s, stream=%s, response_id=%s",
            message_id,
            output_stream,
            response_id_bytes,
        )
        return response_id_bytes.decode("utf-8")

    async def read_response(self, message_id: str, timeout: float = 3.0) -> str:
        """Read response from ephemeral request (non-streaming).

        Used for one-shot request/response like list_projects, get_computer_info.
        Reads once from the Redis stream instead of continuous polling.

        Args:
            message_id: Redis stream entry ID from the original request
            timeout: Maximum time to wait for response (seconds, default 3.0)

        Returns:
            Response data as string

        Raises:
            TimeoutError: If no response received within timeout
        """

        output_stream = f"output:{message_id}"
        start_time = time.time()
        logger.debug("read_response() waiting for response on stream=%s, timeout=%s", output_stream, timeout)

        try:
            poll_count = 0
            while True:
                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    logger.warning(
                        "read_response() timed out after %d polls (%.1fs) for message %s",
                        poll_count,
                        elapsed,
                        message_id[:8],
                    )
                    raise TimeoutError(f"No response received for message {message_id[:8]} within {timeout}s")

                # Read from stream (blocking with 100ms timeout)
                poll_count += 1
                logger.debug(
                    "read_response() poll #%d for message %s (elapsed=%.1fs)", poll_count, message_id[:8], elapsed
                )
                messages = await self.redis.xread({output_stream.encode("utf-8"): b"0"}, block=100, count=1)

                if messages:
                    # Got response - extract and return
                    logger.debug(
                        "read_response() received response for message %s after %d polls", message_id[:8], poll_count
                    )
                    for _stream_name, stream_messages in messages:  # type: ignore[misc]  # messages is Any from Redis
                        for _entry_id, data in stream_messages:  # type: ignore[misc]  # stream_messages is Any from Redis
                            chunk_bytes: bytes = data.get(b"chunk", b"")  # type: ignore[misc]  # data is Any from Redis
                            chunk: str = chunk_bytes.decode("utf-8")
                            if chunk:
                                logger.debug(
                                    "read_response() returning response for message %s (length=%d)",
                                    message_id[:8],
                                    len(chunk),
                                )
                                return chunk

                # No message yet, continue polling
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.debug("read_response cancelled for message %s", message_id[:8])
            raise

    async def send_system_command(
        self, computer_name: str, command: str, args: Optional[dict[str, object]] = None
    ) -> str:
        """Send system command to remote computer (not session-specific).

        System commands are handled by the daemon itself, not routed to tmux.
        Examples: deploy, restart, health_check

        Args:
            computer_name: Target computer name
            command: System command (e.g., "deploy")
            args: Optional command arguments

        Returns:
            Redis stream entry ID
        """

        message_stream = f"messages:{computer_name}"

        # Build system message data
        data = {
            b"type": b"system",
            b"command": command.encode("utf-8"),
            b"timestamp": str(time.time()).encode("utf-8"),
            b"from_computer": self.computer_name.encode("utf-8"),
        }

        # Add args as JSON if provided
        if args:
            data[b"args"] = json.dumps(args).encode("utf-8")

        # Send to Redis stream
        logger.debug("Sending system command to %s: %s", computer_name, command)
        message_id_bytes: bytes = await self.redis.xadd(message_stream, data, maxlen=self.message_stream_maxlen)  # type: ignore[arg-type]  # Redis xadd signature expects wider dict type

        logger.info("Sent system command to %s: %s", computer_name, command)
        return message_id_bytes.decode("utf-8")

    async def get_system_command_status(self, computer_name: str, command: str) -> dict[str, object]:
        """Get status of system command execution.

        Args:
            computer_name: Target computer name
            command: System command name

        Returns:
            Status dict with keys: status, timestamp, error (if failed)
        """

        status_key = f"system_status:{computer_name}:{command}"
        data = await self.redis.get(status_key)

        if not data:
            return {"status": "unknown"}

        result_obj: object = json.loads(data.decode("utf-8"))  # type: ignore[misc]  # json.loads returns Any
        if not isinstance(result_obj, dict):
            return {"status": "error", "error": "Invalid result format"}
        result: dict[str, object] = result_obj
        return result

    async def poll_output_stream(self, session_id: str, timeout: float = 300.0) -> AsyncIterator[str]:  # type: ignore[override, misc]  # mypy false positive with async generators
        """Poll output stream and yield chunks as they arrive.

        Used by MCP server to stream output from remote sessions.

        Args:
            session_id: Session ID
            timeout: Max seconds to wait for output

        Yields:
            Output chunks as they arrive
        """

        output_stream = f"output:{session_id}"
        last_id = b"$"  # Start from current position (only read new chunks)
        start_time = time.time()
        last_yield_time = time.time()
        idle_count = 0
        max_idle_polls = 120  # 120 * 0.5s = 60s max idle
        heartbeat_interval = 60  # Send heartbeat every 60s if no output

        logger.info("Starting output stream poll for session %s", session_id[:8])

        try:
            while True:
                # Check overall timeout
                if time.time() - start_time > timeout:
                    yield "\n[Timeout: Session exceeded time limit]"
                    return

                # Read from stream (blocking with 500ms timeout)
                try:
                    messages = await self.redis.xread({output_stream.encode("utf-8"): last_id}, block=500, count=10)

                    if not messages:
                        # No messages - increment idle counter
                        idle_count += 1

                        # Send heartbeat if no output for a while
                        if time.time() - last_yield_time > heartbeat_interval:
                            yield "[⏳ Waiting for response...]\n"
                            last_yield_time = time.time()

                        # Timeout if idle too long
                        if idle_count >= max_idle_polls:
                            yield "\n[Timeout: No response for 60 seconds]"
                            return

                        continue

                    # Got messages - reset idle counter
                    idle_count = 0

                    # Process messages
                    for _stream_name, stream_messages in messages:  # type: ignore[misc]  # messages is Any from Redis
                        for message_id, data in stream_messages:  # type: ignore[misc]  # stream_messages is Any from Redis
                            chunk = data.get(b"chunk", b"").decode("utf-8")  # type: ignore[misc]  # data is Any from Redis

                            if not chunk:  # type: ignore[misc]  # chunk type inferred from decode
                                continue

                            # Check for completion marker
                            if "[Output Complete]" in chunk:  # type: ignore[misc]  # chunk type inferred from decode
                                logger.info("Received completion marker for session %s", session_id[:8])
                                return

                            # Yield chunk content
                            content = self._extract_chunk_content(chunk)  # type: ignore[misc]  # chunk type inferred from decode
                            if content:
                                yield content
                                last_yield_time = time.time()

                            # Update last ID
                            last_id = message_id

                except Exception as e:
                    logger.error("Error polling output stream: %s", e)
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("Output stream polling cancelled for session %s", session_id[:8])
            raise

    def _extract_chunk_content(self, chunk_text: str) -> str:
        """Extract actual output from chunk message.

        Strips markdown code fences and chunk markers.

        Args:
            chunk_text: Raw chunk text from Redis

        Returns:
            Extracted content without formatting
        """
        if not chunk_text:
            return ""

        # Remove markdown code fences
        content = chunk_text.replace("```sh", "").replace("```", "")
        # Remove chunk markers
        content = re.sub(r"\[Chunk \d+/\d+\]", "", content)
        return content.strip()
