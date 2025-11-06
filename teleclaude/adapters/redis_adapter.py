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
from typing import Any, Dict, List, Optional

from redis.asyncio import Redis

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.config import get_config

logger = logging.getLogger(__name__)


class RedisAdapter(BaseAdapter):
    """Adapter for AI-to-AI communication via Redis Streams.

    Uses Redis Streams for reliable, ordered message delivery between computers.

    Architecture:
    - Each computer polls its command stream: commands:{computer_name}
    - Each session has an output stream: output:{session_id}
    - Computer registry uses Redis keys with TTL for heartbeats

    Message flow:
    - Comp1 → XADD commands:comp2 → Comp2 polls → executes command
    - Comp2 → XADD output:session_id → Comp1 polls → streams to MCP
    """

    def __init__(self, session_manager: Any, daemon: Any):
        """Initialize Redis adapter.

        Args:
            session_manager: SessionManager instance
            daemon: Daemon instance for callbacks
        """
        super().__init__()
        self.session_manager = session_manager
        self.daemon = daemon
        self.redis: Optional[Redis] = None
        self.computer_name = ""
        self.bot_username = ""
        self._command_poll_task: Optional[asyncio.Task[None]] = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        self._running = False

        # Load config
        config = get_config()
        redis_config = config.get("redis", {})

        if not redis_config.get("enabled", True):
            raise ValueError("Redis adapter is disabled in config")

        self.redis_url = redis_config.get("url", "redis://localhost:6379")
        self.redis_password = redis_config.get("password")
        self.max_connections = redis_config.get("max_connections", 10)
        self.socket_timeout = redis_config.get("socket_timeout", 5)
        self.command_stream_maxlen = redis_config.get("command_stream_maxlen", 1000)
        self.output_stream_maxlen = redis_config.get("output_stream_maxlen", 10000)
        self.output_stream_ttl = redis_config.get("output_stream_ttl", 3600)

        # Get computer info
        computer_config = config.get("computer", {})
        self.computer_name = computer_config.get("name", "unknown")
        self.bot_username = computer_config.get("bot_username", "")

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

    async def send_message(self, session_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
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

        session = await self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Get output stream name from session metadata
        redis_metadata = session.adapter_metadata or {}
        if isinstance(redis_metadata, str):
            redis_metadata = json.loads(redis_metadata)

        redis_meta = redis_metadata.get("redis", {})
        output_stream = redis_meta.get("output_stream")

        if not output_stream:
            # Create stream name if not exists
            output_stream = f"output:{session_id}"
            redis_meta["output_stream"] = output_stream
            redis_metadata["redis"] = redis_meta

            # Update session
            await self.session_manager.update_session(session_id, adapter_metadata=redis_metadata)

        # Send to Redis stream
        message_id = await self.redis.xadd(
            output_stream,
            {
                b"chunk": text.encode("utf-8"),
                b"timestamp": str(time.time()).encode("utf-8"),
                b"session_id": session_id.encode("utf-8"),
            },
            maxlen=self.output_stream_maxlen,
        )

        logger.debug("Sent to Redis stream %s: %s", output_stream, message_id)
        return message_id.decode("utf-8")

    async def edit_message(
        self, session_id: str, message_id: str, text: str, metadata: Optional[Dict[str, Any]] = None
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

        session = await self.session_manager.get_session(session_id)
        if not session:
            return False

        redis_metadata = session.adapter_metadata or {}
        if isinstance(redis_metadata, str):
            redis_metadata = json.loads(redis_metadata)

        output_stream = redis_metadata.get("redis", {}).get("output_stream")
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
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send file metadata to Redis (actual file not transferred).

        Args:
            session_id: Session ID
            file_path: File path (sent as text reference)
            caption: Optional caption
            metadata: Optional metadata

        Returns:
            Message ID
        """
        message = f"[FILE: {file_path}]"
        if caption:
            message += f"\n{caption}"
        return await self.send_message(session_id, message, metadata)

    async def send_general_message(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
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

    async def create_channel(self, session_id: str, title: str, metadata: Optional[Dict[str, Any]] = None) -> str:
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
        session = await self.session_manager.get_session(session_id)
        if session:
            redis_metadata = session.adapter_metadata or {}
            if isinstance(redis_metadata, str):
                redis_metadata = json.loads(redis_metadata)

            redis_metadata["redis"] = {
                "command_stream": command_stream,
                "output_stream": output_stream,
            }

            await self.session_manager.update_session(session_id, adapter_metadata=redis_metadata)

        return output_stream

    async def update_channel_title(self, channel_id: str, title: str) -> bool:
        """Update channel title (no-op for Redis).

        Args:
            channel_id: Channel ID
            title: New title

        Returns:
            True
        """
        return True

    async def set_channel_status(self, channel_id: str, status: str) -> bool:
        """Set channel status (no-op for Redis).

        Args:
            channel_id: Channel ID
            status: Status string

        Returns:
            True
        """
        return True

    async def delete_channel(self, channel_id: str) -> bool:
        """Delete Redis stream.

        Args:
            channel_id: Stream name

        Returns:
            True if successful
        """
        if not self.redis:
            return False

        try:
            await self.redis.delete(channel_id)
            return True
        except Exception as e:
            logger.error("Failed to delete stream %s: %s", channel_id, e)
            return False

    async def discover_peers(self) -> List[Dict[str, Any]]:
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
        last_id = b"0-0"

        logger.info("Starting Redis command polling: %s", command_stream)

        while self._running:
            try:
                # Read commands from stream (blocking)
                messages = await self.redis.xread(
                    {command_stream.encode("utf-8"): last_id},
                    block=1000,  # Block for 1 second
                    count=5,
                )

                if not messages:
                    continue

                # Process commands
                for stream_name, stream_messages in messages:
                    for message_id, data in stream_messages:
                        await self._handle_incoming_command(data)
                        last_id = message_id

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Command polling error: %s", e)
                await asyncio.sleep(5)  # Back off on error

    async def _handle_incoming_command(self, data: Dict[bytes, bytes]) -> None:
        """Handle incoming command from Redis stream.

        Args:
            data: Command data dict from Redis stream
        """
        try:
            session_id = data.get(b"session_id", b"").decode("utf-8")
            command = data.get(b"command", b"").decode("utf-8")

            if not session_id or not command:
                logger.warning("Invalid command data: %s", data)
                return

            logger.info("Received command for session %s: %s", session_id[:8], command[:50])

            # Get or create session
            session = await self.session_manager.get_session(session_id)
            if not session:
                # Create new session for incoming AI request
                await self._create_session_from_redis(session_id, data)

            # Emit command event to daemon
            context = {
                "session_id": session_id,
                "adapter_type": "redis",
            }
            await self._emit_command(command, [], context)

        except Exception as e:
            logger.error("Failed to handle incoming command: %s", e)

    async def _create_session_from_redis(self, session_id: str, data: Dict[bytes, bytes]) -> None:
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

        # Create session
        await self.session_manager.create_session(
            session_id=session_id,
            computer_name=self.computer_name,
            tmux_session_name=tmux_session_name,
            adapter_type="redis",
            title=title,
            adapter_metadata={
                "redis": {
                    "command_stream": f"commands:{self.computer_name}",
                    "output_stream": f"output:{session_id}",
                }
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
                    "bot_username": self.bot_username,
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
