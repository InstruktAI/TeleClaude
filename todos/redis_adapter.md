# Redis Adapter Implementation - Multi-Adapter Architecture

## ✅ STATUS: Proposed Solution for AI-to-AI Communication

This document specifies the production-ready implementation of Redis-based AI-to-AI communication that bypasses Telegram's bot-to-bot messaging restriction.

**Key Innovation: Unified AdapterClient** - A clean abstraction that manages multiple adapters per session, allowing parallel broadcasting to Redis (for AI transport) and Telegram (for human observation).

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [AdapterClient - Unified Interface](#adapterclient---unified-interface)
4. [RedisAdapter Implementation](#redisadapter-implementation)
5. [BaseAdapter Interface Updates](#baseadapter-interface-updates)
6. [Session Schema Changes](#session-schema-changes)
7. [Daemon Integration](#daemon-integration)
8. [MCP Server Integration](#mcp-server-integration)
9. [Configuration](#configuration)
10. [Computer Registry with Redis](#computer-registry-with-redis)
11. [Implementation Phases](#implementation-phases)
12. [Testing Strategy](#testing-strategy)

---

## Overview

### The Problem

Telegram Bot API has a hard restriction: **bots cannot see messages from other bots**. This breaks the AI-to-AI communication architecture where Bot A needs to send commands to Bot B.

### The Solution

**Use Redis Streams as reliable message transport for AI-to-AI communication**, while keeping Telegram for human interaction.

### Multi-Adapter Pattern

Each AI-to-AI session uses **two adapters simultaneously**:

1. **RedisAdapter** (primary) - Reliable command/response transport for AI
2. **TelegramAdapter** (mirror) - Display copy for human observation and interaction

Both adapters receive the same output. Humans can observe and even interact with AI sessions via Telegram.

### Benefits

✅ **Bypasses Telegram bot restriction** - AI uses Redis, not Telegram messaging
✅ **Human transparency** - Everything visible in Telegram for observation
✅ **Human interaction** - Humans can join AI conversations
✅ **Clean abstraction** - Daemon code is adapter-agnostic via AdapterClient
✅ **Testable** - Mock AdapterClient in tests
✅ **Incremental** - Can add Redis without breaking existing Telegram sessions

---

## Architecture

### Layer Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│               Claude Code (MCP Client - Comp1)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │ MCP Tools
┌────────────────────────────▼────────────────────────────────────┐
│                    TeleClaudeDaemon (Comp1)                      │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              AdapterClient (Unified Interface)           │   │
│  │                                                          │   │
│  │  • send_message(session_id, text)                       │   │
│  │  • create_channel(title, adapter_types)                 │   │
│  │  • stream_messages(session_id, since_id)                │   │
│  │  • Session-aware routing                                │   │
│  │  • Parallel broadcasting                                │   │
│  │                                                          │   │
│  │  ┌────────────────┐        ┌──────────────────┐        │   │
│  │  │ RedisAdapter   │        │ TelegramAdapter  │        │   │
│  │  │ (Primary)      │        │ (Mirror)         │        │   │
│  │  └────────┬───────┘        └────────┬─────────┘        │   │
│  └───────────┼──────────────────────────┼──────────────────┘   │
│              │                          │                       │
└──────────────┼──────────────────────────┼───────────────────────┘
               │                          │
               ▼                          ▼
    ┌──────────────────┐      ┌────────────────────┐
    │  Redis Streams   │      │  Telegram Group    │
    │  (Central)       │      │                    │
    │                  │      │  Topic:            │
    │  commands:W      │      │  "$M > $W -        │
    │  output:sess123  │      │   Check logs"      │
    └──────────────────┘      └────────────────────┘
               ▲                          ▲
               │                          │
┌──────────────┼──────────────────────────┼───────────────────────┐
│  ┌───────────┴──────────┐  ┌───────────┴─────────┐             │
│  │  AdapterClient       │  │                     │             │
│  │  ┌────────────────┐  │  │                     │             │
│  │  │ RedisAdapter   │  │  │  TelegramAdapter    │             │
│  │  │ (Primary)      │  │  │  (Mirror)           │             │
│  │  └────────────────┘  │  │                     │             │
│  └──────────────────────┘  └─────────────────────┘             │
│                                                                  │
│                    TeleClaudeDaemon (Comp2)                      │
└──────────────────────────────────────────────────────────────────┘
```

### Message Flow Example

**Scenario: Comp1's Claude asks Comp2 to check logs**

1. **MCP call**: `await teleclaude__start_session("workstation", "Check logs")`
2. **Comp1 daemon**:
   - Calls `client.create_channel(title, ["redis", "telegram"])`
   - Client creates Redis streams + Telegram topic
   - Client sends wake-up command via Redis
3. **Comp2 daemon**:
   - RedisAdapter polls `commands:workstation` stream
   - Creates matching session with both adapters
   - Executes `/claude_resume` in tmux
4. **MCP call**: `async for chunk in teleclaude__send(session_id, "tail -f /var/log/nginx/error.log")`
5. **Comp1 daemon**:
   - Calls `client.send_message(session_id, command)`
   - Client sends via Redis, mirrors to Telegram
6. **Comp2 daemon**:
   - Receives command via Redis polling
   - Executes in tmux
   - Calls `client.send_message(session_id, output)` for each chunk
   - Client broadcasts to **both** Redis (for AI) and Telegram (for humans)
7. **Comp1 MCP server**:
   - Calls `client.stream_messages(session_id)`
   - Client streams from RedisAdapter
   - Yields chunks to Claude Code
8. **Humans watching Telegram**:
   - See same output in real-time
   - Can type commands in topic to interact!

---

## AdapterClient - Unified Interface

### Class Definition

```python
"""Unified client managing multiple adapters per session.

File: teleclaude/core/adapter_client.py
"""

import asyncio
import logging
from typing import Any, AsyncIterator, Optional

from teleclaude.adapters.base_adapter import BaseAdapter

logger = logging.getLogger(__name__)


class AdapterClient:
    """Unified interface for multi-adapter sessions.

    Manages multiple adapters (Redis, Telegram, etc.) per session and provides
    a clean, adapter-agnostic API for the daemon and MCP server.

    Key responsibilities:
    - Session-aware routing (knows which adapters each session uses)
    - Parallel broadcasting (send to all adapters concurrently)
    - Primary adapter selection (for streaming)
    - Adapter lifecycle management
    """

    def __init__(self, session_manager: Any):
        self.session_manager = session_manager
        self.adapters: dict[str, BaseAdapter] = {}  # type_name -> adapter instance

    def register_adapter(self, adapter_type: str, adapter: BaseAdapter):
        """Register an adapter (e.g., 'redis', 'telegram').

        Args:
            adapter_type: Adapter type name ('redis', 'telegram', etc.)
            adapter: Adapter instance implementing BaseAdapter
        """
        self.adapters[adapter_type] = adapter
        logger.info("Registered adapter: %s", adapter_type)

    async def send_message(self, session_id: str, text: str, parse_mode: Optional[str] = None):
        """Send message to all adapters for this session.

        Args:
            session_id: Session ID
            text: Message text
            parse_mode: Optional parse mode (for Telegram markdown/HTML)
        """
        # Get session to determine which adapters to use
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("send_message: session %s not found", session_id)
            return

        # Get adapters for this session
        session_adapters = self._get_session_adapters(session)
        if not session_adapters:
            logger.warning("send_message: no adapters for session %s", session_id)
            return

        # Broadcast to all adapters in parallel
        tasks = [
            adapter.send_message(session_id, text, parse_mode)
            for adapter in session_adapters
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any failures
        for adapter_type, result in zip(session.adapter_types, results):
            if isinstance(result, Exception):
                logger.error(
                    "send_message failed for adapter %s, session %s: %s",
                    adapter_type, session_id, result
                )

    async def create_channel(
        self,
        title: str,
        adapter_types: list[str],
        session_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Create channel in specified adapters.

        Args:
            title: Channel title/name
            adapter_types: List of adapter types to create channels in
            session_id: Optional session ID (for Redis stream naming)

        Returns:
            Dict mapping adapter_type -> channel metadata
            Example: {
                "redis": {"command_stream": "commands:workstation", "output_stream": "output:abc123"},
                "telegram": {"channel_id": "456", "topic_name": "$macbook > $workstation - Check logs"}
            }
        """
        results = {}

        # Create channels in parallel
        tasks = []
        for adapter_type in adapter_types:
            adapter = self.adapters.get(adapter_type)
            if not adapter:
                logger.warning("create_channel: adapter %s not registered", adapter_type)
                continue

            tasks.append((adapter_type, adapter.create_channel(title, session_id)))

        # Wait for all creates
        for adapter_type, task in tasks:
            try:
                metadata = await task
                results[adapter_type] = metadata
            except Exception as e:
                logger.error("create_channel failed for %s: %s", adapter_type, e)
                results[adapter_type] = {"error": str(e)}

        return results

    async def stream_messages(
        self,
        session_id: str,
        since_id: str = "0-0"
    ) -> AsyncIterator[dict]:
        """Stream messages from primary adapter for session.

        Args:
            session_id: Session to stream from
            since_id: Stream from after this message ID

        Yields:
            Message dicts with:
            - "text": Message content
            - "complete": True if stream finished (optional)
            - "timestamp": Message timestamp
            - "message_id": Message ID (for resuming)
        """
        # Get session to find primary adapter
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.error("stream_messages: session %s not found", session_id)
            return

        # Determine primary adapter (Redis for AI-to-AI, Telegram for human)
        primary_adapter = self._get_primary_adapter(session)
        if not primary_adapter:
            logger.error("stream_messages: no primary adapter for session %s", session_id)
            return

        # Stream from that adapter
        async for message in primary_adapter.stream_messages(session_id, since_id):
            yield message

    async def get_messages(
        self,
        session_id: str,
        limit: int = 100
    ) -> list[Any]:
        """Get recent messages from primary adapter.

        Args:
            session_id: Session ID
            limit: Max messages to return

        Returns:
            List of messages (adapter-specific format)
        """
        session = await self.session_manager.get_session(session_id)
        if not session:
            return []

        primary_adapter = self._get_primary_adapter(session)
        if not primary_adapter:
            return []

        return await primary_adapter.get_messages(session_id, limit)

    def _get_session_adapters(self, session) -> list[BaseAdapter]:
        """Get adapter instances for session.

        Args:
            session: Session object with adapter_types field

        Returns:
            List of adapter instances
        """
        adapters = []
        for adapter_type in session.adapter_types:
            adapter = self.adapters.get(adapter_type)
            if adapter:
                adapters.append(adapter)
            else:
                logger.warning("Adapter %s not registered", adapter_type)
        return adapters

    def _get_primary_adapter(self, session) -> Optional[BaseAdapter]:
        """Get primary adapter for session (first in list).

        Primary adapter is used for streaming/reading messages.
        For AI-to-AI sessions: Redis
        For human sessions: Telegram

        Args:
            session: Session object with adapter_types field

        Returns:
            Primary adapter instance or None
        """
        if not session.adapter_types:
            return None

        primary_type = session.adapter_types[0]
        return self.adapters.get(primary_type)
```

### Usage in Daemon

```python
# In daemon.py __init__:
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter

class TeleClaudeDaemon:
    def __init__(self, config_path: str, env_path: str):
        # ... existing init ...

        # Create unified client
        self.client = AdapterClient(self.session_manager)

        # Register adapters
        self.redis_adapter = RedisAdapter(redis_client, self.computer_name, self)
        self.telegram_adapter = TelegramAdapter(config, self)

        self.client.register_adapter("redis", self.redis_adapter)
        self.client.register_adapter("telegram", self.telegram_adapter)
```

```python
# Daemon code becomes adapter-agnostic:

# Old (adapter-specific):
await self.telegram_adapter.send_message(session_id, output)

# New (adapter-agnostic):
await self.client.send_message(session_id, output)
```

---

## RedisAdapter Implementation

### Class Definition

```python
"""Redis adapter for AI-to-AI communication.

File: teleclaude/adapters/redis_adapter.py
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Optional

from redis.asyncio import Redis

from teleclaude.adapters.base_adapter import BaseAdapter

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

    def __init__(
        self,
        redis_client: Redis,
        computer_name: str,
        daemon: Any,
        session_manager: Any
    ):
        self.redis = redis_client
        self.computer_name = computer_name
        self.daemon = daemon
        self.session_manager = session_manager

        # Tracking
        self.last_command_id = "0-0"  # For polling commands

        # Start background command polling
        asyncio.create_task(self._poll_redis_commands())

        logger.info("RedisAdapter initialized for %s", computer_name)

    async def start(self):
        """Start adapter (called by daemon)."""
        logger.info("RedisAdapter started")
        # Command polling already started in __init__

    async def stop(self):
        """Stop adapter gracefully."""
        logger.info("RedisAdapter stopping")
        # Close Redis connection
        await self.redis.aclose()

    async def send_message(
        self,
        session_id: str,
        text: str,
        parse_mode: Optional[str] = None
    ):
        """Send message chunk to Redis output stream.

        Args:
            session_id: Session ID
            text: Message text (output chunk)
            parse_mode: Ignored (Redis doesn't need parse mode)
        """
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.warning("send_message: session %s not found", session_id)
            return

        # Get output stream name from session metadata
        redis_metadata = session.adapter_metadata.get("redis", {})
        output_stream = redis_metadata.get("output_stream")

        if not output_stream:
            logger.error("send_message: no output_stream in session %s metadata", session_id)
            return

        try:
            # Append to Redis stream
            message_id = await self.redis.xadd(
                output_stream,
                {
                    "chunk": text,
                    "timestamp": str(time.time()),
                    "session_id": session_id
                }
            )

            logger.debug("Sent to Redis stream %s: message_id=%s", output_stream, message_id)

        except Exception as e:
            logger.error("Failed to send to Redis stream %s: %s", output_stream, e)
            raise

    async def create_channel(
        self,
        title: str,
        session_id: Optional[str] = None
    ) -> dict[str, str]:
        """Create Redis streams for session.

        Args:
            title: Channel title (format: "$initiator > $target - description")
            session_id: Session ID (required for stream naming)

        Returns:
            Dict with stream names:
            {
                "command_stream": "commands:workstation",
                "output_stream": "output:abc123"
            }
        """
        # Parse target from title
        target = self._parse_target_from_title(title)

        if not target:
            raise ValueError(f"Could not parse target from title: {title}")

        if not session_id:
            raise ValueError("session_id required for Redis channel creation")

        # Stream names
        command_stream = f"commands:{target}"
        output_stream = f"output:{session_id}"

        # Redis Streams are created automatically on first XADD
        # No explicit creation needed

        logger.info(
            "Created Redis streams: command=%s, output=%s",
            command_stream, output_stream
        )

        return {
            "command_stream": command_stream,
            "output_stream": output_stream
        }

    async def stream_messages(
        self,
        session_id: str,
        since_id: str = "0-0"
    ) -> AsyncIterator[dict]:
        """Stream messages from Redis output stream.

        Args:
            session_id: Session to stream from
            since_id: Stream from after this message ID (Redis stream entry ID)

        Yields:
            Message dicts with:
            - "text": Message content
            - "complete": True if stream finished
            - "timestamp": Message timestamp
            - "message_id": Redis stream entry ID
        """
        session = await self.session_manager.get_session(session_id)
        if not session:
            logger.error("stream_messages: session %s not found", session_id)
            return

        redis_metadata = session.adapter_metadata.get("redis", {})
        output_stream = redis_metadata.get("output_stream")

        if not output_stream:
            logger.error("stream_messages: no output_stream in session %s", session_id)
            return

        last_id = since_id
        timeout_count = 0
        max_timeout = 600  # 10 minutes of no messages

        while True:
            try:
                # Read from stream (blocking for 1 second)
                messages = await self.redis.xread(
                    {output_stream: last_id},
                    block=1000,  # Block for 1 second
                    count=10     # Read up to 10 messages per poll
                )

                if not messages:
                    timeout_count += 1
                    if timeout_count >= max_timeout:
                        logger.warning("stream_messages: timeout after %ds", max_timeout)
                        yield {
                            "text": "\n[Timeout: No response for 10 minutes]",
                            "complete": True,
                            "timestamp": time.time(),
                            "message_id": last_id
                        }
                        return
                    continue

                # Reset timeout counter
                timeout_count = 0

                # Process messages
                for stream_name, stream_messages in messages:
                    for message_id, data in stream_messages:
                        # Extract data
                        chunk = data.get(b"chunk", b"").decode("utf-8")
                        timestamp = float(data.get(b"timestamp", b"0").decode("utf-8"))
                        complete = data.get(b"complete", b"false").decode("utf-8") == "true"

                        yield {
                            "text": chunk,
                            "complete": complete,
                            "timestamp": timestamp,
                            "message_id": message_id.decode("utf-8")
                        }

                        last_id = message_id

                        # End stream if complete
                        if complete:
                            return

            except Exception as e:
                logger.error("stream_messages error: %s", e)
                yield {
                    "text": f"\n[Error streaming: {e}]",
                    "complete": True,
                    "timestamp": time.time(),
                    "message_id": last_id
                }
                return

    async def get_messages(
        self,
        session_id: str,
        limit: int = 100
    ) -> list[dict]:
        """Get recent messages from Redis stream.

        Args:
            session_id: Session ID
            limit: Max messages to return

        Returns:
            List of message dicts
        """
        session = await self.session_manager.get_session(session_id)
        if not session:
            return []

        redis_metadata = session.adapter_metadata.get("redis", {})
        output_stream = redis_metadata.get("output_stream")

        if not output_stream:
            return []

        try:
            # Read last N messages from stream
            messages = await self.redis.xrevrange(output_stream, count=limit)

            # Convert to dict format
            result = []
            for message_id, data in reversed(messages):
                result.append({
                    "message_id": message_id.decode("utf-8"),
                    "text": data.get(b"chunk", b"").decode("utf-8"),
                    "timestamp": float(data.get(b"timestamp", b"0").decode("utf-8"))
                })

            return result

        except Exception as e:
            logger.error("get_messages error: %s", e)
            return []

    async def _poll_redis_commands(self):
        """Background task: Poll commands:{computer_name} stream for incoming commands.

        This is how Comp2 receives commands from Comp1.
        """
        command_stream = f"commands:{self.computer_name}"
        last_id = "0-0"

        logger.info("Starting Redis command polling: %s", command_stream)

        while True:
            try:
                # Read commands from stream (blocking)
                messages = await self.redis.xread(
                    {command_stream: last_id},
                    block=1000,  # Block for 1 second
                    count=5
                )

                if not messages:
                    continue

                # Process commands
                for stream_name, stream_messages in messages:
                    for message_id, data in stream_messages:
                        await self._handle_incoming_command(data)
                        last_id = message_id

            except Exception as e:
                logger.error("Command polling error: %s", e)
                await asyncio.sleep(5)  # Back off on error

    async def _handle_incoming_command(self, data: dict):
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

            logger.info("Received command for session %s: %s", session_id, command[:50])

            # Get or create session
            session = await self.session_manager.get_session(session_id)
            if not session:
                # Create new session for incoming AI request
                await self._create_session_from_redis(session_id, data)
                session = await self.session_manager.get_session(session_id)

            # Execute command in tmux
            await self.daemon.terminal_bridge.send_keys(
                session.tmux_session_name,
                command
            )

            # Start output polling (will broadcast to all adapters)
            asyncio.create_task(
                self.daemon._poll_and_send_output(session_id)
            )

        except Exception as e:
            logger.error("Failed to handle incoming command: %s", e)

    async def _create_session_from_redis(self, session_id: str, data: dict):
        """Create session from incoming Redis command data.

        Args:
            session_id: Session ID
            data: Command data from Redis (contains metadata)
        """
        # Extract metadata from command
        title = data.get(b"title", b"Unknown Session").decode("utf-8")
        initiator = data.get(b"initiator", b"unknown").decode("utf-8")

        # Create tmux session name
        tmux_session_name = f"{self.computer_name}-ai-{session_id[:8]}"

        # Create session with both Redis and Telegram adapters
        await self.session_manager.create_session(
            session_id=session_id,
            computer_name=self.computer_name,
            title=title,
            tmux_session_name=tmux_session_name,
            adapter_types=["redis", "telegram"],  # Both adapters
            adapter_metadata={
                "redis": {
                    "command_stream": f"commands:{self.computer_name}",
                    "output_stream": f"output:{session_id}"
                },
                "telegram": {
                    "channel_id": None,  # Will be created by TelegramAdapter
                    "topic_name": title
                }
            },
            description=f"AI-to-AI session from {initiator}"
        )

        logger.info("Created session %s from Redis command", session_id)

    def _parse_target_from_title(self, title: str) -> Optional[str]:
        """Parse target computer name from title.

        Expected format: "$initiator > $target - description"

        Args:
            title: Channel title

        Returns:
            Target computer name or None
        """
        import re

        # Match: "$anything > $target - anything"
        match = re.match(r'^\$\w+ > \$(\w+) - ', title)
        if match:
            return match.group(1)

        return None
```

---

## BaseAdapter Interface Updates

### Add stream_messages() Method

```python
# File: teleclaude/adapters/base_adapter.py

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional


class BaseAdapter(ABC):
    """Base adapter interface for all messaging platforms."""

    # ... existing methods (start, stop, send_message, create_channel) ...

    @abstractmethod
    async def stream_messages(
        self,
        session_id: str,
        since_id: str = "0-0"
    ) -> AsyncIterator[dict]:
        """Stream messages from this adapter's channel.

        Used by AdapterClient to stream output for MCP tools.

        Args:
            session_id: Session to stream from
            since_id: Stream from after this message ID (adapter-specific format)

        Yields:
            Message dicts with:
            - "text": Message content
            - "complete": True if stream finished (optional)
            - "timestamp": Message timestamp (Unix seconds)
            - "message_id": Message ID for resuming (adapter-specific)
        """
        pass

    @abstractmethod
    async def get_messages(
        self,
        session_id: str,
        limit: int = 100
    ) -> list[Any]:
        """Get recent messages from channel.

        Args:
            session_id: Session ID
            limit: Max messages to return

        Returns:
            List of messages (adapter-specific format)
        """
        pass
```

### TelegramAdapter Implementation

```python
# File: teleclaude/adapters/telegram_adapter.py

async def stream_messages(
    self,
    session_id: str,
    since_id: str = "0"
) -> AsyncIterator[dict]:
    """Stream from Telegram topic message cache.

    Args:
        session_id: Session ID
        since_id: Telegram message ID (as string)

    Yields:
        Message dicts
    """
    session = await self.session_manager.get_session(session_id)
    if not session:
        return

    telegram_metadata = session.adapter_metadata.get("telegram", {})
    topic_id = telegram_metadata.get("channel_id")

    if not topic_id:
        logger.error("stream_messages: no topic_id for session %s", session_id)
        return

    last_msg_id = int(since_id)
    timeout_count = 0
    max_timeout = 600  # 10 minutes

    while True:
        # Get messages from cache
        messages = await self.get_topic_messages(topic_id, limit=10)

        # Filter messages after since_id
        new_messages = [m for m in messages if m.message_id > last_msg_id]

        if new_messages:
            timeout_count = 0

            for msg in new_messages:
                yield {
                    "text": msg.text,
                    "complete": "[Output Complete]" in msg.text,
                    "timestamp": msg.date.timestamp(),
                    "message_id": str(msg.message_id)
                }

                last_msg_id = msg.message_id

                if "[Output Complete]" in msg.text:
                    return
        else:
            timeout_count += 1
            if timeout_count >= max_timeout:
                yield {
                    "text": "\n[Timeout: No response for 10 minutes]",
                    "complete": True,
                    "timestamp": time.time(),
                    "message_id": str(last_msg_id)
                }
                return

        await asyncio.sleep(0.5)  # Poll interval

async def get_messages(
    self,
    session_id: str,
    limit: int = 100
) -> list[Any]:
    """Get recent messages from Telegram topic.

    Args:
        session_id: Session ID
        limit: Max messages to return

    Returns:
        List of Telegram Message objects
    """
    session = await self.session_manager.get_session(session_id)
    if not session:
        return []

    telegram_metadata = session.adapter_metadata.get("telegram", {})
    topic_id = telegram_metadata.get("channel_id")

    if not topic_id:
        return []

    return await self.get_topic_messages(topic_id, limit)
```

---

## Session Schema Changes

### Database Schema Update

```sql
-- File: teleclaude/core/schema.sql

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    computer_name TEXT NOT NULL,
    title TEXT NOT NULL,
    tmux_session_name TEXT NOT NULL,

    -- Multi-adapter support (NEW)
    adapter_types TEXT NOT NULL DEFAULT '["telegram"]',  -- JSON array: ["redis", "telegram"]

    -- Adapter-specific metadata (UPDATED - now supports multiple adapters)
    adapter_metadata TEXT,  -- JSON: {"redis": {...}, "telegram": {...}}

    -- Existing fields
    description TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed INTEGER DEFAULT 0,

    -- Indexes
    INDEX idx_computer_name (computer_name),
    INDEX idx_status (status),
    INDEX idx_closed (closed)
);
```

### Models Update

```python
# File: teleclaude/core/models.py

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any, Optional


@dataclass
class Session:
    """Session model with multi-adapter support."""

    session_id: str
    computer_name: str
    title: str
    tmux_session_name: str

    # Multi-adapter fields (NEW)
    adapter_types: list[str] = field(default_factory=lambda: ["telegram"])

    # Adapter metadata (UPDATED - now dict of adapter configs)
    adapter_metadata: dict[str, Any] = field(default_factory=dict)

    # Existing fields
    description: Optional[str] = None
    status: str = "active"
    created_at: datetime = field(default_factory=datetime.now)
    closed: bool = False

    def to_dict(self) -> dict:
        """Convert to dict for database storage."""
        return {
            "session_id": self.session_id,
            "computer_name": self.computer_name,
            "title": self.title,
            "tmux_session_name": self.tmux_session_name,
            "adapter_types": json.dumps(self.adapter_types),  # Serialize to JSON
            "adapter_metadata": json.dumps(self.adapter_metadata),  # Serialize to JSON
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "closed": 1 if self.closed else 0
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        """Create from database row dict."""
        return cls(
            session_id=data["session_id"],
            computer_name=data["computer_name"],
            title=data["title"],
            tmux_session_name=data["tmux_session_name"],
            adapter_types=json.loads(data.get("adapter_types", '["telegram"]')),
            adapter_metadata=json.loads(data.get("adapter_metadata", "{}")),
            description=data.get("description"),
            status=data.get("status", "active"),
            created_at=datetime.fromisoformat(data["created_at"]),
            closed=bool(data.get("closed", 0))
        )
```

### SessionManager Update

```python
# File: teleclaude/core/session_manager.py

async def create_session(
    self,
    session_id: str,
    computer_name: str,
    title: str,
    tmux_session_name: str,
    adapter_types: list[str],  # NEW parameter
    adapter_metadata: dict[str, Any],  # UPDATED - now dict of adapter configs
    description: Optional[str] = None
) -> Session:
    """Create new session with multi-adapter support.

    Args:
        session_id: Unique session ID
        computer_name: Computer this session belongs to
        title: Session title
        tmux_session_name: tmux session name
        adapter_types: List of adapter types (e.g., ["redis", "telegram"])
        adapter_metadata: Dict mapping adapter type to metadata
        description: Optional description

    Returns:
        Created Session object
    """
    session = Session(
        session_id=session_id,
        computer_name=computer_name,
        title=title,
        tmux_session_name=tmux_session_name,
        adapter_types=adapter_types,
        adapter_metadata=adapter_metadata,
        description=description
    )

    async with aiosqlite.connect(self.db_path) as db:
        await db.execute(
            """
            INSERT INTO sessions (
                session_id, computer_name, title, tmux_session_name,
                adapter_types, adapter_metadata, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.computer_name,
                session.title,
                session.tmux_session_name,
                json.dumps(session.adapter_types),
                json.dumps(session.adapter_metadata),
                session.description
            )
        )
        await db.commit()

    logger.info("Created session %s with adapters %s", session_id, adapter_types)
    return session
```

---

## Daemon Integration

### Replace Adapter Calls with Client

```python
# File: teleclaude/daemon.py

class TeleClaudeDaemon:
    def __init__(self, config_path: str, env_path: str):
        # ... existing init ...

        # Initialize Redis client
        import redis.asyncio as aioredis
        self.redis_client = aioredis.from_url(
            self.config["redis"]["url"],
            password=self.config["redis"].get("password"),
            decode_responses=False  # We handle decoding
        )

        # Create unified client
        self.client = AdapterClient(self.session_manager)

        # Create and register adapters
        self.redis_adapter = RedisAdapter(
            redis_client=self.redis_client,
            computer_name=self.config["computer"]["name"],
            daemon=self,
            session_manager=self.session_manager
        )

        self.telegram_adapter = TelegramAdapter(
            config=telegram_config,
            daemon=self,
            session_manager=self.session_manager
        )

        # Register with client
        self.client.register_adapter("redis", self.redis_adapter)
        self.client.register_adapter("telegram", self.telegram_adapter)

        logger.info("Daemon initialized with adapters: redis, telegram")

    async def _poll_and_send_output(self, session_id: str):
        """Poll tmux and send output to ALL adapters for session.

        This method is adapter-agnostic - it just calls client.send_message()
        and the client handles broadcasting to all adapters.
        """
        session = await self.session_manager.get_session(session_id)
        if not session:
            return

        # Poll tmux output
        async for output_chunk in self.terminal_bridge.poll_output(session_id):
            # Send to ALL adapters via client (broadcasts automatically)
            await self.client.send_message(session_id, output_chunk)

            # Check for completion
            if self._is_process_finished(output_chunk):
                # Send completion marker
                await self.client.send_message(session_id, "[Output Complete]")
                break
```

### Human Message Handling (Unchanged!)

```python
# TelegramAdapter still handles human messages directly
# This doesn't change - only AI-to-AI uses Redis

async def _handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle human text message in Telegram topic."""
    session = await self._get_session_from_topic(update)
    if not session:
        return

    text = update.message.text

    # Forward to tmux (human interaction in AI session is allowed!)
    await self.daemon.terminal_bridge.send_keys(
        session.tmux_session_name,
        text
    )

    # Output will be broadcast to all adapters automatically
```

---

## MCP Server Integration

### Adapter-Agnostic MCP Tools

```python
# File: teleclaude/mcp_server.py

class TeleClaudeMCPServer:
    def __init__(self, config: dict, daemon: Any):
        self.config = config
        self.daemon = daemon
        self.client = daemon.client  # Use unified client

    async def teleclaude__start_session(
        self,
        target: str,
        title: str,
        description: str
    ) -> dict:
        """Start AI-to-AI session - adapter-agnostic!"""

        # Validate target is online
        if not self.daemon.computer_registry.is_computer_online(target):
            return {
                "status": "error",
                "message": f"Computer '{target}' is offline"
            }

        # Create session ID
        session_id = str(uuid.uuid4())

        # Create topic name
        topic_name = f"${self.daemon.computer_name} > ${target} - {title}"

        # Create channels in BOTH adapters via client
        channel_metadata = await self.client.create_channel(
            title=topic_name,
            adapter_types=["redis", "telegram"],  # Both!
            session_id=session_id
        )

        # Create session in database
        await self.daemon.session_manager.create_session(
            session_id=session_id,
            computer_name=self.daemon.computer_name,
            title=topic_name,
            tmux_session_name=f"{self.daemon.computer_name}-ai-{session_id[:8]}",
            adapter_types=["redis", "telegram"],
            adapter_metadata=channel_metadata,
            description=description
        )

        # Send wake-up command via client (routes to Redis automatically)
        await self._send_command_via_client(session_id, "/claude_resume", target)

        # Wait for ready confirmation
        await self._wait_for_ready(session_id, timeout=10)

        return {
            "session_id": session_id,
            "topic_name": topic_name,
            "status": "ready"
        }

    async def teleclaude__send(
        self,
        session_id: str,
        message: str
    ) -> AsyncIterator[str]:
        """Send command and stream response - adapter-agnostic!

        This is the cleanest part: no Redis-specific code!
        """
        # Validate session
        session = await self.daemon.session_manager.get_session(session_id)
        if not session:
            yield "[Error: Session not found]"
            return

        if session.closed:
            yield "[Error: Session is closed]"
            return

        # Send message via client (routes automatically)
        await self.client.send_message(session_id, message)

        # Stream response via client (reads from primary adapter automatically)
        async for msg in self.client.stream_messages(session_id):
            if msg.get("complete"):
                return

            yield msg["text"]

    async def _send_command_via_client(
        self,
        session_id: str,
        command: str,
        target: str
    ):
        """Send command to target computer via Redis.

        This directly uses Redis for command delivery (not client.send_message
        which is for output broadcasting).
        """
        # Get command stream for target
        command_stream = f"commands:{target}"

        # Send command via Redis
        await self.daemon.redis_client.xadd(
            command_stream,
            {
                "session_id": session_id,
                "command": command,
                "initiator": self.daemon.computer_name,
                "title": f"${self.daemon.computer_name} > ${target}",
                "timestamp": str(time.time())
            }
        )

    async def _wait_for_ready(self, session_id: str, timeout: int = 10):
        """Wait for remote Claude Code to signal ready."""
        start = time.time()

        while time.time() - start < timeout:
            # Get recent messages via client
            messages = await self.client.get_messages(session_id, limit=5)

            for msg in messages:
                text = msg.get("text", "")
                if "Claude Code ready" in text or "Starting Claude Code" in text:
                    return

            await asyncio.sleep(0.5)

        raise TimeoutError(f"Remote Claude Code did not start within {timeout}s")
```

---

## Configuration

### config.yml Updates

```yaml
# File: config.yml.sample

computer:
  name: macbook  # Unique per computer
  bot_username: teleclaude_macbook_bot
  default_shell: /bin/zsh
  default_working_dir: ${WORKING_DIR}

telegram:
  supergroup_id: ${TELEGRAM_SUPERGROUP_ID}

  # Bot whitelist (unchanged)
  trusted_bots:
    - teleclaude_macbook_bot
    - teleclaude_workstation_bot

# NEW: Redis configuration
redis:
  # Redis connection URL
  url: redis://your-redis-host:6379

  # Optional password
  password: ${REDIS_PASSWORD}

  # Connection pool settings
  max_connections: 10
  socket_timeout: 5

  # Stream settings
  command_stream_maxlen: 1000   # Max commands to keep per computer
  output_stream_maxlen: 10000   # Max output messages per session
  output_stream_ttl: 3600       # Auto-expire output streams after 1 hour

mcp:
  enabled: true
  transport: stdio
  claude_command: claude
```

### .env Updates

```bash
# File: .env.sample

# Telegram (unchanged)
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_SUPERGROUP_ID=-100123456789

# Computer identifier
COMPUTER_NAME=macbook

# NEW: Redis credentials
REDIS_PASSWORD=your_redis_password_here

# Working directory
WORKING_DIR=/Users/user/teleclaude
```

### requirements.txt Updates

```txt
# File: requirements.txt

# Existing dependencies
python-telegram-bot==21.9
aiosqlite==0.20.0
python-dotenv==1.0.1
pyyaml==6.0.2
mcp>=1.0.0

# NEW: Redis
redis>=5.0.0
```

---

## Computer Registry with Redis

### Redis-Based Heartbeat

Replace Telegram-based computer registry with Redis keys + TTL:

```python
# File: teleclaude/core/computer_registry.py

class ComputerRegistry:
    """Computer discovery via Redis heartbeats."""

    def __init__(
        self,
        redis_client: Redis,
        computer_name: str,
        bot_username: str
    ):
        self.redis = redis_client
        self.computer_name = computer_name
        self.bot_username = bot_username

        # Configuration
        self.heartbeat_interval = 30  # Send heartbeat every 30s
        self.heartbeat_ttl = 60       # Key expires after 60s

    async def start(self):
        """Start heartbeat and polling."""
        logger.info("Starting Redis-based computer registry")

        # Send initial heartbeat
        await self._send_heartbeat()

        # Start background heartbeat loop
        asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        """Send heartbeat every N seconds."""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self._send_heartbeat()
            except Exception as e:
                logger.error("Heartbeat failed: %s", e)

    async def _send_heartbeat(self):
        """Set Redis key with TTL as heartbeat."""
        key = f"computer:{self.computer_name}:heartbeat"

        # Set key with auto-expiry
        await self.redis.setex(
            key,
            self.heartbeat_ttl,
            json.dumps({
                "computer_name": self.computer_name,
                "bot_username": self.bot_username,
                "last_seen": datetime.now().isoformat()
            })
        )

        logger.debug("Sent heartbeat: %s", key)

    async def get_online_computers(self) -> list[dict]:
        """Get list of online computers (keys that exist).

        Returns:
            List of computer info dicts
        """
        # Find all heartbeat keys
        keys = await self.redis.keys("computer:*:heartbeat")

        computers = []
        for key in keys:
            # Get data
            data = await self.redis.get(key)
            if data:
                info = json.loads(data)
                computers.append({
                    "name": info["computer_name"],
                    "bot_username": info["bot_username"],
                    "status": "online",
                    "last_seen": info["last_seen"]
                })

        return sorted(computers, key=lambda c: c["name"])

    def is_computer_online(self, computer_name: str) -> bool:
        """Check if computer is online (key exists)."""
        key = f"computer:{computer_name}:heartbeat"
        return await self.redis.exists(key) > 0
```

### Benefits

✅ **Simpler** - No Telegram topic polling, just Redis key lookups
✅ **Automatic cleanup** - TTL expires stale computers
✅ **Fast** - Redis key lookups are O(1)
✅ **Reliable** - No dependency on Telegram for registry

---

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1)

**Goal: Get basic Redis communication working**

Tasks:
1. Add redis dependency to requirements.txt
2. Create AdapterClient class in `teleclaude/core/adapter_client.py`
3. Create RedisAdapter class in `teleclaude/adapters/redis_adapter.py`
4. Add `stream_messages()` to BaseAdapter interface
5. Implement `stream_messages()` in TelegramAdapter
6. Update Session model with `adapter_types` field
7. Update SessionManager.create_session() signature
8. Add Redis config to config.yml.sample
9. Update daemon to initialize AdapterClient and register adapters

Deliverable:
- AdapterClient can manage multiple adapters
- RedisAdapter can send/receive via Redis Streams
- Tests pass (unit tests for AdapterClient, RedisAdapter)

### Phase 2: Computer Registry (Week 1)

**Goal: Redis-based computer discovery**

Tasks:
1. Rewrite ComputerRegistry to use Redis keys + TTL
2. Remove Telegram topic dependency from registry
3. Update daemon to use Redis registry
4. Test multi-computer discovery

Deliverable:
- Computers discover each other via Redis heartbeats
- `teleclaude__list_computers` returns online computers

### Phase 3: MCP Tools Integration (Week 2)

**Goal: AI-to-AI sessions working end-to-end**

Tasks:
1. Update `teleclaude__start_session` to create channels via client
2. Update `teleclaude__send` to use client.stream_messages()
3. Add `_send_command_via_client()` helper for command delivery
4. Update daemon's `_poll_and_send_output` to use client
5. Test end-to-end: Comp1 → Comp2 command execution + streaming

Deliverable:
- Full AI-to-AI communication working
- Comp1's Claude can execute commands on Comp2
- Output streams back to Comp1 in real-time

### Phase 4: Human Interaction (Week 2)

**Goal: Humans can observe and interact with AI sessions**

Tasks:
1. Verify Telegram mirroring works (both adapters receive output)
2. Test human typing in AI session topic (should work automatically)
3. Add logging/debugging for adapter broadcasting
4. Performance testing (multiple concurrent sessions)

Deliverable:
- Humans see AI-to-AI sessions in Telegram
- Humans can type commands in AI session topics
- All 331+ tests pass

### Phase 5: Production Hardening (Week 3)

**Goal: Production-ready system**

Tasks:
1. Error handling (Redis connection failures, timeout handling)
2. Graceful degradation (continue if Redis unavailable)
3. Stream cleanup (auto-expire old output streams)
4. Monitoring/metrics (Redis connection health, stream sizes)
5. Documentation updates (architecture.md, user guide)
6. Load testing (10+ concurrent AI sessions)

Deliverable:
- Production-ready Redis adapter
- Comprehensive error handling
- Performance validated
- Documentation complete

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/test_adapter_client.py

import pytest
from unittest.mock import AsyncMock, Mock

from teleclaude.core.adapter_client import AdapterClient


@pytest.mark.asyncio
async def test_adapter_client_registers_adapters():
    """Test registering adapters with client."""
    session_manager = Mock()
    client = AdapterClient(session_manager)

    redis_adapter = Mock()
    telegram_adapter = Mock()

    client.register_adapter("redis", redis_adapter)
    client.register_adapter("telegram", telegram_adapter)

    assert "redis" in client.adapters
    assert "telegram" in client.adapters


@pytest.mark.asyncio
async def test_send_message_broadcasts_to_all_adapters():
    """Test that send_message broadcasts to all adapters."""
    session_manager = Mock()
    session_manager.get_session = AsyncMock(return_value=Mock(
        adapter_types=["redis", "telegram"]
    ))

    client = AdapterClient(session_manager)

    redis_adapter = Mock()
    redis_adapter.send_message = AsyncMock()
    telegram_adapter = Mock()
    telegram_adapter.send_message = AsyncMock()

    client.register_adapter("redis", redis_adapter)
    client.register_adapter("telegram", telegram_adapter)

    await client.send_message("session123", "test message")

    # Both adapters should receive message
    redis_adapter.send_message.assert_called_once_with("session123", "test message", None)
    telegram_adapter.send_message.assert_called_once_with("session123", "test message", None)


@pytest.mark.asyncio
async def test_stream_messages_from_primary_adapter():
    """Test streaming from primary adapter (first in list)."""
    session_manager = Mock()
    session_manager.get_session = AsyncMock(return_value=Mock(
        adapter_types=["redis", "telegram"]  # Redis is primary
    ))

    client = AdapterClient(session_manager)

    async def mock_stream():
        yield {"text": "chunk1", "complete": False}
        yield {"text": "chunk2", "complete": True}

    redis_adapter = Mock()
    redis_adapter.stream_messages = mock_stream

    client.register_adapter("redis", redis_adapter)

    chunks = []
    async for chunk in client.stream_messages("session123"):
        chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[0]["text"] == "chunk1"
    assert chunks[1]["complete"] is True
```

```python
# tests/unit/test_redis_adapter.py

import pytest
from unittest.mock import AsyncMock, Mock, patch

from teleclaude.adapters.redis_adapter import RedisAdapter


@pytest.mark.asyncio
async def test_redis_adapter_send_message():
    """Test sending message to Redis stream."""
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock(return_value=b"1234567890-0")

    session_manager = Mock()
    session_manager.get_session = AsyncMock(return_value=Mock(
        adapter_metadata={
            "redis": {"output_stream": "output:abc123"}
        }
    ))

    adapter = RedisAdapter(redis_client, "macbook", Mock(), session_manager)

    await adapter.send_message("abc123", "test output")

    redis_client.xadd.assert_called_once()
    call_args = redis_client.xadd.call_args
    assert call_args[0][0] == "output:abc123"
    assert b"test output" in call_args[0][1][b"chunk"] or "test output" in call_args[0][1]["chunk"]


@pytest.mark.asyncio
async def test_redis_adapter_stream_messages():
    """Test streaming messages from Redis."""
    redis_client = AsyncMock()

    # Mock XREAD responses
    redis_client.xread = AsyncMock(side_effect=[
        # First poll: 2 messages
        [("output:abc123", [
            (b"1234-0", {b"chunk": b"chunk1", b"timestamp": b"123.45", b"complete": b"false"}),
            (b"1234-1", {b"chunk": b"chunk2", b"timestamp": b"123.46", b"complete": b"true"}),
        ])],
    ])

    session_manager = Mock()
    session_manager.get_session = AsyncMock(return_value=Mock(
        adapter_metadata={
            "redis": {"output_stream": "output:abc123"}
        }
    ))

    adapter = RedisAdapter(redis_client, "macbook", Mock(), session_manager)

    chunks = []
    async for msg in adapter.stream_messages("abc123"):
        chunks.append(msg)
        if msg.get("complete"):
            break

    assert len(chunks) == 2
    assert chunks[0]["text"] == "chunk1"
    assert chunks[1]["complete"] is True
```

### Integration Tests

```python
# tests/integration/test_redis_ai_to_ai.py

import pytest
import asyncio
from redis.asyncio import Redis

from teleclaude.daemon import TeleClaudeDaemon


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_command_delivery():
    """Test command delivery via Redis between two computers."""
    # Setup Redis
    redis = Redis.from_url("redis://localhost:6379")

    # Setup two daemons
    daemon1 = await start_test_daemon("macbook", redis)
    daemon2 = await start_test_daemon("workstation", redis)

    # Comp1 sends command to Comp2
    session_id = "test-session-123"
    await daemon1.redis_client.xadd(
        "commands:workstation",
        {
            "session_id": session_id,
            "command": "echo 'Hello from macbook'",
            "initiator": "macbook"
        }
    )

    # Wait for Comp2 to process
    await asyncio.sleep(2)

    # Check output stream
    messages = await redis.xread({"output:test-session-123": "0-0"}, count=10)

    assert len(messages) > 0
    output = b"".join([msg[b"chunk"] for stream, msgs in messages for msg_id, msg in msgs])
    assert b"Hello from macbook" in output


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_end_to_end_with_redis():
    """Test full MCP flow with Redis adapter."""
    # Start two daemons with Redis
    daemon1 = await start_test_daemon("macbook")
    daemon2 = await start_test_daemon("workstation")

    # MCP call from Comp1
    session = await daemon1.mcp_server.teleclaude__start_session(
        target="workstation",
        title="Test session",
        description="Integration test"
    )

    assert session["status"] == "ready"
    session_id = session["session_id"]

    # Send command and collect output
    output_chunks = []
    async for chunk in daemon1.mcp_server.teleclaude__send(
        session_id,
        "echo 'Redis works!'"
    ):
        output_chunks.append(chunk)

    full_output = "".join(output_chunks)
    assert "Redis works!" in full_output
```

---

## Benefits Summary

### Technical Benefits

✅ **Bypasses Telegram bot restriction** - AI uses Redis, not Telegram bot messaging
✅ **Reliable message delivery** - Redis Streams guarantee order and persistence
✅ **Clean architecture** - Unified client abstracts adapter complexity
✅ **Human transparency** - Everything visible in Telegram via mirroring
✅ **Human interaction** - Humans can join AI conversations
✅ **Testable** - Mock AdapterClient, test adapters independently
✅ **Scalable** - Redis handles high throughput, low latency
✅ **Observable** - `redis-cli MONITOR` for debugging
✅ **Automatic cleanup** - Stream TTL, registry key expiry

### Implementation Benefits

✅ **Minimal code changes** - ~800 lines of new code, existing code mostly unchanged
✅ **Incremental rollout** - Can deploy Redis without breaking Telegram sessions
✅ **No interface changes** - MCP tools remain adapter-agnostic
✅ **Easy deployment** - Single Redis instance serves all computers
✅ **Low ops burden** - Redis Cloud free tier or simple Docker container

---

## Deployment Guide

### Option 1: Redis Cloud (Easiest)

1. Sign up at https://redis.com/try-free/
2. Create database (30MB free tier)
3. Copy connection URL and password
4. Update config.yml:
   ```yaml
   redis:
     url: redis://redis-12345.c1.us-east-1-2.ec2.redns.redis-cloud.com:12345
     password: ${REDIS_PASSWORD}
   ```
5. Set REDIS_PASSWORD in .env
6. Restart daemon: `make restart`

### Option 2: Docker (Self-Hosted)

```bash
# Run Redis container
docker run -d \
  --name teleclaude-redis \
  -p 6379:6379 \
  -v redis-data:/data \
  redis:alpine \
  redis-server --requirepass your-password

# Update config.yml
redis:
  url: redis://localhost:6379
  password: your-password

# Restart daemon
make restart
```

### Option 3: Tailscale + Docker (Most Secure)

```bash
# On central server (e.g., always-on Mac Mini):
tailscale up
docker run -d \
  --name teleclaude-redis \
  -p 100.64.1.100:6379:6379 \
  redis:alpine \
  redis-server --requirepass your-password

# On each computer:
# config.yml
redis:
  url: redis://100.64.1.100:6379  # Tailscale IP
  password: your-password
```

**Benefits:**
- Redis only accessible via VPN
- No public exposure
- Encrypted + authenticated

---

## Success Metrics

### Functionality
- ✅ Claude Code on Comp1 can list all online computers
- ✅ Claude Code on Comp1 can execute commands on Comp2
- ✅ Output streams back to Comp1 in real-time (<1s latency)
- ✅ Humans can observe AI sessions in Telegram
- ✅ Humans can interact with AI sessions via Telegram

### Performance
- Response latency: <1s from command to first output chunk
- Streaming latency: <500ms between chunk generation and delivery
- Concurrent sessions: 10+ simultaneous AI-to-AI sessions per computer

### Reliability
- Zero crashes during normal operation
- Graceful degradation if Redis unavailable (Telegram-only mode)
- Session state survives daemon restarts
- All 331+ tests pass

---

## Appendix: Redis Commands Reference

### Debugging Commands

```bash
# Monitor all Redis activity
redis-cli MONITOR

# List all streams
redis-cli KEYS "*"

# Read from command stream
redis-cli XREAD STREAMS commands:workstation 0-0

# Read from output stream
redis-cli XREAD STREAMS output:abc123 0-0

# Check heartbeat keys
redis-cli KEYS "computer:*:heartbeat"

# Get computer info
redis-cli GET computer:macbook:heartbeat

# Delete stream (cleanup)
redis-cli DEL output:abc123
```

### Stream Management

```bash
# Trim stream to last 1000 entries
redis-cli XTRIM output:abc123 MAXLEN 1000

# Get stream info
redis-cli XINFO STREAM output:abc123

# Delete old streams
redis-cli DEL output:old-session-id
```

---

## End of Specification

This document provides a complete, production-ready specification for implementing Redis-based AI-to-AI communication in TeleClaude using a unified multi-adapter architecture.

**Next steps:**
1. Review and approve specification
2. Begin Phase 1 implementation
3. Deploy Redis instance
4. Test with 2+ computers
5. Roll out to production
