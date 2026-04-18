"""Channel provisioning, command handlers, and UI lane management for AdapterRuntime."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import BaseAdapter
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.db import db
from teleclaude.core.models import ChannelMetadata, MessageMetadata
from teleclaude.core.session_utils import get_display_title_for_session

if TYPE_CHECKING:
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_TERMINAL_SESSION_STATUSES = frozenset({"closing", "closed"})


class _ChannelsMixin:  # pyright: ignore[reportUnusedClass]
    """Channel provisioning, command handlers, and UI lane operations."""

    _session_updated_subscribed: bool = False

    def subscribe_session_events(self) -> None:
        """Adapter client does not consume lifecycle title events."""
        if self._session_updated_subscribed:
            return
        self._session_updated_subscribed = True

    if TYPE_CHECKING:
        adapters: dict[str, BaseAdapter]
        _channel_ensure_locks: dict[str, asyncio.Lock]

        def _ui_adapters(self) -> list[tuple[str, UiAdapter]]: ...

        async def _fanout_excluding(  # pylint: disable=unused-argument
            self,
            session: "Session",
            operation: str,
            task_factory: Callable[[UiAdapter, "Session"], Awaitable[object]],
            *,
            exclude: str | None = None,
        ) -> None: ...

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
            session.session_id,
        )

        try:
            result = await task_factory(adapter, session)
            logger.debug(
                "[UI_LANE] Task completed for %s session %s: result=%s",
                adapter_type,
                session.session_id,
                type(result).__name__ if result else "None",
            )
            return result
        except Exception as exc:  # pylint: disable=broad-exception-caught  # UI lanes isolate adapter failures.
            try:
                return await adapter.recover_lane_error(session, exc, task_factory, display_title)
            except Exception:  # pylint: disable=broad-exception-caught  # Recovery is also adapter-defined.
                logger.error(
                    "[UI_LANE] UI adapter %s failed in lane for session %s: %s",
                    adapter_type,
                    session.session_id,
                    exc,
                )
                return None

    async def _run_deferred_ui_lane(
        self,
        session: "Session",
        adapter_type: str,
        task_factory: Callable[[UiAdapter, "Session"], Awaitable[object]],
    ) -> object | None:
        """Execute deferred UI work through the normal lane recovery envelope."""
        adapter = self.adapters.get(adapter_type)
        if adapter is None or not isinstance(adapter, UiAdapter):
            logger.warning(
                "[UI_LANE] Skipping deferred lane for missing adapter=%s session=%s",
                adapter_type,
                session.session_id,
            )
            return None
        return await self._run_ui_lane(session, adapter_type, adapter, task_factory)

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

    async def create_channel(  # pylint: disable=too-many-locals  # Fanout bookkeeping is intentionally explicit.
        self,
        session: "Session",
        title: str,
        last_input_origin: str,
        target_computer: str | None = None,
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

        entry_point_channel_id: str | None = None

        for adapter_type, result in zip(adapter_types, results):
            if isinstance(result, Exception):
                logger.error("Failed to create channel in %s: %s", adapter_type, result)
                if adapter_type == entry_point:
                    raise ValueError(
                        f"Failed to create channel in entry point adapter {adapter_type}: {result}"
                    ) from result
            else:
                channel_id = str(result)
                logger.debug("Created channel in %s for session %s: %s", adapter_type, session_id, channel_id)
                if adapter_type == entry_point:
                    entry_point_channel_id = channel_id

        if entry_point_is_ui and not entry_point_channel_id:
            raise ValueError(f"Entry point adapter {last_input_origin} did not return channel_id")
        return entry_point_channel_id or ""

    async def ensure_ui_channels(
        self,
        session: "Session",
        *,
        include_adapters: set[str] | None = None,
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

            if session.closed_at or session.lifecycle_status in _TERMINAL_SESSION_STATUSES:
                logger.debug(
                    "Skipping ensure_ui_channels for terminal session %s (status=%s)",
                    session_id,
                    session.lifecycle_status,
                )
                return session

            ui_adapters = [
                (adapter_type, adapter)
                for adapter_type, adapter in self.adapters.items()
                if isinstance(adapter, UiAdapter)
            ]
            if include_adapters is not None:
                ui_adapters = [
                    (adapter_type, adapter) for adapter_type, adapter in ui_adapters if adapter_type in include_adapters
                ]
            if not ui_adapters:
                raise ValueError("No UI adapters registered")

            for _, adapter in ui_adapters:
                session = await adapter.ensure_channel(session)

        refreshed = await db.get_session(session_id)
        if not refreshed:
            raise ValueError(f"Session {session_id} missing after channel creation")
        return refreshed

    async def ensure_output_lanes_ready(
        self,
        session: "Session",
        *,
        trigger: str,
        include_adapters: set[str] | None = None,
    ) -> "Session":
        """Run trigger-aware output-lane readiness on selected UI adapters."""
        session_id = session.session_id

        if session_id not in self._channel_ensure_locks:
            self._channel_ensure_locks[session_id] = asyncio.Lock()

        async with self._channel_ensure_locks[session_id]:
            fresh = await db.get_session(session_id)
            if fresh:
                session = fresh

            if session.closed_at or session.lifecycle_status in _TERMINAL_SESSION_STATUSES:
                logger.debug(
                    "Skipping ensure_output_lanes_ready for terminal session %s (status=%s)",
                    session_id,
                    session.lifecycle_status,
                )
                return session

            ui_adapters = [
                (adapter_type, adapter)
                for adapter_type, adapter in self.adapters.items()
                if isinstance(adapter, UiAdapter)
            ]
            if include_adapters is not None:
                ui_adapters = [
                    (adapter_type, adapter) for adapter_type, adapter in ui_adapters if adapter_type in include_adapters
                ]
            if not ui_adapters:
                raise ValueError("No UI adapters registered")

            for _, adapter in ui_adapters:
                session = await adapter.ensure_output_lane_ready(session, trigger=trigger)  # type: ignore[arg-type]

        refreshed = await db.get_session(session_id)
        return refreshed or session

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
