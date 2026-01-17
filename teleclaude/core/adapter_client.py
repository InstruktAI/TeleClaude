"""Unified client managing multiple adapters per session.

This module provides AdapterClient, which abstracts adapter complexity behind
a clean, unified interface for the daemon and MCP server.
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable, Literal, Optional, cast, overload

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.api_server import APIServer
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import (
    COMMAND_EVENTS,
    AgentEventContext,
    AgentEventPayload,
    AgentHookEvents,
    AgentHookEventType,
    AgentNotificationPayload,
    AgentPromptPayload,
    AgentSessionEndPayload,
    AgentSessionStartPayload,
    AgentStopPayload,
    CommandEventContext,
    CommandEventType,
    ErrorEventContext,
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
from teleclaude.core.models import ChannelMetadata, MessageMetadata, RedisTransportMetadata, TelegramAdapterMetadata
from teleclaude.core.protocols import RemoteExecutionProtocol
from teleclaude.transport.redis_transport import RedisTransport

if TYPE_CHECKING:
    from teleclaude.core.models import Session
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)
_OUTPUT_SUMMARY_MIN_INTERVAL_S = 2.0
_OUTPUT_SUMMARY_IDLE_THRESHOLD_S = 2.0

CommandEventHandler = Callable[[CommandEventType, CommandEventContext], Awaitable[object]]
MessageEventHandler = Callable[[Literal["message"], MessageEventContext], Awaitable[object]]
VoiceEventHandler = Callable[[Literal["voice"], VoiceEventContext], Awaitable[object]]
FileEventHandler = Callable[[Literal["file"], FileEventContext], Awaitable[object]]
SessionLifecycleEventHandler = Callable[
    [Literal["session_created", "session_removed"], SessionLifecycleContext], Awaitable[object]
]
SystemCommandEventHandler = Callable[[Literal["system_command"], SystemCommandContext], Awaitable[object]]
AgentEventHandler = Callable[[Literal["agent_event"], AgentEventContext], Awaitable[object]]
ErrorEventHandler = Callable[[Literal["error"], ErrorEventContext], Awaitable[object]]
SessionUpdatedEventHandler = Callable[[Literal["session_updated"], SessionUpdatedContext], Awaitable[object]]
GenericEventHandler = Callable[[EventType, EventContext], Awaitable[object]]

EventHandler = (
    CommandEventHandler
    | MessageEventHandler
    | VoiceEventHandler
    | FileEventHandler
    | SessionLifecycleEventHandler
    | SystemCommandEventHandler
    | AgentEventHandler
    | ErrorEventHandler
    | SessionUpdatedEventHandler
    | GenericEventHandler
)


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

    def __init__(self, task_registry: "TaskRegistry | None" = None) -> None:
        """Initialize AdapterClient with observer pattern.

        Args:
            task_registry: Optional TaskRegistry for tracking background tasks

        No daemon reference - uses observer pattern instead.
        Daemon subscribes to events via client.on(event, handler).
        """
        self.task_registry = task_registry
        self._handlers: dict[EventType, list[Callable[[EventType, EventContext], Awaitable[object]]]] = {}
        self.adapters: dict[str, BaseAdapter] = {}  # adapter_type -> adapter instance
        self.is_shutting_down = False

    def mark_shutting_down(self) -> None:
        """Mark client as shutting down to suppress adapter restarts."""
        self.is_shutting_down = True

    def register_adapter(self, adapter_type: str, adapter: BaseAdapter) -> None:
        """Manually register an adapter (for testing).

        Args:
            adapter_type: Adapter type name ('telegram', 'redis', etc.)
            adapter: Adapter instance implementing BaseAdapter
        """
        self.adapters[adapter_type] = adapter
        logger.info("Registered adapter: %s", adapter_type)

    @dataclass(frozen=True)
    class _UiDeliveryPlan:
        origin_type: str | None
        origin: UiAdapter | None
        observers: list[tuple[str, UiAdapter]]
        all_ui: list[tuple[str, UiAdapter]]

    def _ui_delivery_plan(self, session: "Session") -> "_UiDeliveryPlan":
        """Compute UI delivery plan once (origin + observers)."""
        all_ui = self._ui_adapters()
        origin_type = session.origin_adapter
        origin: UiAdapter | None = None
        observers: list[tuple[str, UiAdapter]] = []
        for adapter_type, adapter in all_ui:
            if adapter_type == origin_type:
                origin = adapter
            else:
                observers.append((adapter_type, adapter))
        return self._UiDeliveryPlan(
            origin_type=origin_type,
            origin=origin,
            observers=observers,
            all_ui=all_ui,
        )

    def _ui_broadcast_enabled(self) -> bool:
        """Return True when UI updates should broadcast to all UI adapters."""
        return config.ui_delivery.scope == "all_ui"

    def _ui_adapters(self) -> list[tuple[str, UiAdapter]]:
        return [
            (adapter_type, adapter) for adapter_type, adapter in self.adapters.items() if isinstance(adapter, UiAdapter)
        ]

    async def _broadcast_to_ui_adapters(
        self,
        session: "Session",
        operation: str,
        task_factory: Callable[[UiAdapter], Awaitable[object]],
    ) -> list[tuple[str, object]]:
        """Broadcast operation to all UI adapters (originless)."""
        ui_adapters = self._ui_adapters()
        adapter_tasks = [(adapter_type, task_factory(adapter)) for adapter_type, adapter in ui_adapters]

        if not adapter_tasks:
            logger.warning("No UI adapters available for %s (session %s)", operation, session.session_id[:8])
            return []

        results = await asyncio.gather(*[task for _, task in adapter_tasks], return_exceptions=True)
        output: list[tuple[str, object]] = []
        missing_thread_error: Optional[Exception] = None
        telegram_index: Optional[int] = None
        for index, ((adapter_type, _), result) in enumerate(zip(adapter_tasks, results)):
            if isinstance(result, Exception):
                logger.warning(
                    "UI adapter %s failed %s for session %s: %s",
                    adapter_type,
                    operation,
                    session.session_id[:8],
                    result,
                )
                if adapter_type == "telegram" and self._is_missing_thread_error(result):
                    missing_thread_error = result
                    telegram_index = index
            output.append((adapter_type, result))

        if missing_thread_error:
            updated_session = await self._handle_missing_telegram_thread(session, missing_thread_error)
            telegram_adapter = next(
                (adapter for adapter_type, adapter in ui_adapters if adapter_type == "telegram"),
                None,
            )
            if telegram_adapter:
                try:
                    if updated_session:
                        session.adapter_metadata = updated_session.adapter_metadata
                        session.title = updated_session.title
                    retry_result = await task_factory(telegram_adapter)
                    if telegram_index is not None:
                        output[telegram_index] = ("telegram", retry_result)
                    else:
                        output.append(("telegram", retry_result))
                except Exception as exc:
                    logger.warning(
                        "UI adapter telegram failed %s retry for session %s: %s",
                        operation,
                        session.session_id[:8],
                        exc,
                    )

        return output

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
        # API adapter (local HTTP API)
        api_server = APIServer(self, task_registry=self.task_registry)
        await api_server.start()
        self.adapters["api"] = api_server

        # Telegram adapter
        if os.getenv("TELEGRAM_BOT_TOKEN"):
            telegram = TelegramAdapter(self)
            await telegram.start()  # Raises if fails → daemon crashes
            self.adapters["telegram"] = telegram  # Register ONLY after success
            logger.info("Started telegram adapter")

        # Redis adapter
        if config.redis.enabled:
            redis = RedisTransport(self, task_registry=self.task_registry)
            await redis.start()  # Raises if fails → daemon crashes
            self.adapters["redis"] = redis  # Register ONLY after success
            logger.info("Started redis adapter")

        # Validate at least one adapter started
        if len(self.adapters) == 1 and "api" in self.adapters:
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
        session: "Session",
        observers: list[tuple[str, UiAdapter]],
        operation: str,
        task_factory: Callable[[UiAdapter], Awaitable[object]],
    ) -> None:
        """Broadcast operation to all UI observers (best-effort).

        Executes operation on all UI adapters except origin adapter.
        Failures are logged as warnings but do not raise exceptions.

        Args:
            session: Session object (contains origin_adapter)
            operation: Operation name for logging
            task_factory: Function that takes adapter and returns awaitable
        """
        observer_tasks: list[tuple[str, Awaitable[object]]] = [
            (adapter_type, task_factory(adapter)) for adapter_type, adapter in observers
        ]

        if operation == "delete_message":
            logger.debug(
                "Broadcast delete to observers: session=%s origin=%s observers=%s",
                session.session_id[:8],
                session.origin_adapter,
                [t for t, _ in observer_tasks],
            )

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

    async def _route_to_ui(
        self,
        session: "Session",
        method: str,
        *args: object,
        broadcast: Optional[bool] = None,
        **kwargs: object,
    ) -> object:
        """Route operation to origin UI adapter + broadcast to observers.

        If no origin adapter, broadcasts to all UI adapters and returns first truthy result.
        If origin exists, calls origin and broadcasts to observers (best-effort).

        Args:
            session: Session object
            method: Method name to call on adapters
            *args: Positional args to pass to method (after session)
            **kwargs: Keyword args to pass to method

        Returns:
            First truthy result, or None if no truthy results
        """
        plan = self._ui_delivery_plan(session)
        do_broadcast = self._ui_broadcast_enabled() if broadcast is None else broadcast

        def make_task(adapter: UiAdapter) -> Awaitable[object]:
            return cast(Awaitable[object], getattr(adapter, method)(session, *args, **kwargs))

        if not plan.origin:
            results = await self._broadcast_to_ui_adapters(session, method, make_task)
            for _, result in results:
                if isinstance(result, Exception):
                    continue
                if result:  # first truthy wins
                    return result
            return None

        # Call origin (let exceptions propagate)
        result = await cast(Awaitable[object], getattr(plan.origin, method)(session, *args, **kwargs))

        # Broadcast to observers (best-effort)
        if do_broadcast:
            await self._broadcast_to_observers(session, plan.observers, method, make_task)

        return result

    async def send_message(
        self,
        session: "Session",
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        ephemeral: bool = True,
        feedback: bool = False,
    ) -> str | None:
        """Send message to ALL UiAdapters (origin + observers).

        Args:
            session: Session object (daemon already fetched it)
            text: Message text
            metadata: Adapter-specific metadata
            ephemeral: If True (default), track message for deletion.
                      Use False for persistent content (agent output, MCP results).
            feedback: If True, delete old feedback before sending and track as feedback.
                     Feedback is cleaned when next feedback arrives.
                     If False (default), track for deletion on next user input.

        Returns:
            message_id from origin adapter, or None if send failed
        """
        plan = self._ui_delivery_plan(session)
        broadcast = self._ui_broadcast_enabled() and not feedback

        # Feedback mode: delete old feedback before sending new (origin only)
        if feedback:
            pending = await db.get_pending_deletions(session.session_id, deletion_type="feedback")
            if pending:
                logger.debug(
                    "Feedback cleanup: session=%s pending_count=%d",
                    session.session_id[:8],
                    len(pending),
                )
            deleted = 0
            failed = 0
            for msg_id in pending:
                try:
                    if plan.origin:
                        ok = await cast(Awaitable[object], plan.origin.delete_message(session, msg_id))
                    else:
                        ok = await self.delete_message(session, msg_id)
                    if ok:
                        deleted += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.debug("Best-effort feedback deletion failed: %s", e)
                    failed += 1
            if pending:
                logger.debug(
                    "Feedback cleanup result: session=%s deleted=%d failed=%d",
                    session.session_id[:8],
                    deleted,
                    failed,
                )
                await db.clear_pending_deletions(session.session_id, deletion_type="feedback")

        # Send message (origin-only for feedback; otherwise obey broadcast scope)
        result = await self._route_to_ui(
            session,
            "send_message",
            text,
            metadata=metadata,
            broadcast=broadcast,
        )
        message_id = str(result) if result else None

        # Track for deletion if ephemeral
        if ephemeral and message_id:
            deletion_type: Literal["user_input", "feedback"] = "feedback" if feedback else "user_input"
            await db.add_pending_deletion(session.session_id, message_id, deletion_type=deletion_type)
            if feedback:
                logger.debug(
                    "Feedback tracked for deletion: session=%s message_id=%s",
                    session.session_id[:8],
                    message_id,
                )

        return message_id

    async def edit_message(self, session: "Session", message_id: str, text: str) -> bool:
        """Edit message in ALL UiAdapters (origin + observers).

        Args:
            session: Session object
            message_id: Platform-specific message ID
            text: New message text

        Returns:
            True if origin edit succeeded
        """
        result = await self._route_to_ui(
            session,
            "edit_message",
            message_id,
            text,
            broadcast=self._ui_broadcast_enabled(),
        )
        return bool(result)

    async def delete_message(self, session: "Session", message_id: str) -> bool:
        """Delete message in ALL UiAdapters (origin + observers).

        Args:
            session: Session object
            message_id: Platform-specific message ID

        Returns:
            True if origin deletion succeeded
        """
        result = await self._route_to_ui(
            session,
            "delete_message",
            message_id,
            broadcast=self._ui_broadcast_enabled(),
        )
        return bool(result)

    async def send_file(
        self,
        session: "Session",
        file_path: str,
        *,
        caption: str | None = None,
    ) -> str:
        """Send file to ALL UiAdapters (origin + observers).

        Args:
            session: Session object
            file_path: Absolute path to file
            caption: Optional file caption/description

        Returns:
            message_id from origin adapter
        """
        result = await self._route_to_ui(
            session,
            "send_file",
            file_path,
            caption=caption,
            broadcast=self._ui_broadcast_enabled(),
        )
        return str(result) if result else ""

    async def send_output_update(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        session: "Session",
        output: str,
        started_at: float,
        last_output_changed_at: float,
        is_final: bool = False,
        exit_code: Optional[int] = None,
        render_markdown: bool = False,
    ) -> Optional[str]:
        """Broadcast output update to ALL UI adapters.

        Sends filtered output to all registered UiAdapters. Each adapter
        handles truncation and formatting based on its platform limits.

        Args:
            session: Session object
            output: Filtered tmux output (ANSI codes/markers already stripped)
            started_at: When process started (timestamp)
            last_output_changed_at: When output last changed (timestamp)
            is_final: Whether this is the final message (process completed)
            exit_code: Exit code if process completed
            render_markdown: If True, send output as Markdown (no code block wrapper)

        Returns:
            Message ID from first successful adapter, or None if all failed
        """
        session_to_send = session
        if self._needs_ui_channel(session):
            try:
                await self.ensure_ui_channels(session, session.title)
                refreshed = await db.get_session(session.session_id)
                if refreshed:
                    session_to_send = refreshed
            except Exception as exc:
                logger.warning(
                    "Failed to ensure UI channels for session %s: %s",
                    session.session_id[:8],
                    exc,
                )

        # Send output updates based on UI delivery scope
        plan = self._ui_delivery_plan(session_to_send)
        broadcast = self._ui_broadcast_enabled()
        if broadcast or not plan.origin:
            targets = plan.all_ui
        else:
            targets = [(plan.origin_type or "", plan.origin)]

        tasks: list[tuple[str, Awaitable[object]]] = []
        for adapter_type, adapter in targets:
            tasks.append(
                (
                    adapter_type,
                    adapter.send_output_update(
                        session_to_send,
                        output,
                        started_at,
                        last_output_changed_at,
                        is_final,
                        exit_code,
                        render_markdown,
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
        missing_thread_error: Optional[Exception] = None
        for (adapter_type, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                logger.warning(
                    "UI adapter %s failed send_output_update for session %s: %s",
                    adapter_type,
                    session_to_send.session_id[:8],
                    result,
                )
                if adapter_type == "telegram" and self._is_missing_thread_error(result):
                    missing_thread_error = result
            elif isinstance(result, str) and not first_success:
                first_success = result
                logger.debug("Output update sent", adapter=adapter_type, session=session_to_send.session_id[:8])

        if missing_thread_error:
            updated_session = await self._handle_missing_telegram_thread(session_to_send, missing_thread_error)
            telegram_adapter = self.adapters.get("telegram")
            if isinstance(telegram_adapter, UiAdapter):
                try:
                    retry_session = updated_session or session_to_send
                    retry_result = await telegram_adapter.send_output_update(
                        retry_session,
                        output,
                        started_at,
                        last_output_changed_at,
                        is_final,
                        exit_code,
                        render_markdown,
                    )
                    if isinstance(retry_result, str) and not first_success:
                        first_success = retry_result
                        logger.debug(
                            "Output update sent after topic recreation",
                            session=session_to_send.session_id[:8],
                        )
                except Exception as exc:
                    logger.warning(
                        "UI adapter telegram failed send_output_update retry for session %s: %s",
                        session_to_send.session_id[:8],
                        exc,
                    )

        return first_success

    @staticmethod
    def _summarize_output(output: str) -> str:
        """Summarize output for last_output display (single-line tail)."""
        text = output.strip()
        if not text:
            return ""
        lines = text.splitlines()
        for line in reversed(lines):
            if line.strip():
                return line.strip()[:200]
        return text[:200]

    def _needs_ui_channel(self, session: "Session") -> bool:
        telegram_adapter = self.adapters.get("telegram")
        if isinstance(telegram_adapter, UiAdapter):
            telegram_meta = session.adapter_metadata.telegram
            if not telegram_meta or not telegram_meta.topic_id:
                return True
        return False

    @staticmethod
    def _is_missing_thread_error(error: Exception) -> bool:
        error_text = str(error).lower()
        return (
            "message thread not found" in error_text or "topic_deleted" in error_text or "topic deleted" in error_text
        )

    async def _handle_missing_telegram_thread(self, session: "Session", error: Exception) -> "Session | None":
        current = await db.get_session(session.session_id)
        if not current:
            return None

        logger.warning(
            "Telegram topic missing for session %s; recreating (error: %s)",
            session.session_id[:8],
            error,
        )

        # Clear stale topic/message IDs so create_channel can rebuild.
        if current.adapter_metadata and current.adapter_metadata.telegram:
            current.adapter_metadata.telegram.topic_id = None
            current.adapter_metadata.telegram.output_message_id = None
            await db.update_session(current.session_id, adapter_metadata=current.adapter_metadata)

        try:
            await self.ensure_ui_channels(current, current.title)
        except Exception as exc:
            logger.warning(
                "Failed to recreate Telegram topic for session %s: %s",
                current.session_id[:8],
                exc,
            )
            return None
        return await db.get_session(current.session_id)

    async def send_exit_message(
        self,
        session: "Session",
        output: str,
        exit_text: str,
    ) -> None:
        """Send exit message to ALL UiAdapters (origin + observers).

        Args:
            session: Session object
            output: Tmux output
            exit_text: Exit message text
        """
        await self._route_to_ui(session, "send_exit_message", output, exit_text)

    async def update_channel_title(self, session: "Session", title: str) -> bool:
        """Broadcast channel title update to ALL adapters.

        Args:
            session: Session object (caller already fetched it)
            title: New channel title

        Returns:
            True if origin update succeeded
        """
        result = await self._route_to_ui(session, "update_channel_title", title)
        return bool(result)

    async def delete_channel(self, session: "Session") -> bool:
        """Broadcast channel deletion to ALL adapters.

        Args:
            session: Session object (caller already fetched it)

        Returns:
            True if origin deletion succeeded
        """
        result = await self._route_to_ui(session, "delete_channel")
        return bool(result)

    async def discover_peers(self, redis_enabled: bool | None = None) -> list[dict[str, object]]:  # noqa: loose-dict - Adapter peer data
        """Discover peers from all registered adapters.

        Aggregates peer lists from all adapters and deduplicates by name.
        First occurrence wins (primary adapter's data takes precedence).

        Args:
            redis_enabled: Whether Redis is enabled. Defaults to config.redis.enabled.

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

        # Determine Redis enabled state - explicit param takes precedence over config
        is_redis_enabled = redis_enabled if redis_enabled is not None else config.redis.enabled

        # Early return if Redis is disabled - no peer discovery without Redis
        if not is_redis_enabled:
            logger.debug("Redis disabled, skipping peer discovery")
            return []

        all_peers: list[dict[str, object]] = []  # noqa: loose-dict - Adapter peer data

        # Collect peers from all adapters
        for adapter_type, adapter in self.adapters.items():
            logger.debug("Calling discover_peers() on %s adapter", adapter_type)
            try:
                peers = await adapter.discover_peers()  # Returns list[PeerInfo]
                # Convert PeerInfo dataclass to dict for transport
                for peer_info in peers:
                    peer_dict: dict[str, object] = {  # noqa: loose-dict - Adapter peer data
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
                    if peer_info.role:
                        peer_dict["role"] = peer_info.role
                    if peer_info.system_stats:
                        peer_dict["system_stats"] = peer_info.system_stats
                    if peer_info.tmux_binary:
                        peer_dict["tmux_binary"] = peer_info.tmux_binary
                    all_peers.append(peer_dict)
                logger.debug("Discovered %d peers from %s adapter", len(peers), adapter_type)
            except Exception as e:
                logger.error("Failed to discover peers from %s: %s", adapter_type, e)

        # Deduplicate by name (keep first occurrence = primary adapter wins)
        seen: set[str] = set()
        unique_peers: list[dict[str, object]] = []  # noqa: loose-dict - Adapter peer data
        for peer in all_peers:
            peer_name = cast(str, peer.get("name"))
            if peer_name and peer_name not in seen:
                seen.add(peer_name)
                unique_peers.append(peer)

        logger.debug("Total discovered peers (deduplicated): %d", len(unique_peers))
        return unique_peers

    @overload
    def on(self, event: CommandEventType, handler: CommandEventHandler) -> None: ...

    @overload
    def on(self, event: Literal["message"], handler: MessageEventHandler) -> None: ...

    @overload
    def on(self, event: Literal["voice"], handler: VoiceEventHandler) -> None: ...

    @overload
    def on(self, event: Literal["file"], handler: FileEventHandler) -> None: ...

    @overload
    def on(self, event: Literal["session_created"], handler: SessionLifecycleEventHandler) -> None: ...

    @overload
    def on(self, event: Literal["session_removed"], handler: SessionLifecycleEventHandler) -> None: ...

    @overload
    def on(self, event: Literal["system_command"], handler: SystemCommandEventHandler) -> None: ...

    @overload
    def on(self, event: Literal["agent_event"], handler: AgentEventHandler) -> None: ...

    @overload
    def on(self, event: Literal["error"], handler: ErrorEventHandler) -> None: ...

    @overload
    def on(self, event: Literal["session_updated"], handler: SessionUpdatedEventHandler) -> None: ...

    @overload
    def on(self, event: EventType, handler: GenericEventHandler) -> None: ...

    def on(self, event: EventType, handler: EventHandler) -> None:
        """Subscribe to event (daemon registers handlers here).

        Args:
            event: Event type to subscribe to
            handler: Async handler function(event, context) -> Awaitable[object]
                    context is a typed dataclass (CommandEventContext, MessageEventContext, etc.)
        """
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(cast(Callable[[EventType, EventContext], Awaitable[object]], handler))
        logger.trace("Registered handler for event: %s (total: %d)", event, len(self._handlers[event]))

    async def handle_event(
        self,
        event: EventType,
        payload: dict[str, object],  # noqa: loose-dict - Event payload from/to adapters
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
        session_id = cast(str | None, payload.get("session_id"))
        context = self._build_context(event, payload, metadata)

        # 3. Get session for adapter operations
        session = await db.get_session(str(session_id)) if session_id else None

        # 3.5 Track last input adapter and message for routing feedback
        if session and metadata.adapter_type and metadata.adapter_type in self.adapters:
            if event in COMMAND_EVENTS or event in (
                TeleClaudeEvents.MESSAGE,
                TeleClaudeEvents.VOICE,
                TeleClaudeEvents.FILE,
            ):
                # Track adapter for routing
                await db.update_session(session.session_id, last_input_adapter=metadata.adapter_type)
                # Track last user input text for TUI display
                user_text = payload.get("text") or payload.get("command")
                if user_text is not None:
                    await db.update_session(
                        session.session_id,
                        last_message_sent=str(user_text)[:200],
                        last_message_sent_at=datetime.now(timezone.utc).isoformat(),
                    )

        # 4. Pre-handler (UI cleanup before processing)
        message_id = cast(str | None, payload.get("message_id"))
        logger.trace(
            "Pre-handler check: session=%s, message_id=%s, event=%s",
            session.session_id[:8] if session else None,
            message_id,
            event,
        )
        if session and message_id:
            await self._call_pre_handler(session, event, metadata.adapter_type)

        # 5. Dispatch to registered handler
        response = await self._dispatch(event, context)

        # 6. Post-handler (UI state tracking after processing)
        if session and message_id:
            await self._call_post_handler(session, event, str(message_id), metadata.adapter_type)

        # 7. Broadcast to observers (user actions)
        if session:
            await self._broadcast_action(session, event, payload, metadata.adapter_type)

        return response

    async def _resolve_session_id(
        self,
        payload: dict[str, object],  # noqa: loose-dict - Event payload from/to adapters
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
        payload: dict[str, object],  # noqa: loose-dict - Event payload from/to adapters
        metadata: MessageMetadata,
    ) -> EventContext:
        """Build typed context dataclass based on event type."""
        context_builders: dict[str, Callable[[], EventContext]] = {
            TeleClaudeEvents.AGENT_EVENT: lambda: AgentEventContext(
                session_id=str(payload["session_id"]),
                event_type=cast(AgentHookEventType, payload["event_type"]),
                data=self._build_agent_payload(
                    cast(AgentHookEventType, payload["event_type"]),
                    cast(dict[str, object], payload["data"]),  # noqa: loose-dict - Event data from adapter
                ),
            ),
            TeleClaudeEvents.SESSION_UPDATED: lambda: SessionUpdatedContext(
                session_id=str(payload.get("session_id")),
                updated_fields=cast(dict[str, object], payload.get("updated_fields", {})),  # noqa: loose-dict - Event fields
            ),
            TeleClaudeEvents.ERROR: lambda: ErrorEventContext(
                session_id=str(payload.get("session_id")),
                message=cast(str, payload.get("message", "")),
                source=cast(str | None, payload.get("source")),
                details=cast(dict[str, object] | None, payload.get("details")),  # noqa: loose-dict - Event detail boundary
            ),
            TeleClaudeEvents.MESSAGE: lambda: MessageEventContext(
                session_id=str(payload.get("session_id")),
                text=cast(str, payload.get("text", "")),
            ),
            TeleClaudeEvents.VOICE: lambda: VoiceEventContext(
                session_id=str(payload.get("session_id")),
                file_path=cast(str, payload.get("file_path", "")),
                message_id=cast(str | None, payload.get("message_id")),
                message_thread_id=cast(int | None, payload.get("message_thread_id")),
                adapter_type=metadata.adapter_type,
            ),
            TeleClaudeEvents.FILE: lambda: FileEventContext(
                session_id=str(payload.get("session_id")),
                file_path=cast(str, payload.get("file_path", "")),
                filename=cast(str, payload.get("filename", "")),
                caption=cast(str | None, payload.get("caption")),
                file_size=cast(int, payload.get("file_size", 0)),
            ),
            TeleClaudeEvents.SESSION_REMOVED: lambda: SessionLifecycleContext(
                session_id=str(payload.get("session_id"))
            ),
            TeleClaudeEvents.SESSION_CREATED: lambda: SessionLifecycleContext(
                session_id=str(payload.get("session_id"))
            ),
            TeleClaudeEvents.SYSTEM_COMMAND: lambda: SystemCommandContext(
                command=cast(str, payload.get("command", "")),
                from_computer=cast(str, payload.get("from_computer", "")),
            ),
        }

        # Check specific event first
        if event in context_builders:
            return context_builders[event]()

        # Command events share the same context type
        if event in COMMAND_EVENTS:
            return CommandEventContext(
                session_id=str(payload.get("session_id")),
                args=cast(list[str], payload.get("args", [])),
                adapter_type=metadata.adapter_type,
                message_thread_id=metadata.message_thread_id,
                title=metadata.title,
                project_path=metadata.project_path,
                channel_metadata=metadata.channel_metadata,
                auto_command=metadata.auto_command,
                launch_intent=metadata.launch_intent,
            )

        # Fallback - should not happen with EventType literal
        logger.warning("Unknown event type %s, using empty CommandEventContext", event)
        return CommandEventContext(
            session_id=str(payload.get("session_id")), args=cast(list[str], payload.get("args", []))
        )

    def _build_agent_payload(
        self,
        event_type: AgentHookEventType,
        data: dict[str, object],  # noqa: loose-dict - Event data to adapters
    ) -> AgentEventPayload:
        """Build typed agent payload from normalized hook data."""
        native_id = cast(str | None, data.get("session_id"))

        if event_type == AgentHookEvents.AGENT_SESSION_START:
            return AgentSessionStartPayload(
                session_id=native_id,
                transcript_path=cast(str | None, data.get("transcript_path")),
                raw=data,
            )

        if event_type == AgentHookEvents.AGENT_PROMPT:
            return AgentPromptPayload(
                session_id=native_id,
                transcript_path=cast(str | None, data.get("transcript_path")),
                prompt=cast(str, data.get("prompt", "")),
                raw=data,
                source_computer=cast(str | None, data.get("source_computer")),
            )

        if event_type == AgentHookEvents.AGENT_STOP:
            return AgentStopPayload(
                session_id=native_id,
                transcript_path=cast(str | None, data.get("transcript_path")),
                prompt=cast(str | None, data.get("prompt")),
                raw=data,
                summary=cast(str | None, data.get("summary")),
                title=cast(str | None, data.get("title")),
                source_computer=cast(str | None, data.get("source_computer")),
            )

        if event_type == AgentHookEvents.AGENT_NOTIFICATION:
            return AgentNotificationPayload(
                session_id=native_id,
                transcript_path=cast(str | None, data.get("transcript_path")),
                message=str(data.get("message", "")),
                raw=data,
            )

        if event_type == AgentHookEvents.AGENT_SESSION_END:
            return AgentSessionEndPayload(
                session_id=native_id,
                raw=data,
            )

        raise ValueError(f"Unknown agent hook event_type '{event_type}'")

        raise ValueError(f"Unknown agent hook event_type '{event_type}'")

    async def _call_pre_handler(self, session: "Session", event: EventType, source_adapter: str | None = None) -> None:
        """Call source adapter's pre-handler for UI cleanup.

        Uses source adapter (where message came from) rather than origin adapter,
        so AI-to-AI sessions can still have UI cleanup on Telegram.
        """
        plan = self._ui_delivery_plan(session)
        adapter_type = source_adapter or plan.origin_type
        adapter = self.adapters.get(adapter_type)
        if not adapter or not isinstance(adapter, UiAdapter):
            return

        pre_handler = cast(Callable[[object], Awaitable[None]] | None, getattr(adapter, "_pre_handle_user_input", None))
        if not pre_handler or not callable(pre_handler):
            return

        await pre_handler(session)
        logger.debug("Pre-handler executed for %s on event %s", adapter_type, event)

    async def _dispatch(self, event: EventType, context: EventContext) -> dict[str, object]:  # noqa: loose-dict - Event dispatch result
        """Dispatch event to registered handler(s)."""
        logger.trace("Dispatching event: %s, handlers registered: %s", event, event in self._handlers)

        handlers = self._handlers.get(event)
        if not handlers:
            logger.warning("No handler registered for event: %s", event)
            return {"status": "error", "error": f"No handler registered for event: {event}", "code": "NO_HANDLER"}

        # Execute all handlers in parallel
        tasks = [handler(event, context) for handler in handlers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_results: list[object] = []
        errors: list[Exception] = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Handler %d failed for event %s: %s", i, event, result, exc_info=True)
                errors.append(result)
            else:
                success_results.append(result)

        # If we have at least one success, consider it a success
        # Return the first non-None result (or just the first result if all are None)
        # This maintains backward compatibility for command handlers which return a value,
        # while allowing notification handlers (which return None) to coexist.
        if success_results:
            logger.debug(
                "Dispatch completed for event: %s (%d success, %d failed)", event, len(success_results), len(errors)
            )
            # meaningful_result = next((r for r in success_results if r is not None), success_results[0])
            # Actually, for commands there should ideally be only one handler returning a value.
            # We return the first one.
            return {"status": "success", "data": success_results[0]}

        # If all failed, raise the first error
        if errors:
            raise errors[0]

        # Should be unreachable if handlers list was not empty and we handled exceptions
        return {"status": "success", "data": None}

    async def _call_post_handler(
        self, session: "Session", event: EventType, message_id: str, source_adapter: str | None = None
    ) -> None:
        """Call source adapter's post-handler for UI state tracking.

        Uses source adapter (where message came from) rather than origin adapter,
        so AI-to-AI sessions can still have UI state tracking on Telegram.
        """
        plan = self._ui_delivery_plan(session)
        adapter_type = source_adapter or plan.origin_type
        adapter = self.adapters.get(adapter_type)
        if not adapter or not isinstance(adapter, UiAdapter):
            return

        post_handler = cast(
            Callable[[object, str], Awaitable[None]] | None, getattr(adapter, "_post_handle_user_input", None)
        )
        if not post_handler or not callable(post_handler):
            return

        await post_handler(session, message_id)
        logger.debug("Post-handler executed for %s on event %s", adapter_type, event)

    async def _broadcast_action(
        self,
        session: "Session",
        event: EventType,
        payload: dict[str, object],  # noqa: loose-dict - Event payload from/to adapters
        source_adapter: str | None = None,
    ) -> None:
        """Broadcast user actions to UI observer adapters.

        Skips both the origin adapter and the source adapter (where message came from)
        to prevent echoing messages back to the sender.
        """
        # User input echoing is disabled; edit/output updates already convey interaction.
        return

        action_text = self._format_event_for_observers(event, payload)
        if not action_text:
            return

        plan = self._ui_delivery_plan(session)
        for adapter_type, adapter in plan.observers:
            if adapter_type == source_adapter:
                continue

            try:
                await adapter.send_message(
                    session=session,
                    text=action_text,
                    metadata=MessageMetadata(),
                )
                logger.debug("Broadcasted %s to observer adapter: %s", event, adapter_type)
            except Exception as e:
                logger.warning("Failed to broadcast %s to observer %s: %s", event, adapter_type, e)

    def _format_event_for_observers(self, event: EventType, payload: dict[str, object]) -> Optional[str]:  # noqa: loose-dict - Event payload
        """Format event as human-readable text for observer adapters.

        Args:
            event: Event type
            payload: Event payload

        Returns:
            Formatted text or None if event should not be broadcast
        """
        if event == TeleClaudeEvents.MESSAGE:
            text_obj = cast(str | None, payload.get("text"))
            return f"→ {str(text_obj)}" if text_obj else None

        if event == TeleClaudeEvents.CANCEL:
            return "→ [Ctrl+C]"

        elif event == TeleClaudeEvents.CANCEL_2X:
            return "→ [Ctrl+C] [Ctrl+C]"

        elif event == TeleClaudeEvents.KILL:
            return "→ [SIGKILL]"

        elif event == TeleClaudeEvents.CTRL:
            args_obj: object = payload.get("args", [])
            args: list[object] = args_obj if isinstance(args_obj, list) else []  # type: ignore[misc]
            key = str(args[0]) if args else "?"
            return f"→ [Ctrl+{key}]"

        elif event == TeleClaudeEvents.ESCAPE:
            return "→ [ESC]"

        elif event == TeleClaudeEvents.ESCAPE_2X:
            return "→ [ESC] [ESC]"

        elif event == TeleClaudeEvents.NEW_SESSION:
            title = cast(str, payload.get("title", "Untitled"))
            return f"→ [Created session: {title}]"

        # Don't broadcast internal coordination events
        return None

    async def create_channel(  # pylint: disable=too-many-locals
        self,
        session: "Session",
        title: str,
        target_computer: Optional[str] = None,
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
            target_computer: Initiator computer name for AI-to-AI sessions (for stop event forwarding)

        Returns:
            channel_id from origin adapter

        Raises:
            ValueError: If origin adapter not found or channel creation failed
        """
        session_id = session.session_id

        plan = self._ui_delivery_plan(session)
        channel_origin_adapter = plan.origin_type
        if not channel_origin_adapter or channel_origin_adapter not in self.adapters:
            raise ValueError(f"Origin adapter {channel_origin_adapter} not found")

        origin_adapter_instance = self.adapters.get(channel_origin_adapter)
        origin_requires_channel = isinstance(origin_adapter_instance, UiAdapter)

        tasks = []
        adapter_types = []
        for adapter_type, adapter in self.adapters.items():
            is_origin = adapter_type == channel_origin_adapter
            adapter_types.append((adapter_type, is_origin))
            tasks.append(
                adapter.create_channel(
                    session,
                    title,
                    metadata=ChannelMetadata(origin=is_origin, target_computer=target_computer),
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

        if origin_requires_channel and not origin_channel_id:
            raise ValueError(f"Origin adapter {channel_origin_adapter} not found or did not return channel_id")
        if not origin_channel_id:
            origin_channel_id = ""

        # Store ALL adapter channel_ids in session metadata (enables observer broadcasting)
        updated_session = await db.get_session(session_id)
        if updated_session:
            # Store each adapter's channel_id in its namespace
            for adapter_type, channel_id in all_channel_ids.items():
                adapter_meta: object = getattr(updated_session.adapter_metadata, adapter_type, None)
                if not adapter_meta:
                    if adapter_type == "telegram":
                        adapter_meta = TelegramAdapterMetadata()
                    elif adapter_type == "redis":
                        adapter_meta = RedisTransportMetadata()
                    else:
                        continue
                    setattr(updated_session.adapter_metadata, adapter_type, adapter_meta)

                # Store channel_id - telegram uses topic_id, redis uses channel_id
                if adapter_type == "telegram" and isinstance(adapter_meta, TelegramAdapterMetadata):
                    adapter_meta.topic_id = int(channel_id)
                elif adapter_type == "redis" and isinstance(adapter_meta, RedisTransportMetadata):
                    adapter_meta.channel_id = channel_id

            await db.update_session(session_id, adapter_metadata=updated_session.adapter_metadata)
            logger.debug("Stored channel_ids for all adapters in session %s metadata", session_id[:8])

        return origin_channel_id

    async def ensure_ui_channels(
        self,
        session: "Session",
        title: str,
    ) -> None:
        """Ensure UI channels exist for a session (originless)."""
        ui_adapters = self._ui_adapters()
        if not ui_adapters:
            return

        pending: list[tuple[str, UiAdapter]] = []
        for adapter_type, adapter in ui_adapters:
            if adapter_type == "telegram":
                telegram_meta = session.adapter_metadata.telegram
                if telegram_meta and telegram_meta.topic_id:
                    continue
            pending.append((adapter_type, adapter))

        if not pending:
            return

        tasks = [
            adapter.create_channel(
                session,
                title,
                metadata=ChannelMetadata(origin=False),
            )
            for _, adapter in pending
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        channel_ids: dict[str, str] = {}
        for (adapter_type, _), result in zip(pending, results):
            if isinstance(result, Exception):
                logger.error("Failed to create UI channel in %s: %s", adapter_type, result)
                continue
            channel_ids[adapter_type] = str(result)

        if not channel_ids:
            return

        updated_session = await db.get_session(session.session_id)
        if not updated_session:
            return

        for adapter_type, channel_id in channel_ids.items():
            adapter_meta: object = getattr(updated_session.adapter_metadata, adapter_type, None)
            if not adapter_meta:
                if adapter_type == "telegram":
                    adapter_meta = TelegramAdapterMetadata()
                    setattr(updated_session.adapter_metadata, adapter_type, adapter_meta)
                else:
                    continue

            if adapter_type == "telegram" and isinstance(adapter_meta, TelegramAdapterMetadata):
                adapter_meta.topic_id = int(channel_id)

        await db.update_session(session.session_id, adapter_metadata=updated_session.adapter_metadata)

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

        result: str = await adapter.send_general_message(text, metadata=metadata)
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
            metadata: Optional metadata (title, project_path for session creation)

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
