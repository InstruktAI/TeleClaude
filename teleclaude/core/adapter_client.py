"""Unified client managing multiple adapters per session.

This module provides AdapterClient, which abstracts adapter complexity behind
a clean, unified interface for the daemon and MCP server.
"""

import asyncio
import logging
import os
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import (
    COMMAND_EVENTS,
    ClaudeEventContext,
    CommandEventContext,
    EventContext,
    EventType,
    FileEventContext,
    MessageEventContext,
    SessionLifecycleContext,
    SessionUpdatedContext,
    SystemCommandContext,
    TeleClaudeEvents,
    VoiceEventContext,
)
from teleclaude.core.models import (
    ChannelMetadata,
    MessageMetadata,
    RedisAdapterMetadata,
    TelegramAdapterMetadata,
)
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
        self._handlers: dict[EventType, Callable[[EventType, EventContext], Awaitable[object]]] = {}
        self.adapters: dict[str, BaseAdapter] = {}  # adapter_type -> adapter instance

    def register_adapter(self, adapter_type: str, adapter: BaseAdapter) -> None:
        """Manually register an adapter (for testing).

        Args:
            adapter_type: Adapter type name ('telegram', 'redis', etc.)
            adapter: Adapter instance implementing BaseAdapter
        """
        self.adapters[adapter_type] = adapter
        logger.info("Registered adapter: %s", adapter_type)

    async def start(self) -> None:
        """Start adapters and register ONLY successful ones.

        INVARIANT: self.adapters contains ONLY successfully started adapters.

        This eliminates ALL defensive checks because:
        - Adapter in registry → start() succeeded → internal state is valid
        - Metadata exists → contract guarantees it's valid
        - Trust the contract, let bugs fail fast

        Raises:
            Exception: If adapter start() fails (daemon crashes - this is intentional)
            ValueError: If no adapters started
        """
        # Telegram adapter
        if os.getenv("TELEGRAM_BOT_TOKEN"):
            telegram = TelegramAdapter(self)
            await telegram.start()  # Raises if fails → daemon crashes
            self.adapters["telegram"] = telegram  # Register ONLY after success
            logger.info("Started telegram adapter")

        # Redis adapter
        if config.redis.enabled:
            redis = RedisAdapter(self)
            await redis.start()  # Raises if fails → daemon crashes
            self.adapters["redis"] = redis  # Register ONLY after success
            logger.info("Started redis adapter")

        # Validate at least one adapter started
        if not self.adapters:
            raise ValueError("No adapters started - check config.yml and .env")

        logger.info("Started %d adapter(s): %s", len(self.adapters), list(self.adapters.keys()))

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

    async def _broadcast_to_observers(
        self,
        session: "Session",  # type: ignore[name-defined]
        operation: str,
        task_factory: Callable[[UiAdapter], Awaitable[Any]],
    ) -> None:
        """Broadcast operation to all UI observers (best-effort).

        Executes operation on all UI adapters except origin adapter.
        Failures are logged as warnings but do not raise exceptions.

        Args:
            session: Session object (contains origin_adapter)
            operation: Operation name for logging
            task_factory: Function that takes adapter and returns awaitable
        """
        observer_tasks = []
        for adapter_type, adapter in self.adapters.items():
            if adapter_type == session.origin_adapter:
                continue
            if isinstance(adapter, UiAdapter):
                observer_tasks.append((adapter_type, task_factory(adapter)))

        if observer_tasks:
            results = await asyncio.gather(*[task for _, task in observer_tasks], return_exceptions=True)

            for (adapter_type, _), result in zip(observer_tasks, results):
                if isinstance(result, Exception):
                    logger.warning(
                        "Observer %s failed %s for session %s: %s",
                        adapter_type,
                        operation,
                        session.session_id[:8],
                        result,
                    )
                else:
                    logger.debug(
                        "Observer %s completed %s for session %s", adapter_type, operation, session.session_id[:8]
                    )

    async def send_message(self, session: "Session", text: str, metadata: MessageMetadata) -> str:  # type: ignore[name-defined]
        """Send message to ALL UiAdapters (origin + observers).

        Args:
            session: Session object (daemon already fetched it)
            text: Message text
            metadata: Adapter-specific metadata

        Returns:
            message_id from origin adapter
        """
        origin_adapter = self.adapters[session.origin_adapter]

        # Send to origin adapter (CRITICAL - let exceptions propagate)
        origin_message_id: str = await origin_adapter.send_message(session, text, metadata)
        logger.debug("Sent message to origin adapter %s for session %s", session.origin_adapter, session.session_id[:8])

        # Broadcast to UI observers (best-effort)
        await self._broadcast_to_observers(
            session, "send_message", lambda adapter: adapter.send_message(session, text, metadata)
        )

        return origin_message_id

    async def send_feedback(
        self,
        session: "Session",  # type: ignore[name-defined]
        message: str,
        metadata: MessageMetadata,
        persistent: bool = False,
    ) -> Optional[str]:
        """Send feedback message via origin adapter ONLY (ephemeral UI notification).

        Feedback goes to origin adapter only - NOT broadcast to observers.

        Args:
            session: Session object
            message: Feedback message text
            metadata: Adapter-specific metadata
            persistent: If True, message won't be cleaned up on next feedback

        Returns:
            message_id if sent (UI adapter), None if transport adapter
        """
        origin_adapter = self.adapters[session.origin_adapter]
        message_id = await origin_adapter.send_feedback(session, message, metadata, persistent=persistent)

        if message_id:
            logger.debug("Sent feedback via %s for session %s", session.origin_adapter, session.session_id[:8])

        return message_id

    async def edit_message(self, session: "Session", message_id: str, text: str) -> bool:  # type: ignore[name-defined]
        """Edit message in ALL UiAdapters (origin + observers).

        Args:
            session: Session object
            message_id: Platform-specific message ID
            text: New message text

        Returns:
            True if origin edit succeeded
        """
        origin_adapter = self.adapters[session.origin_adapter]

        # Edit in origin adapter (CRITICAL)
        result: bool = await origin_adapter.edit_message(session, message_id, text, MessageMetadata())

        # Broadcast edit to UI observers (best-effort)
        await self._broadcast_to_observers(
            session, "edit_message", lambda adapter: adapter.edit_message(session, message_id, text, MessageMetadata())
        )

        return result

    async def delete_message(self, session: "Session", message_id: str) -> bool:  # type: ignore[name-defined]
        """Delete message in ALL UiAdapters (origin + observers).

        Args:
            session: Session object
            message_id: Platform-specific message ID

        Returns:
            True if origin deletion succeeded
        """
        origin_adapter = self.adapters[session.origin_adapter]

        # Delete in origin adapter (CRITICAL)
        result = await origin_adapter.delete_message(session, message_id)

        # Broadcast delete to UI observers (best-effort)
        await self._broadcast_to_observers(
            session, "delete_message", lambda adapter: adapter.delete_message(session, message_id)
        )

        return bool(result)

    async def send_file(
        self,
        session: "Session",  # type: ignore[name-defined]
        file_path: str,
        caption: Optional[str] = None,
    ) -> str:
        """Send file to origin adapter ONLY (not broadcast).

        Args:
            session: Session object
            file_path: Absolute path to file
            caption: Optional file caption/description

        Returns:
            message_id from origin adapter
        """
        origin_adapter = self.adapters[session.origin_adapter]
        result: str = await origin_adapter.send_file(session, file_path, MessageMetadata(), caption)
        logger.debug(
            "Sent file %s to origin adapter %s for session %s",
            file_path,
            session.origin_adapter,
            session.session_id[:8],
        )
        return result

    async def send_output_update(
        self,
        session: "Session",  # type: ignore[name-defined]
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
            session: Session object
            output: Filtered terminal output (ANSI codes/markers already stripped)
            started_at: When process started (timestamp)
            last_output_changed_at: When output last changed (timestamp)
            is_final: Whether this is the final message (process completed)
            exit_code: Exit code if process completed

        Returns:
            Message ID from first successful adapter, or None if all failed
        """
        # Broadcast to ALL UI adapters
        tasks = []
        for adapter_type, adapter in self.adapters.items():
            if isinstance(adapter, UiAdapter):
                tasks.append(
                    (
                        adapter_type,
                        adapter.send_output_update(
                            session, output, started_at, last_output_changed_at, is_final, exit_code
                        ),
                    )
                )

        if not tasks:
            logger.warning("No UI adapters available for session %s", session.session_id[:8])
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
                    session.session_id[:8],
                    result,
                )
            elif isinstance(result, str) and not first_success:
                first_success = result
                logger.debug("Sent output update via %s for session %s", adapter_type, session.session_id[:8])

        return first_success

    async def send_exit_message(
        self,
        session: "Session",  # type: ignore[name-defined]
        output: str,
        exit_text: str,
    ) -> None:
        """Send exit message in origin adapter (UI-specific).

        Routes to origin adapter's send_exit_message() method.
        Only available for UI adapters (UiAdapter subclasses).

        Args:
            session: Session object
            output: Terminal output
            exit_text: Exit message text

        Raises:
            ValueError: If origin adapter not found
            AttributeError: If origin adapter doesn't have send_exit_message (not a UiAdapter)
        """

        if not session.origin_adapter:
            raise ValueError(f"Session {session.session_id} has no origin adapter configured")

        # Get origin adapter (trust invariant: adapter in registry = started successfully)
        origin_adapter = self.adapters[session.origin_adapter]

        # Check if adapter is a UI adapter (type-safe check)
        if not isinstance(origin_adapter, UiAdapter):
            raise AttributeError(
                f"send_exit_message requires UiAdapter, but {session.origin_adapter} "
                f"is {type(origin_adapter).__name__}"
            )

        # Type checker now knows this is UiAdapter
        await origin_adapter.send_exit_message(session, output, exit_text)

    async def update_channel_title(self, session: "Session", title: str) -> bool:  # type: ignore[name-defined]
        """Broadcast channel title update to ALL adapters.

        Args:
            session: Session object (caller already fetched it)
            title: New channel title

        Returns:
            True if origin update succeeded
        """
        # Trust invariant: adapter in registry = started successfully
        origin_adapter = self.adapters[session.origin_adapter]

        # Update origin adapter (CRITICAL - let exceptions propagate)
        result = await origin_adapter.update_channel_title(session, title)

        # Broadcast to observer adapters (best-effort)
        await self._broadcast_to_observers(
            session, "update_channel_title", lambda adapter: adapter.update_channel_title(session, title)
        )

        return result

    async def delete_channel(self, session: "Session") -> bool:  # type: ignore[name-defined]
        """Broadcast channel deletion to ALL adapters.

        Args:
            session: Session object (caller already fetched it)

        Returns:
            True if origin deletion succeeded
        """
        # Trust invariant: adapter in registry = started successfully
        origin_adapter = self.adapters[session.origin_adapter]

        # Delete in origin adapter (CRITICAL)
        result = await origin_adapter.delete_channel(session)

        # Broadcast to observer adapters (best-effort)
        await self._broadcast_to_observers(session, "delete_channel", lambda adapter: adapter.delete_channel(session))

        return bool(result)

    async def discover_peers(self) -> list[dict[str, Any]]:  # type: ignore[explicit-any]  # JSON/API data with dynamic structure
        """Discover peers from all registered adapters.

        Aggregates peer lists from all adapters and deduplicates by name.
        First occurrence wins (primary adapter's data takes precedence).

        Returns:
            List of peer dicts (converted from PeerInfo dataclass) with:
            - name: Computer name
            - status: "online" or "offline"
            - last_seen: datetime object
            - last_seen_ago: Human-readable string (e.g., "30s ago")
            - adapter_type: Which adapter discovered this peer
            - user: Username (optional)
            - host: Hostname (optional)
            - ip: IP address (optional)
        """
        logger.debug("AdapterClient.discover_peers() called, adapters: %s", list(self.adapters.keys()))
        all_peers: list[dict[str, Any]] = []  # type: ignore[explicit-any]  # JSON/API data

        # Collect peers from all adapters
        for adapter_type, adapter in self.adapters.items():
            logger.debug("Calling discover_peers() on %s adapter", adapter_type)
            try:
                peers = await adapter.discover_peers()  # Returns list[PeerInfo]
                # Convert PeerInfo dataclass to dict for backward compatibility
                for peer_info in peers:
                    peer_dict = {
                        "name": peer_info.name,
                        "status": peer_info.status,
                        "last_seen": peer_info.last_seen,
                        "adapter_type": peer_info.adapter_type,
                    }
                    if peer_info.user:
                        peer_dict["user"] = peer_info.user
                    if peer_info.host:
                        peer_dict["host"] = peer_info.host
                    if peer_info.ip:
                        peer_dict["ip"] = peer_info.ip
                    all_peers.append(peer_dict)
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

    def on(self, event: EventType, handler: Callable[[EventType, EventContext], Awaitable[object]]) -> None:
        """Subscribe to event (daemon registers handlers here).

        Args:
            event: Event type to subscribe to
            handler: Async handler function(event, context) -> Awaitable[object]
                    context is a typed dataclass (CommandEventContext, MessageEventContext, etc.)
        """
        self._handlers[event] = handler
        logger.debug("Registered handler for event: %s", event)

    async def handle_event(
        self,
        event: EventType,
        payload: dict[str, Any],  # type: ignore[explicit-any]
        metadata: MessageMetadata,
    ) -> object:
        """Handle incoming event by dispatching to registered handler.

        Pure coordinator - delegates all concerns to private methods:
        1. Resolve session_id from platform metadata
        2. Build typed context for the event
        3. Call pre-handler (UI cleanup)
        4. Dispatch to registered handler
        5. Call post-handler (UI state tracking)
        6. Broadcast to observer adapters

        Args:
            event: Type-checked event name (from EventType literal)
            payload: Event payload data
            metadata: Event metadata (adapter_type, topic_id, user_id, etc.)

        Returns:
            Result envelope: {"status": "success", "data": ...} or {"status": "error", ...}
        """
        # 1. Resolve session_id from platform metadata (mutates payload)
        await self._resolve_session_id(payload, metadata)

        # 2. Build typed context
        session_id = payload.get("session_id")
        context = self._build_context(event, payload, metadata)

        # 3. Get session for adapter operations
        session = await db.get_session(str(session_id)) if session_id else None

        # 4. Pre-handler (UI cleanup before processing)
        message_id = payload.get("message_id")
        if session and message_id:
            await self._call_pre_handler(session, event)

        # 5. Dispatch to registered handler
        response = await self._dispatch(event, context)

        # 6. Post-handler (UI state tracking after processing)
        if session and message_id:
            await self._call_post_handler(session, event, str(message_id))

        # 7. Broadcast to observers (lifecycle events and user actions)
        if session:
            await self._broadcast_lifecycle(session, event)
            await self._broadcast_action(session, event, payload)

        return response

    async def _resolve_session_id(
        self,
        payload: dict[str, Any],  # type: ignore[explicit-any]
        metadata: MessageMetadata,
    ) -> None:
        """Resolve session_id from platform metadata (topic_id or channel_id).

        Mutates payload in-place to add session_id if found.
        """
        topic_id = metadata.message_thread_id
        channel_id = metadata.channel_id
        adapter_type = metadata.adapter_type

        if topic_id and adapter_type:
            sessions = await db.get_sessions_by_adapter_metadata(adapter_type, "topic_id", topic_id)
            if sessions:
                payload["session_id"] = sessions[0].session_id
        elif channel_id and adapter_type:
            sessions = await db.get_sessions_by_adapter_metadata(adapter_type, "channel_id", channel_id)
            if sessions:
                payload["session_id"] = sessions[0].session_id

    def _build_context(
        self,
        event: EventType,
        payload: dict[str, Any],  # type: ignore[explicit-any]
        metadata: MessageMetadata,
    ) -> EventContext:
        """Build typed context dataclass based on event type."""
        session_id = str(payload.get("session_id"))

        context_builders: dict[str, Callable[[], EventContext]] = {
            TeleClaudeEvents.CLAUDE_EVENT: lambda: ClaudeEventContext(
                session_id=session_id,
                event_type=payload.get("event_type"),
                data=payload.get("data"),
            ),
            TeleClaudeEvents.SESSION_UPDATED: lambda: SessionUpdatedContext(
                session_id=session_id,
                updated_fields=payload.get("updated_fields"),
            ),
            TeleClaudeEvents.MESSAGE: lambda: MessageEventContext(
                session_id=session_id,
                text=payload.get("text"),
            ),
            TeleClaudeEvents.VOICE: lambda: VoiceEventContext(
                session_id=session_id,
                file_path=payload.get("file_path"),
            ),
            TeleClaudeEvents.FILE: lambda: FileEventContext(
                session_id=session_id,
                file_path=payload.get("file_path"),
                filename=payload.get("filename"),
            ),
            TeleClaudeEvents.SESSION_CLOSED: lambda: SessionLifecycleContext(session_id=session_id),
            TeleClaudeEvents.SESSION_REOPENED: lambda: SessionLifecycleContext(session_id=session_id),
            TeleClaudeEvents.SYSTEM_COMMAND: lambda: SystemCommandContext(
                command=payload.get("command"),
                from_computer=payload.get("from_computer"),
            ),
        }

        # Check specific event first
        if event in context_builders:
            return context_builders[event]()

        # Command events share the same context type
        if event in COMMAND_EVENTS:
            return CommandEventContext(
                session_id=session_id,
                args=payload.get("args"),
                adapter_type=metadata.adapter_type,
                message_thread_id=metadata.message_thread_id,
                title=metadata.title,
                project_dir=metadata.project_dir,
                channel_metadata=metadata.channel_metadata,
                auto_command=metadata.auto_command,
            )

        # Fallback - should not happen with EventType literal
        logger.warning("Unknown event type %s, using empty CommandEventContext", event)
        return CommandEventContext(session_id=session_id, args=payload.get("args"))

    async def _call_pre_handler(self, session: "Session", event: EventType) -> None:  # type: ignore[name-defined]
        """Call origin adapter's pre-handler for UI cleanup."""
        origin_adapter = self.adapters.get(session.origin_adapter)
        if not origin_adapter or not isinstance(origin_adapter, UiAdapter):
            return

        pre_handler = getattr(origin_adapter, "_pre_handle_user_input", None)
        if not pre_handler or not callable(pre_handler):
            return

        try:
            await pre_handler(session)
            logger.debug("Pre-handler executed for %s on event %s", session.origin_adapter, event)
        except Exception as e:
            logger.warning("Pre-handler failed for %s on %s: %s", session.origin_adapter, event, e)

    async def _dispatch(self, event: EventType, context: EventContext) -> dict[str, object]:
        """Dispatch event to registered handler."""
        logger.debug("Dispatching event: %s, handlers: %s", event, list(self._handlers.keys()))

        handler = self._handlers.get(event)
        if not handler:
            logger.warning("No handler registered for event: %s", event)
            return {"status": "error", "error": f"No handler registered for event: {event}", "code": "NO_HANDLER"}

        try:
            logger.debug("Calling handler for event: %s", event)
            result = await handler(event, context)
            logger.debug("Handler completed for event: %s", event)
            return {"status": "success", "data": result}
        except Exception as e:
            logger.error("Handler failed for event %s: %s", event, e, exc_info=True)
            return {"status": "error", "error": str(e), "code": type(e).__name__}

    async def _call_post_handler(self, session: "Session", event: EventType, message_id: str) -> None:  # type: ignore[name-defined]
        """Call origin adapter's post-handler for UI state tracking."""
        origin_adapter = self.adapters.get(session.origin_adapter)
        if not origin_adapter or not isinstance(origin_adapter, UiAdapter):
            return

        post_handler = getattr(origin_adapter, "_post_handle_user_input", None)
        if not post_handler or not callable(post_handler):
            return

        try:
            await post_handler(session, message_id)
            logger.debug("Post-handler executed for %s on event %s", session.origin_adapter, event)
        except Exception as e:
            logger.warning("Post-handler failed for %s on %s: %s", session.origin_adapter, event, e)

    async def _broadcast_lifecycle(self, session: "Session", event: EventType) -> None:  # type: ignore[name-defined]
        """Broadcast session lifecycle events (close/reopen) to observer adapters."""
        if event not in (TeleClaudeEvents.SESSION_CLOSED, TeleClaudeEvents.SESSION_REOPENED):
            return

        for adapter_type, adapter in self.adapters.items():
            if adapter_type == session.origin_adapter:
                continue

            try:
                if event == TeleClaudeEvents.SESSION_CLOSED:
                    await adapter.close_channel(session)
                    logger.debug("Closed channel in observer adapter: %s", adapter_type)
                else:
                    await adapter.reopen_channel(session)
                    logger.debug("Reopened channel in observer adapter: %s", adapter_type)
            except Exception as e:
                logger.warning("Failed to %s channel in observer %s: %s", event, adapter_type, e)

    async def _broadcast_action(
        self,
        session: "Session",  # type: ignore[name-defined]
        event: EventType,
        payload: dict[str, Any],  # type: ignore[explicit-any]
    ) -> None:
        """Broadcast user actions to UI observer adapters."""
        action_text = self._format_event_for_observers(event, payload)
        if not action_text:
            return

        for adapter_type, adapter in self.adapters.items():
            if adapter_type == session.origin_adapter:
                continue
            if not isinstance(adapter, UiAdapter):
                continue

            try:
                await adapter.send_message(
                    session_id=session.session_id,
                    text=action_text,
                    metadata=MessageMetadata(),
                )
                logger.debug("Broadcasted %s to observer adapter: %s", event, adapter_type)
            except Exception as e:
                logger.warning("Failed to broadcast %s to observer %s: %s", event, adapter_type, e)

    def _format_event_for_observers(self, event: EventType, payload: dict[str, Any]) -> Optional[str]:  # type: ignore[explicit-any]  # JSON/API data with dynamic structure
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
        session: "Session",  # type: ignore[name-defined]
        title: str,
        origin_adapter: str,
    ) -> str:
        """Create channels in ALL adapters for new session.

        Stores each adapter's channel_id in session metadata to enable broadcasting.
        Each adapter creates its communication primitive:
        - UI adapters (Telegram): Create topics for user interaction
        - Transport adapters (Redis): Create streams for AI-to-AI communication

        Args:
            session: Session object (caller already has it)
            title: Channel title
            origin_adapter: Name of origin adapter (interactive)

        Returns:
            channel_id from origin adapter (for backward compatibility)

        Raises:
            ValueError: If origin adapter not found or channel creation failed
        """
        session_id = session.session_id

        tasks = []
        adapter_types = []
        for adapter_type, adapter in self.adapters.items():
            is_origin = adapter_type == origin_adapter
            adapter_types.append((adapter_type, is_origin))
            tasks.append(
                adapter.create_channel(
                    session,
                    title,
                    metadata=ChannelMetadata(origin=is_origin),
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
            # Store each adapter's channel_id in its namespace
            for adapter_type, channel_id in all_channel_ids.items():
                adapter_meta = getattr(session.adapter_metadata, adapter_type, None)
                if not adapter_meta:
                    if adapter_type == "telegram":
                        adapter_meta = TelegramAdapterMetadata()
                    elif adapter_type == "redis":
                        adapter_meta = RedisAdapterMetadata()
                    else:
                        continue
                    setattr(session.adapter_metadata, adapter_type, adapter_meta)

                # Store channel_id - telegram uses topic_id, redis uses channel_id
                if adapter_type == "telegram":
                    adapter_meta.topic_id = int(channel_id)
                elif adapter_type == "redis":
                    adapter_meta.channel_id = channel_id

            await db.update_session(session_id, adapter_metadata=session.adapter_metadata)
            logger.debug("Stored channel_ids for all adapters in session %s metadata", session_id[:8])

        return origin_channel_id

    async def send_general_message(
        self,
        adapter_type: str,
        text: str,
        metadata: MessageMetadata,
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
        metadata: MessageMetadata,
        session_id: Optional[str] = None,
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
        return await transport.send_request(computer_name, command, metadata, session_id)

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
