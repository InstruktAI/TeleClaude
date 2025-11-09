"""Unified client managing multiple adapters per session.

This module provides AdapterClient, which abstracts adapter complexity behind
a clean, unified interface for the daemon and MCP server.
"""

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, List, Optional

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import EventType
from teleclaude.core.models import Session
from teleclaude.core.protocols import RemoteExecutionProtocol

logger = logging.getLogger(__name__)


class AdapterClient:
    """Unified interface for multi-adapter operations.

    Manages multiple adapters (Telegram, Redis, etc.) and provides a clean,
    adapter-agnostic API. Owns the complete adapter lifecycle.

    Key responsibilities:
    - Adapter creation and registration
    - Adapter lifecycle management
    - Peer discovery aggregation from all adapters
    - (Future) Session-aware routing
    - (Future) Parallel broadcasting to multiple adapters
    """

    def __init__(self) -> None:
        """Initialize AdapterClient with observer pattern.

        No daemon reference - uses observer pattern instead.
        Daemon subscribes to events via client.on(event, handler).
        """
        self._handlers: dict[EventType, Callable[[EventType, dict[str, object], dict[str, object]], object]] = {}
        self.adapters: dict[str, BaseAdapter] = {}  # adapter_type -> adapter instance

    def _load_adapters(self) -> None:
        """Load and initialize adapters from config."""
        # config already imported

        # Load Telegram adapter if configured (always loaded if bot token exists)
        if os.getenv("TELEGRAM_BOT_TOKEN"):
            telegram_adapter = TelegramAdapter(self)
            self.adapters["telegram"] = telegram_adapter
            logger.info("Loaded Telegram adapter")

        # Load Redis adapter if configured
        if config.redis.enabled:
            from teleclaude.adapters.redis_adapter import RedisAdapter

            redis_adapter = RedisAdapter(self)
            self.adapters["redis"] = redis_adapter
            logger.info("Loaded Redis adapter")

        # Validate at least one adapter is loaded
        if not self.adapters:
            raise ValueError("No adapters configured - check config.yml and .env")

        logger.info("Loaded %d adapter(s): %s", len(self.adapters), list(self.adapters.keys()))

    def register_adapter(self, adapter_type: str, adapter: BaseAdapter) -> None:
        """Manually register an adapter (for testing).

        Args:
            adapter_type: Adapter type name ('telegram', 'redis', etc.)
            adapter: Adapter instance implementing BaseAdapter
        """
        self.adapters[adapter_type] = adapter
        logger.info("Registered adapter: %s", adapter_type)

    async def start(self) -> None:
        """Start all registered adapters."""
        tasks = []
        for adapter_type, adapter in self.adapters.items():
            logger.info("Starting %s adapter...", adapter_type)
            tasks.append(adapter.start())

        # Start all adapters in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any failures
        for adapter_type, result in zip(self.adapters.keys(), results):
            if isinstance(result, Exception):
                logger.error("Failed to start %s adapter: %s", adapter_type, result)
            else:
                logger.info("%s adapter started", adapter_type)

    async def stop(self) -> None:
        """Stop all registered adapters."""
        tasks = []
        for adapter_type, adapter in self.adapters.items():
            logger.info("Stopping %s adapter...", adapter_type)
            tasks.append(adapter.stop())

        # Stop all adapters in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any failures
        for adapter_type, result in zip(self.adapters.keys(), results):
            if isinstance(result, Exception):
                logger.error("Failed to stop %s adapter: %s", adapter_type, result)
            else:
                logger.info("%s adapter stopped", adapter_type)

    async def send_message(self, session_id: str, text: str, metadata: Optional[dict[str, object]] = None) -> str:
        """Send message to origin adapter and broadcast to observers with UI.

        Origin/Observer Pattern:
        - Origin adapter: Interactive session (CRITICAL - failure throws exception)
        - Observer adapters: Read-only sessions with has_ui=True (OPTIONAL - failures logged)

        Args:
            session_id: Session identifier
            text: Message text
            metadata: Optional adapter-specific metadata

        Returns:
            message_id from origin adapter

        Raises:
            ValueError: If session or origin adapter not found
            Exception: If origin adapter send fails (critical)
        """

        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if not session.origin_adapter:
            raise ValueError(f"Session {session_id} has no origin adapter configured")

        # Get origin adapter
        origin_adapter = self.adapters.get(session.origin_adapter)
        if not origin_adapter:
            raise ValueError(f"Origin adapter {session.origin_adapter} not available")

        # Send to origin adapter (CRITICAL - let exceptions propagate)
        origin_message_id: str = await origin_adapter.send_message(session_id, text, metadata)
        logger.debug("Sent message to origin adapter %s for session %s", session.origin_adapter, session_id[:8])

        # Broadcast to observer adapters with has_ui=True (OPTIONAL - catch exceptions)
        observer_tasks = []
        for adapter_type, adapter in self.adapters.items():
            # Skip origin adapter (already sent)
            if adapter_type == session.origin_adapter:
                continue

            # Only send to adapters with UI (skip Redis, etc.)
            if not adapter.has_ui:
                continue

            observer_tasks.append((adapter_type, adapter.send_message(session_id, text, metadata)))

        if observer_tasks:
            # Execute observer sends in parallel
            results = await asyncio.gather(*[task for _, task in observer_tasks], return_exceptions=True)

            # Log observer failures (non-critical)
            for (adapter_type, _), result in zip(observer_tasks, results):
                if isinstance(result, Exception):
                    logger.warning(
                        "Observer adapter %s failed to send message for session %s: %s",
                        adapter_type,
                        session_id[:8],
                        result,
                    )
                else:
                    logger.debug("Sent message to observer adapter %s for session %s", adapter_type, session_id[:8])

        return origin_message_id

    async def edit_message(self, session_id: str, message_id: str, text: str) -> bool:
        """Edit message in origin adapter.

        Args:
            session_id: Session identifier
            message_id: Platform-specific message ID
            text: New message text

        Returns:
            True if edit succeeded, False otherwise

        Raises:
            ValueError: If session or origin adapter not found
        """

        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if not session.origin_adapter:
            raise ValueError(f"Session {session_id} has no origin adapter configured")

        # Get origin adapter
        origin_adapter = self.adapters.get(session.origin_adapter)
        if not origin_adapter:
            raise ValueError(f"Origin adapter {session.origin_adapter} not available")

        # Delegate to origin adapter
        result: bool = await origin_adapter.edit_message(session_id, message_id, text)
        return result

    async def delete_message(self, session_id: str, message_id: str) -> bool:
        """Delete message in origin adapter.

        Args:
            session_id: Session identifier
            message_id: Platform-specific message ID

        Returns:
            True if deletion succeeded, False otherwise

        Raises:
            ValueError: If session or origin adapter not found
        """

        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if not session.origin_adapter:
            raise ValueError(f"Session {session_id} has no origin adapter configured")

        # Get origin adapter
        origin_adapter = self.adapters.get(session.origin_adapter)
        if not origin_adapter:
            raise ValueError(f"Origin adapter {session.origin_adapter} not available")

        # Delegate to origin adapter
        result = await origin_adapter.delete_message(session_id, message_id)
        return bool(result)

    async def send_output_update(
        self,
        session_id: str,
        output: str,
        started_at: float,
        last_output_changed_at: float,
        is_final: bool = False,
        exit_code: Optional[int] = None,
    ) -> Optional[str]:
        """Send or edit output message in origin adapter (UI-specific).

        Routes to origin adapter's send_output_update() method.
        Only available for adapters with has_ui=True.

        Args:
            session_id: Session identifier
            output: Terminal output
            started_at: When process started (timestamp)
            last_output_changed_at: When output last changed (timestamp)
            is_final: Whether this is the final message (process completed)
            exit_code: Exit code if process completed

        Returns:
            Message ID from origin adapter, or None if failed

        Raises:
            ValueError: If session or origin adapter not found
            AttributeError: If origin adapter doesn't have send_output_update (not a UiAdapter)
        """
        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if not session.origin_adapter:
            raise ValueError(f"Session {session_id} has no origin adapter configured")

        # Get origin adapter
        origin_adapter = self.adapters.get(session.origin_adapter)
        if not origin_adapter:
            raise ValueError(f"Origin adapter {session.origin_adapter} not available")

        # Check if adapter is a UI adapter (type-safe check)
        if not isinstance(origin_adapter, UiAdapter):
            # Non-UI adapters (like Redis) don't support send_output_update
            # Return None silently (they handle output via send_message chunks)
            logger.debug(
                "Skipping send_output_update for session %s (origin adapter %s has no UI)",
                session_id[:8],
                session.origin_adapter,
            )
            return None

        # Type checker now knows this is UiAdapter
        result = await origin_adapter.send_output_update(
            session_id, output, started_at, last_output_changed_at, is_final, exit_code
        )
        return result

    async def send_exit_message(
        self,
        session_id: str,
        output: str,
        exit_text: str,
    ) -> None:
        """Send exit message in origin adapter (UI-specific).

        Routes to origin adapter's send_exit_message() method.
        Only available for adapters with has_ui=True.

        Args:
            session_id: Session identifier
            output: Terminal output
            exit_text: Exit message text

        Raises:
            ValueError: If session or origin adapter not found
            AttributeError: If origin adapter doesn't have send_exit_message (not a UiAdapter)
        """
        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if not session.origin_adapter:
            raise ValueError(f"Session {session_id} has no origin adapter configured")

        # Get origin adapter
        origin_adapter = self.adapters.get(session.origin_adapter)
        if not origin_adapter:
            raise ValueError(f"Origin adapter {session.origin_adapter} not available")

        # Check if adapter is a UI adapter (type-safe check)
        if not isinstance(origin_adapter, UiAdapter):
            raise AttributeError(
                f"send_exit_message requires UiAdapter, but {session.origin_adapter} "
                f"is {type(origin_adapter).__name__}"
            )

        # Type checker now knows this is UiAdapter
        await origin_adapter.send_exit_message(session_id, output, exit_text)

    async def update_channel_title(self, session_id: str, title: str) -> bool:
        """Update channel title in origin adapter.

        Args:
            session_id: Session identifier
            title: New channel title

        Returns:
            True if update succeeded, False otherwise

        Raises:
            ValueError: If session or origin adapter not found
        """

        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if not session.origin_adapter:
            raise ValueError(f"Session {session_id} has no origin adapter configured")

        # Get origin adapter
        origin_adapter = self.adapters.get(session.origin_adapter)
        if not origin_adapter:
            raise ValueError(f"Origin adapter {session.origin_adapter} not available")

        # Delegate to origin adapter
        result = await origin_adapter.update_channel_title(session_id, title)
        return bool(result)

    async def delete_channel(self, session_id: str) -> bool:
        """Delete channel in origin adapter.

        Args:
            session_id: Session identifier

        Returns:
            True if deletion succeeded, False otherwise

        Raises:
            ValueError: If session or origin adapter not found
        """

        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if not session.origin_adapter:
            raise ValueError(f"Session {session_id} has no origin adapter configured")

        # Get origin adapter
        origin_adapter = self.adapters.get(session.origin_adapter)
        if not origin_adapter:
            raise ValueError(f"Origin adapter {session.origin_adapter} not available")

        # Delegate to origin adapter
        result = await origin_adapter.delete_channel(session_id)
        return bool(result)

    async def discover_peers(self) -> list[dict[str, object]]:
        """Discover peers from all registered adapters.

        Aggregates peer lists from all adapters and deduplicates by name.
        First occurrence wins (primary adapter's data takes precedence).

        Returns:
            List of peer dicts with:
            - name: Computer name
            - status: "online" or "offline"
            - last_seen: datetime object
            - last_seen_ago: Human-readable string (e.g., "30s ago")
            - adapter_type: Which adapter discovered this peer
        """
        all_peers = []

        # Collect peers from all adapters
        for adapter_type, adapter in self.adapters.items():
            try:
                peers = await adapter.discover_peers()
                all_peers.extend(peers)
                logger.debug("Discovered %d peers from %s adapter", len(peers), adapter_type)
            except Exception as e:
                logger.error("Failed to discover peers from %s: %s", adapter_type, e)

        # Deduplicate by name (keep first occurrence = primary adapter wins)
        seen = set()
        unique_peers = []
        for peer in all_peers:
            peer_name = peer.get("name")
            if peer_name and peer_name not in seen:
                seen.add(peer_name)
                unique_peers.append(peer)

        logger.debug("Total discovered peers (deduplicated): %d", len(unique_peers))
        return unique_peers

    def on(
        self, event: EventType, handler: Callable[[EventType, dict[str, object], dict[str, object]], object]
    ) -> None:
        """Subscribe to event (daemon registers handlers here).

        Args:
            event: Event type to subscribe to
            handler: Async handler function(event, payload, metadata) -> object
        """
        self._handlers[event] = handler
        logger.debug("Registered handler for event: %s", event)

    async def handle_event(
        self,
        event: EventType,
        payload: dict[str, object],
        metadata: dict[str, object],
    ) -> object:
        """Called by adapters - does session lookup and emits to subscribers.

        Coordination layer responsibilities:
        1. Convert platform IDs (topic_id, etc.) to session_id
        2. Emit to registered handler (daemon)

        Args:
            event: Type-checked event name (from EventType literal)
            payload: Event payload data
            metadata: Event metadata (adapter_type, topic_id, user_id, etc.)

        Returns:
            Result from handler
        """

        # Cast metadata to dict for type-safe access
        metadata_typed = metadata  # Already dict[str, object]
        topic_id_obj = metadata_typed.get("topic_id")
        channel_id_obj = metadata_typed.get("channel_id")
        adapter_type_obj = metadata_typed.get("adapter_type")

        # Convert to strings for session lookup
        topic_id = str(topic_id_obj) if topic_id_obj else None
        channel_id = str(channel_id_obj) if channel_id_obj else None
        adapter_type = str(adapter_type_obj) if adapter_type_obj else None

        # Try to find session by platform metadata
        if topic_id and adapter_type:
            sessions = await db.get_sessions_by_adapter_metadata(adapter_type, "topic_id", topic_id)
            if sessions:
                payload["session_id"] = sessions[0].session_id
        elif channel_id and adapter_type:
            sessions = await db.get_sessions_by_adapter_metadata(adapter_type, "channel_id", channel_id)
            if sessions:
                payload["session_id"] = sessions[0].session_id

        # 2. Emit to subscriber
        logger.debug("handle_event called for event: %s, registered handlers: %s", event, list(self._handlers.keys()))
        handler = self._handlers.get(event)
        if handler:
            logger.debug("Found handler for event: %s, calling it now", event)
            handler_result = handler(event, payload, metadata)
            # Handler returns a coroutine that needs to be awaited
            result = await handler_result  # type: ignore[misc]  # Handler is callable returning awaitable
            logger.debug("Handler completed for event: %s", event)
            return result

        logger.warning("No handler registered for event: %s", event)
        return None

    async def create_channel(
        self,
        session_id: str,
        title: str,
        origin_adapter: str,
    ) -> str:
        """Create channels in ALL adapters for new session.

        Args:
            session_id: Session ID
            title: Channel title
            origin_adapter: Name of origin adapter (interactive)

        Returns:
            channel_id from origin adapter (for storing in adapter_metadata)

        Raises:
            ValueError: If origin adapter not found or channel creation failed
        """
        tasks = []
        adapter_types = []
        for adapter_type, adapter in self.adapters.items():
            is_origin = adapter_type == origin_adapter
            adapter_types.append((adapter_type, is_origin))
            tasks.append(
                adapter.create_channel(
                    session_id=session_id,
                    title=title,
                    metadata={
                        "origin": is_origin,
                        "origin_adapter": origin_adapter,
                    },
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        origin_channel_id = None
        for (adapter_type, is_origin), result in zip(adapter_types, results):
            if isinstance(result, Exception):
                logger.error("Failed to create channel in %s: %s", adapter_type, result)
                if is_origin:
                    raise ValueError(f"Failed to create channel in origin adapter {adapter_type}: {result}") from result
            else:
                logger.debug("Created channel in %s for session %s", adapter_type, session_id[:8])
                if is_origin:
                    origin_channel_id = result

        if not origin_channel_id:
            raise ValueError(f"Origin adapter {origin_adapter} not found or did not return channel_id")

        return str(origin_channel_id)

    async def send_general_message(
        self,
        adapter_type: str,
        text: str,
        metadata: Optional[dict[str, object]] = None,
    ) -> str:
        """Send message to general/default channel (not tied to specific session).

        Used for commands issued in general context, like /list-sessions.

        Args:
            adapter_type: Which adapter to use (from command context)
            text: Message text
            metadata: Platform-specific routing (message_thread_id, etc.)

        Returns:
            message_id from adapter

        Raises:
            ValueError: If adapter not found
        """
        adapter = self.adapters.get(adapter_type)
        if not adapter:
            raise ValueError(f"Adapter {adapter_type} not found")

        result: str = await adapter.send_general_message(text, metadata)
        return result

    # === Cross-Computer Orchestration (AI-to-AI) ===

    async def send_remote_command(
        self,
        computer_name: str,
        session_id: str,
        command: str,
        metadata: Optional[dict[str, object]] = None,
    ) -> str:
        """Send command to remote computer via transport adapter.

        Args:
            computer_name: Target computer identifier
            session_id: Session ID for the command
            command: Command to execute on remote computer
            metadata: Optional metadata for the command

        Returns:
            Request ID for tracking the command

        Raises:
            RuntimeError: If no transport adapter available
            Exception: If command send fails
        """
        transport = self._get_transport_adapter()
        return await transport.send_command_to_computer(computer_name, session_id, command, metadata)

    def poll_remote_output(
        self,
        session_id: str,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Stream output from remote session via transport adapter.

        Args:
            session_id: Session ID to poll output from
            timeout: Maximum time to wait for output (seconds)

        Yields:
            Output chunks from the remote session

        Raises:
            RuntimeError: If no transport adapter available
            TimeoutError: If no output received within timeout
        """
        transport = self._get_transport_adapter()
        return transport.poll_output_stream(session_id, timeout)

    async def discover_remote_computers(self) -> List[str]:
        """Discover remote computers via all transport adapters.

        Aggregates computer lists from all adapters implementing RemoteExecutionProtocol
        and deduplicates by computer name.

        Returns:
            List of computer names accessible via transport adapters

        Raises:
            RuntimeError: If no transport adapter available
        """
        computers: List[str] = []
        transport_count = 0

        for adapter in self.adapters.values():
            if isinstance(adapter, RemoteExecutionProtocol):
                transport_count += 1
                try:
                    discovered = await adapter.discover_computers()
                    computers.extend(discovered)
                    logger.debug("Discovered %d computers from transport adapter", len(discovered))
                except Exception as e:
                    logger.error("Failed to discover computers from transport adapter: %s", e)

        if transport_count == 0:
            raise RuntimeError("No transport adapter available for remote execution")

        # Deduplicate by name
        unique_computers = list(set(computers))
        logger.debug("Total discovered computers (deduplicated): %d", len(unique_computers))
        return unique_computers

    def _get_transport_adapter(self) -> RemoteExecutionProtocol:
        """Get first adapter that supports remote execution.

        Returns:
            Adapter implementing RemoteExecutionProtocol

        Raises:
            RuntimeError: If no transport adapter available
        """
        for adapter in self.adapters.values():
            if isinstance(adapter, RemoteExecutionProtocol):
                return adapter

        raise RuntimeError("No transport adapter available for remote execution")
