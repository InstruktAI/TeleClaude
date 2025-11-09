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
from teleclaude.core.protocols import RemoteExecutionProtocol

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = logging.getLogger(__name__)


class RedisAdapter(BaseAdapter, RemoteExecutionProtocol):
    """Adapter for AI-to-AI communication via Redis Streams.

    Uses Redis Streams for reliable, ordered message delivery between computers.

    Implements RemoteExecutionProtocol for cross-computer orchestration.

    Architecture:
    - Each computer polls its command stream: commands:{computer_name}
    - Each session has an output stream: output:{session_id}
    - Computer registry uses Redis keys with TTL for heartbeats

    Message flow:
    - Comp1 → XADD commands:comp2 → Comp2 polls → executes command
    - Comp2 → XADD output:session_id → Comp1 polls → streams to MCP
    """

    has_ui = False  # Redis has no visual UI (pure transport)

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
        self._command_poll_task: Optional[asyncio.Task[None]] = None
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
        self.command_stream_maxlen = config.redis.command_stream_maxlen
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
        self._command_poll_task = asyncio.create_task(self._poll_redis_commands())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info("RedisAdapter started")

    async def stop(self) -> None:
        """Stop adapter and cleanup resources."""
        if not self._running:
            return

        self._running = False

        # Cancel background tasks
        if self._command_poll_task:
            self._command_poll_task.cancel()
            try:
                await self._command_poll_task
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
        output_stream = redis_meta.get("output_stream")

        if not output_stream:
            # Create stream name if not exists
            output_stream = f"output:{session_id}"
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

        Args:
            session_id: Session ID
            title: Channel title (format: "$initiator > $target - description")
            metadata: Optional metadata

        Returns:
            Output stream name as channel_id
        """
        if not self.redis:
            raise RuntimeError("Redis not initialized")

        # Parse target from title
        target = self._parse_target_from_title(title)
        if not target:
            raise ValueError(f"Could not parse target from title: {title}")

        # Stream names
        command_stream = f"commands:{target}"
        output_stream = f"output:{session_id}"

        # Streams are created automatically on first XADD
        logger.info(
            "Created Redis streams for session %s: command=%s, output=%s",
            session_id[:8],
            command_stream,
            output_stream,
        )

        # Store stream names in session metadata
        session = await db.get_session(session_id)
        if session:
            redis_metadata = session.adapter_metadata or {}
            if isinstance(redis_metadata, str):
                redis_metadata = json.loads(redis_metadata)

            redis_metadata["redis"] = {
                "command_stream": command_stream,
                "output_stream": output_stream,
            }

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

    async def set_channel_status(self, session_id: str, status: str) -> bool:
        """Set channel status (no-op for Redis).

        Args:
            session_id: Session identifier
            status: Status string

        Returns:
            True
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
                            "bot_username": info.get("bot_username", ""),
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

    async def _poll_redis_commands(self) -> None:
        """Background task: Poll commands:{computer_name} stream for incoming commands."""
        if not self.redis:
            return

        command_stream = f"commands:{self.computer_name}"
        # Start from 60 seconds ago to catch messages during startup window
        startup_timestamp = int((time.time() - 60) * 1000)  # 60 seconds ago in milliseconds
        last_id = f"{startup_timestamp}-0".encode("utf-8")

        logger.info("Starting Redis command polling: %s (from last 60s)", command_stream)

        while self._running:
            try:
                # Read commands from stream (blocking)
                logger.debug(
                    "About to XREAD from %s with last_id=%s, block=1000ms",
                    command_stream,
                    last_id,
                )

                messages = await self.redis.xread(
                    {command_stream.encode("utf-8"): last_id},
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
                        await self._handle_incoming_command(data)
                        last_id = message_id
                        logger.debug(
                            "Updated last_id to %s",
                            last_id.decode("utf-8") if isinstance(last_id, bytes) else last_id,
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Command polling error: %s", e)
                await asyncio.sleep(5)  # Back off on error

    async def _handle_incoming_command(self, data: dict[bytes, bytes]) -> None:
        """Handle incoming command from Redis stream.

        Args:
            data: Command data dict from Redis stream
        """
        try:
            session_id = data.get(b"session_id", b"").decode("utf-8")
            command_str = data.get(b"command", b"").decode("utf-8")

            if not session_id or not command_str:
                logger.warning("Invalid command data: %s", data)
                return

            logger.info("Received command for session %s: %s", session_id[:8], command_str[:50])

            # Get or create session
            session = await db.get_session(session_id)
            if not session:
                # Create new session for incoming AI request
                await self._create_session_from_redis(session_id, data)

            # Parse command using centralized parser
            from teleclaude.core.events import (
                EventType,
                TeleClaudeEvents,
                parse_command_string,
            )

            cmd_name, args = parse_command_string(command_str)
            if not cmd_name:
                logger.warning("Empty command received for session %s", session_id[:8])
                return

            # Emit command event to daemon via client
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
            logger.error("Failed to handle incoming command: %s", e)

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
                "is_ai_to_ai": True,  # CRITICAL: Mark as AI session for chunked output
                "redis": {
                    "command_stream": f"commands:{self.computer_name}",
                    "output_stream": f"output:{session_id}",
                },
                "telegram": {
                    "topic_name": title,
                },
            },
            description=f"AI-to-AI session from {initiator}",
        )

        logger.info("Created session %s from Redis command", session_id[:8])

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

        # Set key with auto-expiry
        await self.redis.setex(
            key,
            self.heartbeat_ttl,
            json.dumps(
                {
                    "computer_name": self.computer_name,
                    "last_seen": datetime.now().isoformat(),
                }
            ),
        )

        logger.debug("Sent heartbeat: %s", key)

    def _parse_target_from_title(self, title: str) -> Optional[str]:
        """Parse target computer name from title.

        Expected format: "$initiator > $target - description"

        Args:
            title: Channel title

        Returns:
            Target computer name or None
        """
        # Match: "$anything > $target - anything"
        match = re.match(r"^\$\w+ > \$(\w+) - ", title)
        if match:
            return match.group(1)

        return None

    # === MCP-specific methods for AI-to-AI communication ===

    async def send_command_to_computer(
        self, computer_name: str, session_id: str, command: str, metadata: Optional[dict[str, object]] = None
    ) -> str:
        """Send command to remote computer's command stream.

        Used by MCP server to initiate commands on remote computers.

        Args:
            computer_name: Target computer name
            session_id: Session ID
            command: Command to execute
            metadata: Optional metadata (title, initiator, etc.)

        Returns:
            Redis stream entry ID
        """
        if not self.redis:
            raise RuntimeError("Redis not initialized")

        command_stream = f"commands:{computer_name}"
        metadata = metadata or {}

        # Build command data
        data = {
            b"session_id": session_id.encode("utf-8"),
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
            command_stream,
            [k.decode("utf-8") for k in data.keys()],
        )

        message_id_bytes: bytes = await self.redis.xadd(command_stream, data, maxlen=self.command_stream_maxlen)

        logger.debug("XADD returned message_id=%s", message_id_bytes.decode("utf-8"))
        logger.info("Sent command to %s: session=%s, command=%s", computer_name, session_id[:8], command[:50])
        return message_id_bytes.decode("utf-8")

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
                    for stream_name, stream_messages in messages:
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
