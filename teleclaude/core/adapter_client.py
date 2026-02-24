"""Unified client managing multiple adapters per session.

This module provides AdapterClient, which abstracts adapter complexity behind
a clean, unified interface for the daemon and MCP server.
"""

import asyncio
import os
from typing import TYPE_CHECKING, Awaitable, Callable, Literal, Optional, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.discord_adapter import DiscordAdapter
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.models import (
    ChannelMetadata,
    CleanupTrigger,
    MessageMetadata,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.protocols import RemoteExecutionProtocol
from teleclaude.core.session_utils import get_display_title_for_session
from teleclaude.transport.redis_transport import RedisTransport

if TYPE_CHECKING:
    from teleclaude.core.agent_coordinator import AgentCoordinator
    from teleclaude.core.events import AgentEventContext
    from teleclaude.core.models import Session
    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)


_OUTPUT_SUMMARY_MIN_INTERVAL_S = 2.0
_OUTPUT_SUMMARY_IDLE_THRESHOLD_S = 2.0


class AdapterClient:
    """Unified interface for multi-adapter operations.

    Manages UI adapters (Telegram, Discord) and transport services (Redis),
    providing a clean, boundary-agnostic API. Owns the lifecycle of registered
    components.

    Routing model: all UI adapters receive output unconditionally. Channel
    provisioning (ensure_channel) determines which adapters participate —
    not the routing layer. The entry point (last_input_origin) is bookkeeping
    for response routing, not a routing decision.
    """

    def __init__(self, task_registry: "TaskRegistry | None" = None) -> None:
        """Initialize AdapterClient.

        Args:
            task_registry: Optional TaskRegistry for tracking background tasks
        """
        self.task_registry = task_registry
        self.adapters: dict[str, BaseAdapter] = {}  # adapter_type -> adapter instance
        self.is_shutting_down = False
        # Direct handler for agent events (set by daemon, replaces event bus for AGENT_EVENT)
        self.agent_event_handler: Callable[["AgentEventContext"], Awaitable[None]] | None = None
        self.agent_coordinator: "AgentCoordinator | None" = None
        # Per-session lock for channel provisioning (prevents concurrent ensure_channel races)
        self._channel_ensure_locks: dict[str, asyncio.Lock] = {}

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
        include_adapters: set[str] | None = None,
    ) -> list[tuple[str, object]]:
        """Send operation to all UI adapters sequentially.

        Serialized (not parallel) to prevent concurrent adapter_metadata blob
        writes from clobbering each other — each adapter reads the previous
        adapter's writes before persisting its own changes.
        """
        ui_adapters = self._ui_adapters()
        if include_adapters is not None:
            ui_adapters = [
                (adapter_type, adapter) for adapter_type, adapter in ui_adapters if adapter_type in include_adapters
            ]
        if not ui_adapters:
            logger.warning("No UI adapters available for %s (session %s)", operation, session.session_id[:8])
            return []

        output: list[tuple[str, object]] = []
        for adapter_type, adapter in ui_adapters:
            result = await self._run_ui_lane(session, adapter_type, adapter, task_factory)
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
        # Discord adapter (guard for tests that patch config with older/minimal objects)
        discord_cfg = getattr(config, "discord", None)
        if discord_cfg is not None and bool(getattr(discord_cfg, "enabled", False)):
            discord = DiscordAdapter(self, task_registry=self.task_registry)
            await discord.start()  # Raises if fails -> daemon crashes
            self.adapters["discord"] = discord  # Register ONLY after success
            logger.info("Started discord adapter")

        # Telegram adapter
        # Check for env token presence (adapter authenticates from env)
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

    async def _fanout_excluding(
        self,
        session: "Session",
        operation: str,
        task_factory: Callable[[UiAdapter, "Session"], Awaitable[object]],
        *,
        exclude: str | None = None,
    ) -> None:
        """Send operation to all UI adapters except one (best-effort).

        Used for echo prevention: when a user types in one adapter, broadcast
        the input to all other UI adapters without echoing it back to the source.

        Args:
            session: Session object
            operation: Operation name for logging
            task_factory: Function that takes adapter and returns awaitable
            exclude: Adapter type to skip. Uses session.last_input_origin if not provided.
        """
        skip = exclude or session.last_input_origin

        tasks: list[tuple[str, Awaitable[object]]] = []
        for adapter_type, adapter in self.adapters.items():
            if adapter_type == skip:
                continue
            if isinstance(adapter, UiAdapter):
                tasks.append((adapter_type, self._run_ui_lane(session, adapter_type, adapter, task_factory)))

        if tasks:
            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

            for (adapter_type, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    logger.warning(
                        "UI adapter %s failed %s for session %s: %s",
                        adapter_type,
                        operation,
                        session.session_id[:8],
                        result,
                    )
                else:
                    logger.debug(
                        "UI adapter %s completed %s for session %s", adapter_type, operation, session.session_id[:8]
                    )

    async def _route_to_ui(
        self,
        session: "Session",
        method: str,
        *args: object,
        include_adapters: set[str] | None = None,
        **kwargs: object,
    ) -> object:
        """Send operation to all UI adapters, returning the entry point result.

        All UI adapters receive the operation in parallel. The return value
        comes from the adapter matching session.last_input_origin (if it's a
        UI adapter), otherwise from the first successful adapter.

        Channel provisioning (ensure_channel) determines which adapters
        participate — not the routing layer.
        """
        session = await self.ensure_ui_channels(session)

        def make_task(adapter: UiAdapter, lane_session: "Session") -> Awaitable[object]:
            return cast(Awaitable[object], getattr(adapter, method)(lane_session, *args, **kwargs))

        entry_point = session.last_input_origin
        logger.debug(
            "[ROUTING] Fanout: session=%s method=%s entry_point=%s",
            session.session_id[:8],
            method,
            entry_point,
        )
        results = await self._broadcast_to_ui_adapters(session, method, make_task, include_adapters=include_adapters)

        # Prefer result from entry point adapter, fall back to first success
        entry_point_result: object = None
        first_result: object = None
        for adapter_type, result in results:
            if isinstance(result, (Exception, type(None))):
                continue
            if first_result is None:
                first_result = result
            if adapter_type == entry_point:
                entry_point_result = result

        return entry_point_result if entry_point_result is not None else first_result

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
        """Send message to all UI adapters.

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
            message_id from entry point adapter, or None if send failed
        """
        # Override cleanup_trigger if specified in metadata (e.g. from voice handler)
        if metadata and metadata.cleanup_trigger:
            try:
                cleanup_trigger = CleanupTrigger(metadata.cleanup_trigger)
            except ValueError:
                logger.warning("Invalid cleanup_trigger in metadata: %s", metadata.cleanup_trigger)

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
                    ok = await self.delete_message(
                        session,
                        msg_id,
                    )
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

        # Fetch fresh session from DB (session object may be stale after entry point update)
        fresh_session = await db.get_session(session.session_id)
        session_to_use = fresh_session or session

        # Notices are an origin UX path only.
        # If the origin is not a registered UI adapter, skip delivery.
        include_adapters: set[str] | None = None
        if feedback:
            origin_adapter = (session_to_use.last_input_origin or "").strip()
            origin_ui_adapter = self.adapters.get(origin_adapter)
            if isinstance(origin_ui_adapter, UiAdapter):
                include_adapters = {origin_adapter}
            else:
                logger.debug(
                    "Skipping notice with non-UI origin: session=%s origin=%s",
                    session_to_use.session_id[:8],
                    origin_adapter or "<none>",
                )
                return None

        # Route to chosen UI adapters (entry point result preferred)
        result = await self._route_to_ui(
            session_to_use,
            "send_message",
            text,
            metadata=metadata,
            multi_message=multi_message,
            include_adapters=include_adapters,
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

    async def move_badge_to_bottom(self, session: "Session") -> None:
        """Atomic-like move of the Session Badge to the absolute bottom on all UI adapters."""
        await self._broadcast_to_ui_adapters(session, "move_badge", lambda adapter, s: adapter._move_badge_to_bottom(s))

    async def break_threaded_turn(self, session: "Session") -> None:
        """Force a break in the threaded output stream on all UI adapters.

        Each adapter clears its own output_message_id and char_offset in its
        metadata namespace. Broadcast is serialized to prevent blob clobbering.
        """

        async def _reset_adapter_state(adapter: UiAdapter, s: "Session") -> None:
            await adapter._clear_output_message_id(s)
            await adapter._set_char_offset(s, 0)

        await self._broadcast_to_ui_adapters(session, "break_turn", _reset_adapter_state)

    async def send_threaded_output(
        self,
        session: "Session",
        text: str,
        multi_message: bool = False,
    ) -> str | None:
        """Send threaded output to all UI adapters (edit if exists, else new)."""
        # Cleanup feedback messages (like "Transcribed text...") when threaded output starts.
        pending = await db.get_pending_deletions(session.session_id, deletion_type="feedback")
        if pending:
            logger.debug(
                "Feedback cleanup (threaded output start): session=%s pending_count=%d",
                session.session_id[:8],
                len(pending),
            )
            for msg_id in pending:
                try:
                    await self.delete_message(
                        session,
                        msg_id,
                    )
                except Exception as e:
                    logger.debug("Best-effort feedback deletion failed: %s", e)
            await db.clear_pending_deletions(session.session_id, deletion_type="feedback")

        result = await self._route_to_ui(
            session,
            "send_threaded_output",
            text,
            multi_message=multi_message,
        )
        return str(result) if result else None

    async def edit_message(self, session: "Session", message_id: str, text: str) -> bool:
        """Edit message in all UI adapters.

        Args:
            session: Session object
            message_id: Platform-specific message ID
            text: New message text

        Returns:
            True if edit succeeded
        """
        result = await self._route_to_ui(session, "edit_message", message_id, text)
        return bool(result)

    async def delete_message(
        self,
        session: "Session",
        message_id: str,
    ) -> bool:
        """Delete message in all UI adapters.

        Args:
            session: Session object
            message_id: Platform-specific message ID

        Returns:
            True if deletion succeeded
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
        """Send file to all UI adapters.

        Args:
            session: Session object
            file_path: Absolute path to file
            caption: Optional file caption/description

        Returns:
            message_id from entry point adapter
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
        """Send output update to all UI adapters.

        Args:
            session: Session object
            output: Filtered tmux output (ANSI codes/markers already stripped)
            started_at: When process started (timestamp)
            last_output_changed_at: When output last changed (timestamp)
            is_final: Whether this is the final message (process completed)
            exit_code: Exit code if process completed
            render_markdown: If True, send output as Markdown (no code block wrapper)

        Returns:
            Message ID from entry point adapter, or None if failed
        """
        logger.debug(
            "[OUTPUT_ROUTE] send_output_update called: session=%s output_len=%d is_final=%s",
            session.session_id[:8],
            len(output),
            is_final,
        )

        # Cleanup feedback messages (like "Transcribed text...") when output starts.
        # This keeps the thread clean by removing intermediate status updates
        # once the real agent output begins.
        pending = await db.get_pending_deletions(session.session_id, deletion_type="feedback")
        if pending:
            logger.debug(
                "Feedback cleanup (output start): session=%s pending_count=%d",
                session.session_id[:8],
                len(pending),
            )
            for msg_id in pending:
                try:
                    await self.delete_message(
                        session,
                        msg_id,
                    )
                except Exception as e:
                    logger.debug("Best-effort feedback deletion failed: %s", e)
            await db.clear_pending_deletions(session.session_id, deletion_type="feedback")

        # Route to all UI adapters. Channel provisioning (ensure_channel)
        # determines which adapters participate (e.g., Telegram skips customer sessions).
        result = await self._route_to_ui(
            session,
            "send_output_update",
            output,
            started_at,
            last_output_changed_at,
            is_final,
            exit_code,
            render_markdown,
        )
        return str(result) if result else None

    async def broadcast_user_input(
        self,
        session: "Session",
        text: str,
        source: str,
        *,
        actor_id: str | None = None,
        actor_name: str | None = None,
        actor_avatar_url: str | None = None,
    ) -> None:
        """Reflect user input to all UI adapters except the source adapter.

        This keeps direct user experience local while fanning out for admin visibility.
        """
        default_actor = "TUI" if source.lower() in {InputOrigin.API.value, InputOrigin.HOOK.value} else source.upper()
        normalized_actor_name = (actor_name or "").strip() or (actor_id or "").strip() or default_actor
        fresh_session = await db.get_session(session.session_id)
        session_to_use = fresh_session or session
        final_text = f"{normalized_actor_name} @ {session_to_use.computer_name}:\n\n{text}"

        source_adapter = source.strip().lower()
        reflection_metadata = MessageMetadata(
            parse_mode=None,
            reflection_actor_id=(actor_id or "").strip() or None,
            reflection_actor_name=normalized_actor_name,
            reflection_actor_avatar_url=(actor_avatar_url or "").strip() or None,
        )

        def make_task(adapter: UiAdapter, lane_session: "Session") -> Awaitable[object]:
            return cast(
                Awaitable[object],
                adapter.send_message(
                    lane_session,
                    final_text,
                    metadata=reflection_metadata,
                ),
            )

        await self._fanout_excluding(
            session_to_use,
            "send_user_input_reflection",
            make_task,
            exclude=source_adapter,
        )

    async def _run_ui_lane(
        self,
        session: "Session",
        adapter_type: str,
        adapter: UiAdapter,
        task_factory: Callable[[UiAdapter, "Session"], Awaitable[object]],
    ) -> object | None:
        """Execute a task on a single UI adapter lane.

        Caller must provision channels via ensure_ui_channels() first.
        """
        display_title = await get_display_title_for_session(session)
        logger.debug(
            "[UI_LANE] Starting lane for adapter=%s session=%s",
            adapter_type,
            session.session_id[:8],
        )

        try:
            result = await task_factory(adapter, session)
            logger.debug(
                "[UI_LANE] Task completed for %s session %s: result=%s",
                adapter_type,
                session.session_id[:8],
                type(result).__name__ if result else "None",
            )
            return result
        except Exception as exc:
            try:
                return await adapter.recover_lane_error(session, exc, task_factory, display_title)
            except Exception:
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
        """Update channel title in all UI adapters.

        Args:
            session: Session object (caller already fetched it)
            title: New channel title

        Returns:
            True if update succeeded
        """
        result = await self._route_to_ui(session, "update_channel_title", title)
        return bool(result)

    async def delete_channel(self, session: "Session") -> bool:
        """Delete channel from all UI adapters.

        Does not provision channels — during teardown, never create channels
        just to delete them.

        Args:
            session: Session object (caller already fetched it)

        Returns:
            True if at least one deletion succeeded
        """

        def make_task(adapter: UiAdapter, lane_session: "Session") -> Awaitable[object]:
            return cast(Awaitable[object], adapter.delete_channel(lane_session))

        results = await self._broadcast_to_ui_adapters(session, "delete_channel", make_task)

        for _, result in results:
            if not isinstance(result, (Exception, type(None))) and result:
                return True
        return False

    async def discover_peers(
        self, redis_enabled: bool | None = None
    ) -> list[dict[str, object]]:  # guard: loose-dict - Adapter peer data
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

        all_peers: list[dict[str, object]] = []  # guard: loose-dict - Adapter peer data

        # Collect peers from all adapters
        for adapter_type, adapter in self.adapters.items():
            logger.debug("Calling discover_peers() on %s adapter", adapter_type)
            try:
                peers = await adapter.discover_peers()  # Returns list[PeerInfo]
                # Convert PeerInfo dataclass to dict for transport
                for peer_info in peers:
                    peer_dict: dict[str, object] = {  # guard: loose-dict - Adapter peer data
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
        unique_peers: list[dict[str, object]] = []  # guard: loose-dict - Adapter peer data
        for peer in all_peers:
            peer_name = cast(str, peer.get("name"))
            if peer_name and peer_name not in seen:
                seen.add(peer_name)
                unique_peers.append(peer)

        logger.debug("Total discovered peers (deduplicated): %d", len(unique_peers))
        return unique_peers

    async def _call_pre_handler(self, session: "Session", event: str, source_adapter: str | None = None) -> None:
        """Call source adapter's pre-handler for UI cleanup."""
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
        """Call source adapter's post-handler for UI state tracking."""
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
        payload: dict[str, object],  # guard: loose-dict - Command payload for UI adapters
        source_adapter: str | None = None,
    ) -> None:
        """Broadcast user command actions to other UI adapters (echo prevention)."""
        command_payload = dict(payload)
        command_payload["command_name"] = command_name
        await self._broadcast_action(session, "command", command_payload, source_adapter)

    async def _broadcast_action(
        self,
        session: "Session",
        event: str,
        payload: dict[str, object],  # guard: loose-dict - Event payload from/to adapters
        source_adapter: str | None = None,
    ) -> None:
        """Broadcast user actions to other UI adapters (echo prevention).

        Skips the entry point adapter and the source adapter to prevent
        echoing messages back to the sender.
        """
        action_text = self._format_event_text(event, payload)
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
                logger.debug("Broadcasted %s to UI adapter: %s", event, adapter_type)
            except Exception as e:
                logger.warning("Failed to broadcast %s to UI adapter %s: %s", event, adapter_type, e)

    def _format_event_text(
        self,
        event: str,
        payload: dict[str, object],  # guard: loose-dict - Event payload
    ) -> Optional[str]:
        """Format event as human-readable text for UI adapters.

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
        """Create channels in all adapters for new session.

        Each adapter creates its communication primitive:
        - UI adapters (Telegram, Discord): Create topics/threads for user interaction
        - Transport adapters (Redis): Record metadata for AI-to-AI communication

        Args:
            session: Session object (caller already has it)
            title: Channel title
            last_input_origin: Entry point identifier (which adapter/input initiated)
            target_computer: Initiator computer name for AI-to-AI sessions

        Returns:
            channel_id from entry point adapter (if UI), or empty string

        Raises:
            ValueError: If entry point is a UI adapter and channel creation failed
        """
        session_id = session.session_id

        entry_point = last_input_origin if last_input_origin in self.adapters else ""
        if not entry_point and last_input_origin:
            logger.debug("Entry point %s not a registered adapter; treating as non-adapter entry", last_input_origin)
        entry_point_is_ui = isinstance(self.adapters.get(entry_point), UiAdapter)

        tasks = []
        adapter_types = []
        for adapter_type, adapter in self.adapters.items():
            adapter_types.append(adapter_type)
            tasks.append(
                adapter.create_channel(
                    session,
                    title,
                    metadata=ChannelMetadata(target_computer=target_computer),
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        entry_point_channel_id = None
        all_channel_ids: dict[str, str] = {}

        for adapter_type, result in zip(adapter_types, results):
            if isinstance(result, Exception):
                logger.error("Failed to create channel in %s: %s", adapter_type, result)
                if adapter_type == entry_point:
                    raise ValueError(
                        f"Failed to create channel in entry point adapter {adapter_type}: {result}"
                    ) from result
            else:
                channel_id = str(result)
                all_channel_ids[adapter_type] = channel_id
                logger.debug("Created channel in %s for session %s: %s", adapter_type, session_id[:8], channel_id)
                if adapter_type == entry_point:
                    entry_point_channel_id = channel_id

        if entry_point_is_ui and not entry_point_channel_id:
            raise ValueError(f"Entry point adapter {last_input_origin} did not return channel_id")
        if not entry_point_channel_id:
            entry_point_channel_id = ""

        # Store all adapter channel_ids in session metadata
        updated_session = await db.get_session(session_id)
        if updated_session:
            for adapter_type, channel_id in all_channel_ids.items():
                adapter = self.adapters.get(adapter_type)
                if adapter:
                    adapter.store_channel_id(updated_session.adapter_metadata, channel_id)

            await db.update_session(session_id, adapter_metadata=updated_session.adapter_metadata)
            logger.debug("Stored channel_ids for all adapters in session %s metadata", session_id[:8])

        return entry_point_channel_id

    async def ensure_ui_channels(
        self,
        session: "Session",
    ) -> "Session":
        """Single funnel for UI channel provisioning.

        Uses a per-session lock to prevent concurrent provisioning.
        Adapter calls are serialized to prevent cross-adapter metadata overwrites
        (each adapter reads the previous one's writes).
        """
        session_id = session.session_id

        if session_id not in self._channel_ensure_locks:
            self._channel_ensure_locks[session_id] = asyncio.Lock()

        async with self._channel_ensure_locks[session_id]:
            fresh = await db.get_session(session_id)
            if fresh:
                session = fresh

            ui_adapters = self._ui_adapters()
            if not ui_adapters:
                raise ValueError("No UI adapters registered")

            for _, adapter in ui_adapters:
                session = await adapter.ensure_channel(session)

        refreshed = await db.get_session(session_id)
        if not refreshed:
            raise ValueError(f"Session {session_id[:8]} missing after channel creation")
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
