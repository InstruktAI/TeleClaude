"""Redis adapter for AI-to-AI communication via Redis Streams.

This adapter enables reliable cross-computer messaging for TeleClaude using
Redis Streams as the transport layer. It bypasses Telegram's bot-to-bot
messaging restriction.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING, AsyncIterator, Optional

from redis.asyncio import Redis

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import EventType, TeleClaudeEvents, parse_command_string
from teleclaude.core.protocols import RemoteExecutionProtocol
from teleclaude.core.system_stats import get_all_stats

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
        self.redis: Optional[Redis] = None
        self._message_poll_task: Optional[asyncio.Task[None]] = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
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

        logger.info("RedisAdapter initialized for computer: %s", self.computer_name)

    async def start(self) -> None:
        """Initialize Redis connection and start background tasks."""
        if self._running:
            logger.warning("RedisAdapter already running")
            return

        # Create Redis client
        self.redis = Redis.from_url(
            self.redis_url,
            password=self.redis_password,
            max_connections=self.max_connections,
            socket_timeout=self.socket_timeout,
            decode_responses=False,  # We handle decoding manually
        )

        # Test connection
        try:
            await self.redis.ping()
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

    async def send_message(self, session_id: str, text: str, metadata: Optional[dict[str, object]] = None) -> str:
        """Send message chunk to Redis output stream.

        Args:
            session_id: Session ID
            text: Message text (output chunk)
            metadata: Optional metadata (ignored for Redis)

        Returns:
            Redis stream entry ID as message_id
        """
        if not self.redis:
            raise RuntimeError("Redis not initialized")

        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Get output stream name from session metadata
        redis_metadata: dict[str, object] = session.adapter_metadata or {}
        if isinstance(redis_metadata, str):
            redis_metadata = json.loads(redis_metadata)

        redis_meta: dict[str, object] = redis_metadata.get("redis", {})  # type: ignore[assignment]
        # Try redis-specific channel_id first, then fall back to output_stream
        output_stream = redis_meta.get("channel_id") or redis_meta.get("output_stream")

        if not output_stream:
            # Create stream name if not exists
            output_stream = f"output:{session_id}"
            redis_meta["channel_id"] = output_stream
            redis_meta["output_stream"] = output_stream
            redis_metadata["redis"] = redis_meta

            # Update session
            await db.update_session(session_id, adapter_metadata=redis_metadata)

        # Send to Redis stream
        message_id_bytes: bytes = await self.redis.xadd(
            output_stream,
            {
                b"chunk": text.encode("utf-8"),
                b"timestamp": str(time.time()).encode("utf-8"),
                b"session_id": session_id.encode("utf-8"),
            },
            maxlen=self.output_stream_maxlen,
        )

        logger.debug("Sent to Redis stream %s: %s", output_stream, message_id_bytes)
        return message_id_bytes.decode("utf-8")

    async def edit_message(
        self, session_id: str, message_id: str, text: str, metadata: Optional[dict[str, object]] = None
    ) -> bool:
        """Redis streams don't support editing - send new message instead.

        Args:
            session_id: Session ID
            message_id: Message ID (ignored)
            text: New text
            metadata: Optional metadata

        Returns:
            True (always succeeds by sending new message)
        """
        await self.send_message(session_id, text, metadata)
        return True

    async def delete_message(self, session_id: str, message_id: str) -> bool:
        """Delete message from Redis stream.

        Args:
            session_id: Session ID
            message_id: Redis stream entry ID

        Returns:
            True if successful
        """
        if not self.redis:
            return False

        session = await db.get_session(session_id)
        if not session:
            return False

        redis_metadata: dict[str, object] = session.adapter_metadata or {}
        if isinstance(redis_metadata, str):
            redis_metadata = json.loads(redis_metadata)

        redis_meta_2: dict[str, object] = redis_metadata.get("redis", {})  # type: ignore[assignment]
        output_stream = redis_meta_2.get("output_stream")
        if not output_stream:
            return False

        try:
            await self.redis.xdel(output_stream, message_id)
            return True
        except Exception as e:
            logger.error("Failed to delete message %s: %s", message_id, e)
            return False

    async def send_file(
        self,
        session_id: str,
        file_path: str,
        caption: Optional[str] = None,
        metadata: Optional[dict[str, object]] = None,
    ) -> str:
        """Send file - not supported by Redis adapter.

        Args:
            session_id: Session ID
            file_path: Path to file
            caption: Optional caption
            metadata: Optional metadata

        Returns:
            Empty string (not supported)
        """
        logger.warning("send_file not supported by RedisAdapter")
        return ""

    async def send_general_message(self, text: str, metadata: Optional[dict[str, object]] = None) -> str:
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

    async def create_channel(self, session_id: str, title: str, metadata: Optional[dict[str, object]] = None) -> str:
        """Create Redis streams for session.

        For AI-to-AI sessions (with target_computer): Creates command + output streams.
        For local sessions (no target_computer): Creates only output stream.

        Args:
            session_id: Session ID
            title: Channel title
            metadata: Optional metadata (may contain target_computer for AI-to-AI sessions)

        Returns:
            Output stream name as channel_id
        """
        if not self.redis:
            raise RuntimeError("Redis not initialized")

        target = metadata.get("target_computer") if metadata else None
        output_stream = f"output:{session_id}"

        # Store stream names in session metadata
        session = await db.get_session(session_id)
        if session:
            redis_metadata = session.adapter_metadata or {}
            if isinstance(redis_metadata, str):
                redis_metadata = json.loads(redis_metadata)

            redis_meta: dict[str, str] = {
                "output_stream": output_stream,
            }

            # AI-to-AI session: include message stream
            if target:
                message_stream = f"messages:{target}"
                redis_meta["message_stream"] = message_stream
                logger.info(
                    "Created Redis streams for AI-to-AI session %s: message=%s, output=%s",
                    session_id[:8],
                    message_stream,
                    output_stream,
                )
            else:
                # Local session: only output stream (for potential future use)
                logger.debug(
                    "Created Redis output stream for local session %s: %s (no message stream)",
                    session_id[:8],
                    output_stream,
                )

            redis_metadata["redis"] = redis_meta
            await db.update_session(session_id, adapter_metadata=redis_metadata)

        return output_stream

    async def update_channel_title(self, session_id: str, title: str) -> bool:
        """Update channel title (no-op for Redis).

        Args:
            session_id: Session identifier
            title: New title

        Returns:
            True
        """
        return True

    async def close_channel(self, session_id: str) -> bool:
        """No-op: Redis has no persistent channels to close.

        Args:
            session_id: Session identifier

        Returns:
            True (always succeeds)
        """
        return True

    async def reopen_channel(self, session_id: str) -> bool:
        """No-op: Redis has no persistent channels to reopen.

        Args:
            session_id: Session identifier

        Returns:
            True (always succeeds)
        """
        return True

    async def delete_channel(self, session_id: str) -> bool:
        """Delete Redis stream.

        Args:
            session_id: Session identifier

        Returns:
            True if successful
        """
        if not self.redis:
            return False

        try:
            await self.redis.delete(session_id)
            return True
        except Exception as e:
            logger.error("Failed to delete stream %s: %s", session_id, e)
            return False

    async def discover_peers(self) -> list[dict[str, object]]:
        """Discover peers via Redis heartbeat keys.

        Returns:
            List of peer dicts with name, status, last_seen, etc.
        """
        if not self.redis:
            return []

        try:
            # Find all heartbeat keys
            keys = await self.redis.keys(b"computer:*:heartbeat")

            peers = []
            for key in keys:
                # Get data
                data = await self.redis.get(key)
                if data:
                    info = json.loads(data.decode("utf-8"))

                    last_seen_str = info.get("last_seen", "")
                    try:
                        last_seen_dt = datetime.fromisoformat(last_seen_str)
                    except (ValueError, TypeError):
                        last_seen_dt = datetime.now()

                    # Calculate time ago
                    age_seconds = (datetime.now() - last_seen_dt).total_seconds()
                    if age_seconds < 60:
                        last_seen_ago = f"{int(age_seconds)}s ago"
                    elif age_seconds < 3600:
                        last_seen_ago = f"{int(age_seconds / 60)}m ago"
                    else:
                        last_seen_ago = f"{int(age_seconds / 3600)}h ago"

                    peers.append(
                        {
                            "name": info["computer_name"],
                            "role": info.get("role", "general"),
                            "host": info.get("host"),
                            "system_stats": info.get("system_stats", {}),
                            "sessions": info.get("sessions", []),
                            "status": "online",
                            "last_seen": last_seen_dt,
                            "last_seen_ago": last_seen_ago,
                            "adapter_type": "redis",
                        }
                    )

            return sorted(peers, key=lambda p: p["name"])

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
        if not self.redis:
            return

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

                messages = await self.redis.xread(
                    {message_stream.encode("utf-8"): last_id},
                    block=1000,  # Block for 1 second
                    count=5,
                )

                logger.debug(
                    "XREAD returned %d stream(s) with messages",
                    len(messages) if messages else 0,
                )

                if not messages:
                    logger.debug("No messages received, continuing poll loop")
                    continue

                # Process commands
                for stream_name, stream_messages in messages:
                    logger.debug(
                        "Stream %s has %d message(s)",
                        stream_name.decode("utf-8") if isinstance(stream_name, bytes) else stream_name,
                        len(stream_messages),
                    )

                    for message_id, data in stream_messages:
                        logger.debug(
                            "Processing message %s with data keys: %s",
                            message_id.decode("utf-8") if isinstance(message_id, bytes) else message_id,
                            [k.decode("utf-8") if isinstance(k, bytes) else k for k in data.keys()],
                        )

                        # Persist last_id BEFORE processing to prevent re-processing on restart
                        # This is critical for deploy commands that call os._exit(0)
                        last_id = message_id
                        last_id_str = last_id.decode("utf-8") if isinstance(last_id, bytes) else last_id
                        await self._set_last_processed_message_id(last_id_str)
                        logger.debug("Saved last_id %s before processing", last_id_str)

                        # Process message (may call os._exit(0) for deploy)
                        await self._handle_incoming_message(data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Message polling error: %s", e)
                await asyncio.sleep(5)  # Back off on error

    async def _handle_incoming_message(self, data: dict[bytes, bytes]) -> None:
        """Handle incoming message from Redis stream.

        Args:
            data: Message data dict from Redis stream
        """
        try:
            # Check if this is a system message
            msg_type = data.get(b"type", b"").decode("utf-8")
            if msg_type == "system":
                await self._handle_system_message(data)
                return

            # Regular user message (session-specific)
            session_id = data.get(b"session_id", b"").decode("utf-8")
            message_str = data.get(b"command", b"").decode(
                "utf-8"
            )  # Field name stays "command" for protocol compatibility

            if not session_id or not message_str:
                logger.warning("Invalid message data: %s", data)
                return

            logger.info("Received message for session %s: %s", session_id[:8], message_str[:50])

            # Get or create session
            session = await db.get_session(session_id)
            if not session:
                # Only create session if metadata indicates real session initialization
                metadata = json.loads(data.get(b"metadata", b"{}").decode("utf-8"))
                if metadata.get("title") and metadata.get("project_dir"):
                    # Real AI-to-AI session initialization (has title + project_dir)
                    await self._create_session_from_redis(session_id, data)
                    logger.info("Created session from Redis: %s (title: %s)", session_id[:8], metadata.get("title"))
                else:
                    # Ephemeral query command (list_projects, etc.) - skip session creation
                    logger.debug(
                        "Skipping session creation for ephemeral command: %s (no title/project_dir)", session_id[:8]
                    )

            # Parse message using centralized parser
            cmd_name, args = parse_command_string(message_str)
            if not cmd_name:
                logger.warning("Empty message received for session %s", session_id[:8])
                return

            # Emit event to daemon via client
            event_type: EventType = cmd_name  # type: ignore[assignment]

            # MESSAGE events use "text" in payload, commands use "args"
            payload: dict[str, object]
            if event_type == TeleClaudeEvents.MESSAGE:
                # Join args back into single text string for MESSAGE events
                payload = {"session_id": session_id, "text": " ".join(args) if args else ""}
                logger.debug("Emitting MESSAGE event with text: %s", " ".join(args) if args else "(empty)")
            else:
                payload = {"session_id": session_id, "args": args}
                logger.debug("Emitting %s event with args: %s", event_type, args)

            logger.debug("About to call handle_event for event_type: %s", event_type)
            await self.client.handle_event(
                event=event_type,
                payload=payload,
                metadata={"adapter_type": "redis"},
            )
            logger.debug("handle_event completed for event_type: %s", event_type)

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
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError:
            args = {}

        logger.info("Received system command '%s' from %s", command, from_computer)

        # Emit SYSTEM_COMMAND event to daemon
        await self.client.handle_event(
            event=TeleClaudeEvents.SYSTEM_COMMAND,
            payload={
                "command": command,
                "args": args,
                "from_computer": from_computer,
            },
            metadata={"adapter_type": "redis"},
        )

    async def _create_session_from_redis(self, session_id: str, data: dict[bytes, bytes]) -> None:
        """Create session from incoming Redis command data.

        Args:
            session_id: Session ID
            data: Command data from Redis
        """
        # Extract metadata from command
        title = data.get(b"title", b"Unknown Session").decode("utf-8")
        initiator = data.get(b"initiator", b"unknown").decode("utf-8")

        # Create tmux session name
        tmux_session_name = f"{self.computer_name}-ai-{session_id[:8]}"

        # Create session with redis as origin adapter
        await db.create_session(
            session_id=session_id,
            computer_name=self.computer_name,
            tmux_session_name=tmux_session_name,
            origin_adapter="redis",
            title=title,
            adapter_metadata={
                "target_computer": initiator,  # AI-to-AI session from remote computer
            },
            description=f"AI-to-AI session from {initiator}",
        )

        # Create channels in ALL adapters (Telegram, Redis, etc.)
        # AdapterClient.create_channel() stores all adapter channel_ids in metadata
        await self.client.create_channel(
            session_id=session_id,
            title=title,
            origin_adapter="redis",
        )

        logger.info("Created session %s from Redis command with channels in all adapters", session_id[:8])

    async def _heartbeat_loop(self) -> None:
        """Background task: Send heartbeat every N seconds."""
        if not self.redis:
            return

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
        """Send Redis key with TTL as heartbeat."""
        if not self.redis:
            return

        key = f"computer:{self.computer_name}:heartbeat"

        # Add active sessions (limited to 50 max)
        all_sessions = await db.get_sessions_by_title_pattern("")
        active_sessions = [s.title for s in all_sessions if not s.closed][:50]  # Limit to 50 sessions

        # Build enhanced payload with graceful degradation
        payload: dict[str, object] = {
            "computer_name": self.computer_name,
            "last_seen": datetime.now().isoformat(),
            "role": config.computer.role,
            "host": config.computer.host,
            "system_stats": get_all_stats(),
            "sessions": active_sessions,
        }

        # Set key with auto-expiry
        await self.redis.setex(
            key,
            self.heartbeat_ttl,
            json.dumps(payload),
        )

        logger.debug("Sent heartbeat: %s", key)

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
        if not self.redis:
            raise RuntimeError("Redis not initialized")

        key = f"observation:{target_computer}:{session_id}"
        data = json.dumps(
            {
                "observer": self.computer_name,
                "started_at": time.time(),
            }
        )

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
        if not self.redis:
            return False

        key = f"observation:{self.computer_name}:{session_id}"
        exists = await self.redis.exists(key)
        return bool(exists)

    # === Request/Response pattern for ephemeral queries (list_projects, etc.) ===

    async def send_request(
        self, computer_name: str, request_id: str, command: str, metadata: Optional[dict[str, object]] = None
    ) -> str:
        """Send request to remote computer's message stream.

        Used for ephemeral queries (list_projects, etc.) and session commands.

        Args:
            computer_name: Target computer name
            request_id: Correlation ID for request/response matching
            command: Command to send
            metadata: Optional metadata (title, project_dir for session creation)

        Returns:
            Redis stream entry ID
        """
        if not self.redis:
            raise RuntimeError("Redis not initialized")

        message_stream = f"messages:{computer_name}"
        metadata = metadata or {}

        # Build message data (session_id field kept for protocol compatibility)
        data = {
            b"session_id": request_id.encode("utf-8"),
            b"command": command.encode("utf-8"),
            b"timestamp": str(time.time()).encode("utf-8"),
            b"initiator": self.computer_name.encode("utf-8"),
        }

        # Add optional metadata
        if "title" in metadata:
            title_str = str(metadata["title"])
            data[b"title"] = title_str.encode("utf-8")
        if "project_dir" in metadata:
            project_dir_str = str(metadata["project_dir"])
            data[b"project_dir"] = project_dir_str.encode("utf-8")

        # Send to Redis stream
        logger.debug(
            "About to XADD to stream=%s, data keys=%s",
            message_stream,
            [k.decode("utf-8") for k in data],
        )

        message_id_bytes: bytes = await self.redis.xadd(message_stream, data, maxlen=self.message_stream_maxlen)

        logger.debug("XADD returned message_id=%s", message_id_bytes.decode("utf-8"))
        logger.info("Sent request to %s: request_id=%s, command=%s", computer_name, request_id[:8], command[:50])
        return message_id_bytes.decode("utf-8")

    async def send_response(self, request_id: str, data: str) -> str:
        """Send response for an ephemeral request directly to Redis stream.

        Used by command handlers (list_projects, etc.) to respond without DB session.

        Args:
            request_id: Correlation ID from the request
            data: Response data (typically JSON)

        Returns:
            Redis stream entry ID
        """
        if not self.redis:
            raise RuntimeError("Redis not initialized")

        output_stream = f"output:{request_id}"

        message_id_bytes: bytes = await self.redis.xadd(
            output_stream,
            {
                b"chunk": data.encode("utf-8"),
                b"timestamp": str(time.time()).encode("utf-8"),
                b"request_id": request_id.encode("utf-8"),
            },
            maxlen=self.output_stream_maxlen,
        )

        logger.debug("Sent response to stream %s: %s", output_stream, message_id_bytes)
        return message_id_bytes.decode("utf-8")

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
        if not self.redis:
            raise RuntimeError("Redis not initialized")

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
        message_id_bytes: bytes = await self.redis.xadd(message_stream, data, maxlen=self.message_stream_maxlen)

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
        if not self.redis:
            raise RuntimeError("Redis not initialized")

        status_key = f"system_status:{computer_name}:{command}"
        data = await self.redis.get(status_key)

        if not data:
            return {"status": "unknown"}

        result: dict[str, object] = json.loads(data.decode("utf-8"))
        return result

    async def poll_output_stream(self, session_id: str, timeout: float = 300.0) -> AsyncIterator[str]:
        """Poll output stream and yield chunks as they arrive.

        Used by MCP server to stream output from remote sessions.

        Args:
            session_id: Session ID
            timeout: Max seconds to wait for output

        Yields:
            Output chunks as they arrive
        """
        if not self.redis:
            raise RuntimeError("Redis not initialized")

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
                    for _stream_name, stream_messages in messages:
                        for message_id, data in stream_messages:
                            chunk = data.get(b"chunk", b"").decode("utf-8")

                            if not chunk:
                                continue

                            # Check for completion marker
                            if "[Output Complete]" in chunk:
                                logger.info("Received completion marker for session %s", session_id[:8])
                                return

                            # Yield chunk content
                            content = self._extract_chunk_content(chunk)
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
