"""Unified client managing multiple adapters per session.

This module provides AdapterClient, which abstracts adapter complexity behind
a clean, unified interface for the daemon and MCP server.
"""

import asyncio
import os
from typing import TYPE_CHECKING, Awaitable, Callable, Literal, Optional, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.feature_flags import is_threaded_output_enabled
from teleclaude.core.models import (
    ChannelMetadata,
    CleanupTrigger,
    MessageMetadata,
    RedisTransportMetadata,
    TelegramAdapterMetadata,
)
from teleclaude.core.protocols import RemoteExecutionProtocol
from teleclaude.core.session_utils import get_display_title_for_session
from teleclaude.transport.redis_transport import RedisTransport

if TYPE_CHECKING:
    from teleclaude.core.events import AgentEventContext
    from teleclaude.core.models import Session
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)


_OUTPUT_SUMMARY_MIN_INTERVAL_S = 2.0
_OUTPUT_SUMMARY_IDLE_THRESHOLD_S = 2.0


class AdapterClient:
    """Unified interface for multi-adapter operations.

    Manages UI adapters (Telegram) and transport services (Redis), and provides
    a clean, boundary-agnostic API. Owns the lifecycle of registered components.

    Key responsibilities:
    - Component creation and registration
    - Component lifecycle management
    - Peer discovery aggregation from transports
    - (Future) Session-aware routing
    - (Future) Parallel broadcasting to multiple adapters
    """

    def __init__(self, task_registry: "TaskRegistry | None" = None) -> None:
        """Initialize AdapterClient with observer pattern.

        Args:
            task_registry: Optional TaskRegistry for tracking background tasks
        """
        self.task_registry = task_registry
        self.adapters: dict[str, BaseAdapter] = {}  # adapter_type -> adapter instance
        self.is_shutting_down = False
        # Direct handler for agent events (set by daemon, replaces event bus for AGENT_EVENT)
        self.agent_event_handler: Callable[["AgentEventContext"], Awaitable[None]] | None = None

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

    def _origin_ui_adapter(self, session: "Session") -> UiAdapter | None:
        if not session.last_input_origin:
            logger.error(
                "Session %s missing last_input_origin; broadcasting to all UI adapters",
                session.session_id[:8],
            )
            return None
        adapter = self.adapters.get(session.last_input_origin)
        return adapter if isinstance(adapter, UiAdapter) else None

    def _ui_adapters(self) -> list[tuple[str, UiAdapter]]:
        return [
            (adapter_type, adapter) for adapter_type, adapter in self.adapters.items() if isinstance(adapter, UiAdapter)
        ]

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """Send error feedback to all UI adapters, surfacing failures."""
        ui_adapters = self._ui_adapters()
        if not ui_adapters:
            logger.warning("No UI adapters available for error feedback (session %s)", session_id[:8])
            return

        results = await asyncio.gather(
            *[adapter.send_error_feedback(session_id, error_message) for _, adapter in ui_adapters],
            return_exceptions=True,
        )
        first_error: Exception | None = None
        for (adapter_type, _), result in zip(ui_adapters, results):
            if isinstance(result, Exception):
                logger.error(
                    "Error feedback failed for adapter %s session %s: %s",
                    adapter_type,
                    session_id[:8],
                    result,
                )
                if first_error is None:
                    first_error = result
        if first_error is not None:
            raise first_error

    async def _broadcast_to_ui_adapters(
        self,
        session: "Session",
        operation: str,
        task_factory: Callable[[UiAdapter, "Session"], Awaitable[object]],
    ) -> list[tuple[str, object]]:
        """Broadcast operation to all UI adapters (originless)."""
        ui_adapters = self._ui_adapters()
        adapter_tasks = [
            (adapter_type, self._run_ui_lane(session, adapter_type, adapter, task_factory))
            for adapter_type, adapter in ui_adapters
        ]

        if not adapter_tasks:
            logger.warning("No UI adapters available for %s (session %s)", operation, session.session_id[:8])
            return []

        results = await asyncio.gather(*[task for _, task in adapter_tasks], return_exceptions=True)
        output: list[tuple[str, object]] = []
        for (adapter_type, _), result in zip(adapter_tasks, results):
            output.append((adapter_type, result))

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
            logger.info("Started redis transport")

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
        session: "Session",
        operation: str,
        task_factory: Callable[[UiAdapter, "Session"], Awaitable[object]],
    ) -> None:
        """Broadcast operation to all UI observers (best-effort).

        Executes operation on all UI adapters except origin adapter.
        Failures are logged as warnings but do not raise exceptions.

        Args:
            session: Session object (contains last_input_origin)
            operation: Operation name for logging
            task_factory: Function that takes adapter and returns awaitable
        """
        # Fetch fresh origin from DB (session object may be stale)
        fresh_session = await db.get_session(session.session_id)
        last_input_origin = fresh_session.last_input_origin if fresh_session else session.last_input_origin

        observer_tasks: list[tuple[str, Awaitable[object]]] = []
        for adapter_type, adapter in self.adapters.items():
            if adapter_type == last_input_origin:
                continue
            if isinstance(adapter, UiAdapter):
                observer_tasks.append((adapter_type, self._run_ui_lane(session, adapter_type, adapter, task_factory)))

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
        broadcast: bool = True,
        **kwargs: object,
    ) -> object:
        """Route operation to origin UI adapter via _run_ui_lane, then broadcast to observers.

        ALL calls go through _run_ui_lane which guarantees ensure_channel runs,
        providing thread-gone resilience (topic deleted, channel missing, etc.).

        If no origin adapter, broadcasts to all UI adapters and returns first truthy result.
        If origin exists, calls origin via lane and broadcasts to observers (best-effort).

        Args:
            session: Session object
            method: Method name to call on adapters
            *args: Positional args to pass to method (after session)
            broadcast: If False, only send to origin (no observers). Default: True.
            **kwargs: Keyword args to pass to method

        Returns:
            First truthy result, or None if no truthy results
        """
        origin_ui = self._origin_ui_adapter(session)

        def make_task(adapter: UiAdapter, lane_session: "Session") -> Awaitable[object]:
            return cast(Awaitable[object], getattr(adapter, method)(lane_session, *args, **kwargs))

        if not origin_ui:
            results = await self._broadcast_to_ui_adapters(session, method, make_task)
            for _, result in results:
                if isinstance(result, Exception):
                    continue
                if result:  # first truthy wins
                    return result
            return None

        # Route origin through _run_ui_lane for ensure_channel resilience
        origin_type = session.last_input_origin or "unknown"
        result = await self._run_ui_lane(session, origin_type, origin_ui, make_task)

        # Broadcast to observers (best-effort) unless disabled
        if broadcast:
            await self._broadcast_to_observers(session, method, make_task)

        return result

    async def send_message(
        self,
        session: "Session",
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        cleanup_trigger: CleanupTrigger = CleanupTrigger.NEXT_NOTICE,
        ephemeral: bool = True,
        multi_message: bool = False,
    ) -> str | None:
        """Send message to ALL UiAdapters (origin + observers).

        Args:
            session: Session object (daemon already fetched it)
            text: Message text
            metadata: Adapter-specific metadata
            cleanup_trigger: When this message should be removed.
                - CleanupTrigger.NEXT_NOTICE: removed on next notice message
                - CleanupTrigger.NEXT_TURN: removed on next user turn
            ephemeral: If True (default), track message for deletion.
                      Use False for persistent content (agent output, MCP results).
            multi_message: If True, content is a multi-message payload needing quoting.

        Returns:
            message_id from origin adapter, or None if send failed
        """
        # Convert cleanup_trigger enum to feedback boolean (internal implementation)
        feedback = cleanup_trigger == CleanupTrigger.NEXT_NOTICE

        # Skip feedback for AI-to-AI sessions (listeners already deliver)
        if feedback and session.initiator_session_id:
            return None

        # Feedback mode: delete old feedback before sending new
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

        # Fetch fresh last_input_origin from DB (session object may be stale after origin update)
        fresh_session = await db.get_session(session.session_id)
        last_input_origin = fresh_session.last_input_origin if fresh_session else session.last_input_origin

        if last_input_origin:
            target = self.adapters.get(last_input_origin)
            if isinstance(target, UiAdapter):
                result = await target.send_message(session, text, metadata=metadata, multi_message=multi_message)
            else:
                logger.debug(
                    "Session %s last_input_origin=%s not available; broadcasting to all UI adapters",
                    session.session_id[:8],
                    last_input_origin,
                )
                result = await self._route_to_ui(
                    session, "send_message", text, broadcast=True, metadata=metadata, multi_message=multi_message
                )
        else:
            logger.debug(
                "Session %s missing last_input_origin; broadcasting to all UI adapters",
                session.session_id[:8],
            )
            result = await self._route_to_ui(
                session, "send_message", text, broadcast=True, metadata=metadata, multi_message=multi_message
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

    async def send_threaded_output(
        self,
        session: "Session",
        text: str,
        footer_text: str | None = None,
        multi_message: bool = False,
    ) -> str | None:
        """Send threaded output via UI adapters (edit if exists, else new).

        Always routes through _run_ui_lane to guarantee ensure_channel runs,
        which handles thread-gone resilience (topic deleted from Telegram, etc.).
        """
        result = await self._route_to_ui(
            session,
            "send_threaded_output",
            text,
            broadcast=False,
            footer_text=footer_text,
            multi_message=multi_message,
        )
        return str(result) if result else None

    async def send_threaded_footer(self, session: "Session", text: str) -> str | None:
        """Send threaded footer via UI adapters with adapter-local cleanup semantics."""
        if not is_threaded_output_enabled(session.active_agent):
            return None
        result = await self._route_to_ui(session, "send_threaded_footer", text)
        return str(result) if result else None

    async def edit_message(self, session: "Session", message_id: str, text: str) -> bool:
        """Edit message in ALL UiAdapters (origin + observers).

        Args:
            session: Session object
            message_id: Platform-specific message ID
            text: New message text

        Returns:
            True if origin edit succeeded
        """
        result = await self._route_to_ui(session, "edit_message", message_id, text)
        return bool(result)

    async def delete_message(self, session: "Session", message_id: str) -> bool:
        """Delete message in ALL UiAdapters (origin + observers).

        Args:
            session: Session object
            message_id: Platform-specific message ID

        Returns:
            True if origin deletion succeeded
        """
        result = await self._route_to_ui(session, "delete_message", message_id)
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
        result = await self._route_to_ui(session, "send_file", file_path, caption=caption)
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
        logger.debug(
            "[OUTPUT_ROUTE] send_output_update called: session=%s output_len=%d is_final=%s",
            session.session_id[:8],
            len(output),
            is_final,
        )

        # Check if threaded output experiment is enabled AND hooks have actually delivered output.
        # Only suppress standard poller when threaded output is active (output_message_id set),
        # otherwise fall through so the session isn't silenced when hooks don't fire.
        if is_threaded_output_enabled(session.active_agent):
            telegram_meta = getattr(session.adapter_metadata, "telegram", None)
            if telegram_meta and telegram_meta.output_message_id:
                logger.debug(
                    "[OUTPUT_ROUTE] Standard output suppressed for session %s (threaded output active)",
                    session.session_id[:8],
                )
                return await self.get_output_message_id(session.session_id)
            logger.debug(
                "[OUTPUT_ROUTE] Experiment active but no threaded output yet for session %s, falling through",
                session.session_id[:8],
            )

        def make_task(adapter: UiAdapter, lane_session: "Session") -> Awaitable[object]:
            return adapter.send_output_update(
                lane_session,
                output,
                started_at,
                last_output_changed_at,
                is_final,
                exit_code,
                render_markdown,
            )

        # Broadcast to ALL UI adapters (per-adapter lanes)
        tasks = [
            (adapter_type, self._run_ui_lane(session, adapter_type, adapter, make_task))
            for adapter_type, adapter in self.adapters.items()
            if isinstance(adapter, UiAdapter)
        ]

        logger.debug(
            "[OUTPUT_ROUTE] Found %d UI adapters: %s",
            len(tasks),
            [adapter_type for adapter_type, _ in tasks],
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
                logger.error(
                    "[OUTPUT_ROUTE] Adapter %s failed for session %s: %s",
                    adapter_type,
                    session.session_id[:8],
                    result,
                )
            elif isinstance(result, str) and not first_success:
                first_success = result
                logger.debug("[OUTPUT_ROUTE] Output update sent to %s: message_id=%s", adapter_type, result)
            elif result is None:
                logger.warning(
                    "[OUTPUT_ROUTE] Adapter %s returned None for session %s (likely ensure_channel failed)",
                    adapter_type,
                    session.session_id[:8],
                )

        if not first_success:
            logger.error(
                "[OUTPUT_ROUTE] NO ADAPTERS SUCCEEDED for session %s - output lost!",
                session.session_id[:8],
            )

        return first_success

    async def broadcast_user_input(
        self,
        session: "Session",
        text: str,
        origin: str,
    ) -> None:
        """Broadcast user input to observer UI adapters.

        Formats input with source attribution (e.g. "TUI @ macbook") and
        sends to all UI adapters except the origin via _broadcast_to_observers,
        which routes through _run_ui_lane for ensure_channel resilience.
        """
        from teleclaude.utils.markdown import escape_markdown_v2

        origin_display = "TUI" if origin.lower() == "api" else origin.upper()
        computer_name = config.computer.name
        header = f"{origin_display} @ {computer_name}:"

        escaped_header = escape_markdown_v2(header)
        escaped_text = escape_markdown_v2(text)
        final_text = f"*{escaped_header}*\n_{escaped_text}_"

        async def send_broadcast(ui_adapter: UiAdapter, lane_session: "Session") -> Optional[str]:
            return await ui_adapter.send_message(
                lane_session,
                final_text,
                metadata=MessageMetadata(parse_mode="MarkdownV2"),
            )

        await self._broadcast_to_observers(session, "broadcast_user_input", send_broadcast)

    async def _run_ui_lane(
        self,
        session: "Session",
        adapter_type: str,
        adapter: UiAdapter,
        task_factory: Callable[[UiAdapter, "Session"], Awaitable[object]],
    ) -> object | None:
        # Build display title for UI adapters (DB stores only description)
        display_title = await get_display_title_for_session(session)
        logger.debug(
            "[UI_LANE] Starting lane for adapter=%s session=%s title=%s",
            adapter_type,
            session.session_id[:8],
            display_title,
        )
        lane_session = session
        try:
            lane_session = await adapter.ensure_channel(lane_session, display_title)
            logger.debug(
                "[UI_LANE] ensure_channel succeeded for %s session %s",
                adapter_type,
                session.session_id[:8],
            )
        except Exception as exc:
            logger.error(
                "[UI_LANE] Failed to ensure UI channel for %s session %s: %s (BLOCKING OUTPUT)",
                adapter_type,
                session.session_id[:8],
                exc,
            )
            return None

        try:
            result = await task_factory(adapter, lane_session)
            logger.debug(
                "[UI_LANE] Task completed for %s session %s: result=%s",
                adapter_type,
                session.session_id[:8],
                type(result).__name__ if result else "None",
            )
            return result
        except Exception as exc:
            logger.error(
                "[UI_LANE] UI adapter %s failed in lane for session %s: %s",
                adapter_type,
                session.session_id[:8],
                exc,
            )
            return None

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

    async def _call_pre_handler(self, session: "Session", event: str, source_adapter: str | None = None) -> None:
        """Call source adapter's pre-handler for UI cleanup.

        Uses source adapter (where message came from) rather than origin adapter,
        so AI-to-AI sessions can still have UI cleanup on Telegram.
        """
        adapter_type = source_adapter or session.last_input_origin
        adapter = self.adapters.get(adapter_type)
        if not adapter or not isinstance(adapter, UiAdapter):
            return

        pre_handler = cast(Callable[[object], Awaitable[None]] | None, getattr(adapter, "_pre_handle_user_input", None))
        if not pre_handler or not callable(pre_handler):
            return

        await pre_handler(session)
        logger.debug("Pre-handler executed for %s on event %s", adapter_type, event)

    async def _call_post_handler(
        self, session: "Session", event: str, message_id: str, source_adapter: str | None = None
    ) -> None:
        """Call source adapter's post-handler for UI state tracking.

        Uses source adapter (where message came from) rather than origin adapter,
        so AI-to-AI sessions can still have UI state tracking on Telegram.
        """
        adapter_type = source_adapter or session.last_input_origin
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

    async def pre_handle_command(self, session: "Session", source_adapter: str | None = None) -> None:
        """Run UI pre-handler before executing a user command."""
        await self._call_pre_handler(session, "command", source_adapter)

    async def post_handle_command(self, session: "Session", message_id: str, source_adapter: str | None = None) -> None:
        """Run UI post-handler after executing a user command."""
        await self._call_post_handler(session, "command", message_id, source_adapter)

    async def broadcast_command_action(
        self,
        session: "Session",
        command_name: str,
        payload: dict[str, object],  # noqa: loose-dict - Command payload for observers
        source_adapter: str | None = None,
    ) -> None:
        """Broadcast user command actions to UI observer adapters."""
        command_payload = dict(payload)
        command_payload["command_name"] = command_name
        await self._broadcast_action(session, "command", command_payload, source_adapter)

    async def _broadcast_action(
        self,
        session: "Session",
        event: str,
        payload: dict[str, object],  # noqa: loose-dict - Event payload from/to adapters
        source_adapter: str | None = None,
    ) -> None:
        """Broadcast user actions to UI observer adapters.

        Skips both the origin adapter and the source adapter (where message came from)
        to prevent echoing messages back to the sender.
        """
        action_text = self._format_event_for_observers(event, payload)
        if not action_text:
            return

        for adapter_type, adapter in self.adapters.items():
            if adapter_type == session.last_input_origin:
                continue
            if adapter_type == source_adapter:
                continue
            if not isinstance(adapter, UiAdapter):
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

    def _format_event_for_observers(self, event: str, payload: dict[str, object]) -> Optional[str]:  # noqa: loose-dict - Event payload
        """Format event as human-readable text for observer adapters.

        Args:
            event: Event type
            payload: Event payload

        Returns:
            Formatted text or None if event should not be broadcast
        """
        command_name = None
        if event == "command":
            command_name = cast(str | None, payload.get("command_name"))

        if command_name == "send_message":
            text_obj = cast(str | None, payload.get("text"))
            return f"→ {str(text_obj)}" if text_obj else None

        if command_name == "cancel":
            return "→ [Ctrl+C]"

        elif command_name == "cancel2x":
            return "→ [Ctrl+C] [Ctrl+C]"

        elif command_name == "kill":
            return "→ [SIGKILL]"

        elif command_name == "ctrl":
            args_obj: object = payload.get("args", [])
            args: list[object] = args_obj if isinstance(args_obj, list) else []  # type: ignore[misc]
            key = str(args[0]) if args else "?"
            return f"→ [Ctrl+{key}]"

        elif command_name == "escape":
            return "→ [ESC]"

        elif command_name == "escape2x":
            return "→ [ESC] [ESC]"

        elif command_name == "create_session":
            title = cast(str, payload.get("title", "Untitled"))
            return f"→ [Created session: {title}]"

        # Don't broadcast internal coordination events
        return None

    async def create_channel(  # pylint: disable=too-many-locals
        self,
        session: "Session",
        title: str,
        last_input_origin: str,
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
            last_input_origin: Name of origin adapter (interactive)
            target_computer: Initiator computer name for AI-to-AI sessions (for stop event forwarding)

        Returns:
            channel_id from origin adapter

        Raises:
            ValueError: If origin adapter not found or channel creation failed
        """
        session_id = session.session_id

        channel_last_input_origin = last_input_origin
        if last_input_origin not in self.adapters:
            logger.debug("Origin %s not a registered adapter; treating as originless", last_input_origin)
            channel_last_input_origin = ""

        last_input_origin_instance = self.adapters.get(channel_last_input_origin)
        origin_requires_channel = isinstance(last_input_origin_instance, UiAdapter)

        tasks = []
        adapter_types = []
        for adapter_type, adapter in self.adapters.items():
            is_origin = bool(channel_last_input_origin) and adapter_type == channel_last_input_origin
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
            raise ValueError(f"Origin adapter {last_input_origin} not found or did not return channel_id")
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
    ) -> "Session":
        """Ensure UI channels exist for a session (originless)."""
        ui_adapters = self._ui_adapters()
        if not ui_adapters:
            raise ValueError("No UI adapters registered")

        tasks = [adapter.ensure_channel(session, title) for _, adapter in ui_adapters]
        try:
            await asyncio.gather(*tasks)
        except Exception as exc:
            logger.error("Failed to ensure UI channel(s): %s", exc)
            raise

        refreshed = await db.get_session(session.session_id)
        if not refreshed:
            raise ValueError(f"Session {session.session_id[:8]} missing after channel creation")
        return refreshed

    async def get_output_message_id(self, session_id: str) -> Optional[str]:
        """Get output message ID for session.

        Args:
            session_id: Session identifier

        Returns:
            Message ID of output message, or None if not set
        """
        return await db.get_output_message_id(session_id)

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
        target_computer: str | None = None,
    ) -> str:
        """Read single response from request (for ephemeral request/response).

        Used for one-shot requests like list_projects, get_computer_info.
        Reads the response in one go instead of streaming.

        Args:
            message_id: Stream entry ID from the original request
            timeout: Maximum time to wait for response (seconds, default 3.0)
            target_computer: Optional target computer for namespaced response stream

        Returns:
            Response data as string

        Raises:
            RuntimeError: If no transport adapter available
            TimeoutError: If no response received within timeout
        """
        transport = self._get_transport_adapter()
        return await transport.read_response(message_id, timeout, target_computer)

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
