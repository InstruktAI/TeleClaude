"""Unified client managing multiple adapters per session.

This module provides AdapterClient, which abstracts adapter complexity behind
a clean, unified interface for the daemon and MCP server.
"""

import asyncio
import logging
import os
from typing import AsyncIterator, Callable, Optional

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import EventType, TeleClaudeEvents
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
        self._handlers: dict[EventType, Callable[[EventType, dict[str, object]], object]] = {}
        self.adapters: dict[str, BaseAdapter] = {}  # adapter_type -> adapter instance

    def _load_adapters(self) -> None:
        """Load and initialize adapters from config."""
        # config already imported

        # Load Telegram adapter if configured (always loaded if bot token exists)
        if os.getenv("TELEGRAM_BOT_TOKEN"):
            telegram_adapter = TelegramAdapter(self)
            self.adapters["telegram"] = telegram_adapter
            logger.info("Loaded Telegram adapter")

        # Load Redis adapter if configured (only instantiate when enabled)
        if config.redis.enabled:
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
        """Send message to origin adapter and broadcast to UI observer adapters.

        Origin/Observer Pattern:
        - Origin adapter: Interactive session (CRITICAL - failure throws exception)
        - Observer adapters: Read-only UI sessions (OPTIONAL - failures logged)

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

        # Broadcast to observer adapters (OPTIONAL - catch exceptions)
        observer_tasks = []
        for adapter_type, adapter in self.adapters.items():
            # Skip origin adapter (already sent)
            if adapter_type == session.origin_adapter:
                continue

            # UI adapters: always broadcast
            if isinstance(adapter, UiAdapter):
                observer_tasks.append((adapter_type, adapter.send_message(session_id, text, metadata)))
                continue

            # Redis adapter: only broadcast if session is observed
            if adapter_type == "redis":
                is_observed = await adapter.is_session_observed(session_id)  # type: ignore[attr-defined]
                if is_observed:
                    observer_tasks.append((adapter_type, adapter.send_message(session_id, text, metadata)))
                    logger.debug("Broadcasting to Redis (session %s is observed)", session_id[:8])
                continue

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

    async def send_file(
        self,
        session_id: str,
        file_path: str,
        caption: Optional[str] = None,
    ) -> str:
        """Send file to origin adapter only (no observer broadcasting).

        Used by MCP tools to upload files to the session's UI adapter.
        Unlike send_message(), files are NOT broadcast to observers -
        they only go to the origin adapter where the session is interactive.

        Args:
            session_id: Session identifier
            file_path: Absolute path to file
            caption: Optional file caption/description

        Returns:
            message_id from adapter

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

        # Send file to origin adapter only (no broadcasting)
        result: str = await origin_adapter.send_file(session_id, file_path, caption)
        logger.debug(
            "Sent file %s to origin adapter %s for session %s", file_path, session.origin_adapter, session_id[:8]
        )
        return result

    async def send_output_update(
        self,
        session_id: str,
        output: str,
        started_at: float,
        last_output_changed_at: float,
        is_final: bool = False,
        exit_code: Optional[int] = None,
    ) -> Optional[str]:
        """Broadcast output update to ALL UI adapters.

        Sends filtered output to all registered UiAdapters. Each adapter
        handles truncation and formatting based on its platform limits.

        Args:
            session_id: Session identifier
            output: Filtered terminal output (ANSI codes/markers already stripped)
            started_at: When process started (timestamp)
            last_output_changed_at: When output last changed (timestamp)
            is_final: Whether this is the final message (process completed)
            exit_code: Exit code if process completed

        Returns:
            Message ID from first successful adapter, or None if all failed

        Raises:
            ValueError: If session not found
        """
        session = await db.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Broadcast to ALL UI adapters
        tasks = []
        for adapter_type, adapter in self.adapters.items():
            if isinstance(adapter, UiAdapter):
                tasks.append(
                    (
                        adapter_type,
                        adapter.send_output_update(
                            session_id, output, started_at, last_output_changed_at, is_final, exit_code
                        ),
                    )
                )

        if not tasks:
            logger.warning("No UI adapters available for session %s", session_id[:8])
            return None

        # Execute all in parallel
        results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

        # Log failures and return first success
        first_success: Optional[str] = None
        for (adapter_type, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                logger.warning(
                    "UI adapter %s failed send_output_update for session %s: %s",
                    adapter_type,
                    session_id[:8],
                    result,
                )
            elif isinstance(result, str) and not first_success:
                first_success = result
                logger.debug("Sent output update via %s for session %s", adapter_type, session_id[:8])

        return first_success

    async def send_exit_message(
        self,
        session_id: str,
        output: str,
        exit_text: str,
    ) -> None:
        """Send exit message in origin adapter (UI-specific).

        Routes to origin adapter's send_exit_message() method.
        Only available for UI adapters (UiAdapter subclasses).

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

        # Get channel_id from session metadata
        if not session.adapter_metadata:
            raise ValueError(f"Session {session_id} has no adapter_metadata")

        channel_id = session.adapter_metadata.get("channel_id")
        if not channel_id:
            raise ValueError(f"Session {session_id} has no channel_id in adapter_metadata")

        # Delegate to origin adapter with channel_id
        result = await origin_adapter.update_channel_title(str(channel_id), title)
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
        logger.debug("AdapterClient.discover_peers() called, adapters: %s", list(self.adapters.keys()))
        all_peers = []

        # Collect peers from all adapters
        for adapter_type, adapter in self.adapters.items():
            logger.debug("Calling discover_peers() on %s adapter", adapter_type)
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

    def on(self, event: EventType, handler: Callable[[EventType, dict[str, object]], object]) -> None:
        """Subscribe to event (daemon registers handlers here).

        Args:
            event: Event type to subscribe to
            handler: Async handler function(event, context) -> object
                    NOTE: Signature changed to (event, context) - context contains all payload + metadata
        """
        self._handlers[event] = handler
        logger.debug("Registered handler for event: %s", event)

    async def handle_event(
        self,
        event: EventType,
        payload: dict[str, object],
        metadata: dict[str, object],
    ) -> object:
        """Called by adapters - orchestrates UI cleanup and handler dispatch.

        Coordination layer responsibilities:
        1. Convert platform IDs (topic_id, etc.) to session_id
        2. Build unified context dict (payload + metadata merged)
        3. Get session for origin adapter access
        4. [USER INPUT ONLY] Call origin adapter's pre-handler (UI cleanup)
        5. Dispatch to registered handler (daemon business logic)
        6. [USER INPUT ONLY] Call origin adapter's post-handler (UI state tracking)
        7. Broadcast user actions to observer adapters

        UI cleanup delegation (separation of concerns):
        - AdapterClient: Pure coordinator (no UI operations)
        - UI adapters: Own their UI cleanup logic (message deletion, etc.)
        - Transport adapters: No pre/post handlers (not UiAdapter instances)

        Args:
            event: Type-checked event name (from EventType literal)
            payload: Event payload data
            metadata: Event metadata (adapter_type, topic_id, user_id, etc.)

        Returns:
            Result from handler
        """

        # 1. Session lookup by platform metadata
        topic_id_obj = metadata.get("topic_id")
        channel_id_obj = metadata.get("channel_id")
        adapter_type_obj = metadata.get("adapter_type")

        topic_id = str(topic_id_obj) if topic_id_obj else None
        channel_id = str(channel_id_obj) if channel_id_obj else None
        adapter_type = str(adapter_type_obj) if adapter_type_obj else None

        if topic_id and adapter_type:
            sessions = await db.get_sessions_by_adapter_metadata(adapter_type, "topic_id", topic_id)
            if sessions:
                payload["session_id"] = sessions[0].session_id
        elif channel_id and adapter_type:
            sessions = await db.get_sessions_by_adapter_metadata(adapter_type, "channel_id", channel_id)
            if sessions:
                payload["session_id"] = sessions[0].session_id

        # 2. Build unified context (all data in one place)
        context: dict[str, object] = {
            **payload,  # All payload data
            **metadata,  # All metadata (overwrites if key collision)
        }
        session_id = context.get("session_id")
        message_id = context.get("message_id")

        # 3. Get session for origin adapter access (needed for pre/post handlers and broadcasting)
        session = None
        if session_id:
            session = await db.get_session(str(session_id))

        # 4. PRE: Call origin adapter's pre-handler for UI cleanup
        if session and message_id:
            origin_adapter = self.adapters.get(session.origin_adapter)
            if origin_adapter and isinstance(origin_adapter, UiAdapter):
                pre_handler = getattr(origin_adapter, "_pre_handle_user_input", None)
                if pre_handler and callable(pre_handler):
                    try:
                        await pre_handler(session.session_id)
                        logger.debug("Pre-handler executed for %s on event %s", session.origin_adapter, event)
                    except Exception as e:
                        logger.warning("Pre-handler failed for %s on %s: %s", session.origin_adapter, event, e)

        # 5. EXECUTE: Dispatch to registered handler with try-catch wrapper
        logger.debug("handle_event called for event: %s, registered handlers: %s", event, list(self._handlers.keys()))
        handler = self._handlers.get(event)
        if handler:
            try:
                logger.debug("Found handler for event: %s, calling it now", event)
                handler_result = handler(event, context)  # New signature: (event, context)
                result = await handler_result  # type: ignore[misc]  # Handler is callable returning awaitable
                logger.debug("Handler completed for event: %s", event)

                # Wrap success response in envelope
                response: dict[str, object] = {"status": "success", "data": result}

            except Exception as e:
                logger.error("Handler failed for event %s: %s", event, e, exc_info=True)
                response = {"status": "error", "error": str(e), "code": type(e).__name__}
                result = None  # No result data on error

            # 6. POST: Call origin adapter's post-handler for UI state tracking
            if session and message_id:
                origin_adapter = self.adapters.get(session.origin_adapter)
                if origin_adapter and isinstance(origin_adapter, UiAdapter):
                    post_handler = getattr(origin_adapter, "_post_handle_user_input", None)
                    if post_handler and callable(post_handler):
                        try:
                            await post_handler(session.session_id, str(message_id))
                            logger.debug("Post-handler executed for %s on event %s", session.origin_adapter, event)
                        except Exception as e:
                            logger.warning("Post-handler failed for %s on %s: %s", session.origin_adapter, event, e)

            # 7. Broadcast session lifecycle events to observer adapters (channel close/reopen)
            if session and event in ("session_closed", "session_reopened"):
                for adapter_type, adapter in self.adapters.items():
                    if adapter_type != session.origin_adapter:
                        try:
                            if event == "session_closed":
                                await adapter.close_channel(session.session_id)
                                logger.debug("Closed channel in observer adapter: %s", adapter_type)
                            elif event == "session_reopened":
                                await adapter.reopen_channel(session.session_id)
                                logger.debug("Reopened channel in observer adapter: %s", adapter_type)
                        except Exception as e:
                            logger.warning("Failed to %s channel in observer %s: %s", event, adapter_type, e)

            # 8. Broadcast ALL user actions to UI observer adapters (not just MESSAGE)
            if session:
                # Format event as human-readable action
                action_text = self._format_event_for_observers(event, payload)

                if action_text:
                    # Broadcast to UI observer adapters (not origin)
                    for adapter_type, adapter in self.adapters.items():
                        if adapter_type != session.origin_adapter and isinstance(adapter, UiAdapter):
                            try:
                                # Send copy of user action (best-effort, failures logged)
                                await adapter.send_message(
                                    session_id=session.session_id, text=action_text, metadata={"is_observer_echo": True}
                                )
                                logger.debug("Broadcasted %s to observer adapter: %s", event, adapter_type)
                            except Exception as e:
                                logger.warning("Failed to broadcast %s to observer %s: %s", event, adapter_type, e)

            return response

        logger.warning("No handler registered for event: %s", event)
        return {"status": "error", "error": f"No handler registered for event: {event}", "code": "NO_HANDLER"}

    def _format_event_for_observers(self, event: EventType, payload: dict[str, object]) -> Optional[str]:
        """Format event as human-readable text for observer adapters.

        Args:
            event: Event type
            payload: Event payload

        Returns:
            Formatted text or None if event should not be broadcast
        """
        if event == TeleClaudeEvents.MESSAGE:
            text_obj = payload.get("text")
            return f"→ {str(text_obj)}" if text_obj else None

        if event == TeleClaudeEvents.CANCEL:
            return "→ [Ctrl+C]"

        elif event == TeleClaudeEvents.CANCEL_2X:
            return "→ [Ctrl+C] [Ctrl+C]"

        elif event == TeleClaudeEvents.KILL:
            return "→ [SIGKILL]"

        elif event == TeleClaudeEvents.CTRL:
            args_obj = payload.get("args", [])
            args = args_obj if isinstance(args_obj, list) else []
            key = str(args[0]) if args else "?"
            return f"→ [Ctrl+{key}]"

        elif event == TeleClaudeEvents.ESCAPE:
            return "→ [ESC]"

        elif event == TeleClaudeEvents.ESCAPE_2X:
            return "→ [ESC] [ESC]"

        elif event == TeleClaudeEvents.NEW_SESSION:
            title = payload.get("title", "Untitled")
            return f"→ [Created session: {title}]"

        # Don't broadcast internal coordination events
        return None

    async def create_channel(
        self,
        session_id: str,
        title: str,
        origin_adapter: str,
    ) -> str:
        """Create channels in ALL adapters for new session.

        Stores each adapter's channel_id in session metadata to enable broadcasting.
        Each adapter creates its communication primitive:
        - UI adapters (Telegram): Create topics for user interaction
        - Transport adapters (Redis): Create streams for AI-to-AI communication

        Args:
            session_id: Session ID
            title: Channel title
            origin_adapter: Name of origin adapter (interactive)

        Returns:
            channel_id from origin adapter (for backward compatibility)

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

        # Collect ALL channel_ids (origin + observers)
        origin_channel_id = None
        all_channel_ids: dict[str, str] = {}

        for (adapter_type, is_origin), result in zip(adapter_types, results):
            if isinstance(result, Exception):
                logger.error("Failed to create channel in %s: %s", adapter_type, result)
                if is_origin:
                    raise ValueError(f"Failed to create channel in origin adapter {adapter_type}: {result}") from result
            else:
                channel_id = str(result)
                all_channel_ids[adapter_type] = channel_id
                logger.debug("Created channel in %s for session %s: %s", adapter_type, session_id[:8], channel_id)
                if is_origin:
                    origin_channel_id = channel_id

        if not origin_channel_id:
            raise ValueError(f"Origin adapter {origin_adapter} not found or did not return channel_id")

        # Store ALL adapter channel_ids in session metadata (enables observer broadcasting)
        session = await db.get_session(session_id)
        if session:
            metadata = session.adapter_metadata or {}
            metadata["channel_id"] = origin_channel_id  # Backward compatibility

            # Store each adapter's channel_id under namespaced key
            for adapter_type, channel_id in all_channel_ids.items():
                if adapter_type not in metadata:
                    metadata[adapter_type] = {}
                adapter_meta = metadata[adapter_type]
                if not isinstance(adapter_meta, dict):
                    adapter_meta = {}
                    metadata[adapter_type] = adapter_meta
                adapter_meta["channel_id"] = channel_id

            await db.update_session(session_id, adapter_metadata=metadata)
            logger.debug("Stored channel_ids for all adapters in session %s metadata", session_id[:8])

        return origin_channel_id

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

    # === Request/Response pattern for AI-to-AI communication ===

    async def send_request(
        self,
        computer_name: str,
        command: str,
        session_id: Optional[str] = None,
        metadata: Optional[dict[str, object]] = None,
    ) -> str:
        """Send request to remote computer via transport adapter.

        Transport layer generates request_id from Redis for correlation.

        Args:
            computer_name: Target computer identifier
            command: Command to send to remote computer
            session_id: Optional TeleClaude session ID (for session commands)
            metadata: Optional metadata (title, project_dir for session creation)

        Returns:
            Redis message ID (for response correlation via read_response)

        Raises:
            RuntimeError: If no transport adapter available
        """
        transport = self._get_transport_adapter()
        return await transport.send_request(computer_name, command, session_id, metadata)

    async def send_response(self, message_id: str, data: str) -> str:
        """Send response for an ephemeral request.

        Used by command handlers (list_projects, etc.) to respond without DB session.

        Args:
            message_id: Stream entry ID from the original request
            data: Response data (typically JSON)

        Returns:
            Stream entry ID of the response

        Raises:
            RuntimeError: If no transport adapter available
        """
        transport = self._get_transport_adapter()
        return await transport.send_response(message_id, data)

    async def read_response(
        self,
        message_id: str,
        timeout: float = 3.0,
    ) -> str:
        """Read single response from request (for ephemeral request/response).

        Used for one-shot requests like list_projects, get_computer_info.
        Reads the response in one go instead of streaming.

        Args:
            message_id: Stream entry ID from the original request
            timeout: Maximum time to wait for response (seconds, default 3.0)

        Returns:
            Response data as string

        Raises:
            RuntimeError: If no transport adapter available
            TimeoutError: If no response received within timeout
        """
        transport = self._get_transport_adapter()
        return await transport.read_response(message_id, timeout)

    async def stream_session_output(
        self,
        session_id: str,
        timeout: float = 2.0,
    ) -> AsyncIterator[str]:
        """Stream output from a tmux session (for continuous session streaming).

        Used for streaming real tmux session output in send_message, get_session_status, observe_session.
        Yields chunks of output as they arrive.

        Args:
            session_id: Session ID to stream output from
            timeout: Maximum time to wait for each chunk (seconds)

        Yields:
            Output chunks as strings

        Raises:
            RuntimeError: If no transport adapter available
        """
        transport = self._get_transport_adapter()
        async for chunk in transport.poll_output_stream(session_id, timeout):
            yield chunk

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
