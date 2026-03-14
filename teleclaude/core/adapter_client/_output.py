"""Message and output delivery methods for AdapterClient."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.db import db
from teleclaude.core.models import CleanupTrigger, MessageMetadata
from teleclaude.core.origins import InputOrigin

if TYPE_CHECKING:
    from teleclaude.adapters.base_adapter import BaseAdapter
    from teleclaude.core.models import Session

logger = get_logger(__name__)


class _OutputMixin:  # pyright: ignore[reportUnusedClass]
    """Message, output, and delivery operations for AdapterClient."""

    if TYPE_CHECKING:
        adapters: dict[str, "BaseAdapter"]

        def _ui_adapters(self) -> list[tuple[str, UiAdapter]]: ...

        async def _broadcast_to_ui_adapters(
            self,
            session: "Session",
            operation: str,
            task_factory: Callable[[UiAdapter, "Session"], Awaitable[object]],
            include_adapters: set[str] | None = None,
        ) -> list[tuple[str, object]]: ...

        async def _route_to_ui(
            self,
            session: "Session",
            method: str,
            *args: object,
            include_adapters: set[str] | None = None,
            **kwargs: object,
        ) -> object: ...

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """Send error feedback to all UI adapters, surfacing failures."""
        ui_adapters = self._ui_adapters()
        if not ui_adapters:
            logger.warning("No UI adapters available for error feedback (session %s)", session_id)
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
                    session_id,
                    result,
                )
                if first_error is None:
                    first_error = result
        if first_error is not None:
            raise first_error

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
                      Use False for persistent content (agent output, tool results).
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
                    session.session_id,
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
                    session.session_id,
                    deleted,
                    failed,
                )
                await db.clear_pending_deletions(session.session_id, deletion_type="feedback")

        # Fetch fresh session from DB (session object may be stale after entry point update)
        fresh_session = await db.get_session(session.session_id)
        session_to_use = fresh_session or session

        # Source-only messages: feedback notices and transcription displays.
        # If the origin is not a registered UI adapter, skip delivery.
        source_only = feedback or (metadata is not None and metadata.is_transcription)
        include_adapters: set[str] | None = None
        if source_only:
            origin_adapter = (session_to_use.last_input_origin or "").strip()
            origin_ui_adapter = self.adapters.get(origin_adapter)
            if isinstance(origin_ui_adapter, UiAdapter):
                include_adapters = {origin_adapter}
            else:
                logger.debug(
                    "Skipping source-only message with non-UI origin: session=%s origin=%s",
                    session_to_use.session_id,
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
                    session.session_id,
                    message_id,
                )

        return message_id

    async def move_badge_to_bottom(self, session: "Session") -> None:
        """Atomic-like move of the Session Badge to the absolute bottom on all UI adapters."""
        await self._broadcast_to_ui_adapters(session, "move_badge", lambda adapter, s: adapter.move_badge_to_bottom(s))

    async def break_threaded_turn(self, session: "Session") -> None:
        """Force a break in the threaded output stream on all UI adapters.

        Each adapter clears its own output_message_id and char_offset in its
        metadata namespace. Broadcast is serialized to prevent blob clobbering.

        Also drops pending QoS payloads to prevent stale output from being
        dispatched after the user's new input.
        """
        # Drop pending QoS payloads then clear adapter state.
        for adapter_type, adapter in self.adapters.items():
            if isinstance(adapter, UiAdapter):
                dropped = adapter.drop_pending_output(session.session_id)
                if dropped:
                    logger.debug(
                        "Dropped %d pending QoS payload(s) on turn break: session=%s adapter=%s",
                        dropped,
                        session.session_id,
                        adapter_type,
                    )

        await self._broadcast_to_ui_adapters(session, "break_turn", lambda adapter, s: adapter.clear_turn_state(s))

    async def send_threaded_output(
        self,
        session: "Session",
        text: str,
        multi_message: bool = False,
    ) -> str | None:
        """Send threaded output to all UI adapters (edit if exists, else new)."""
        # Cleanup feedback messages (e.g. transcription display) when threaded output starts.
        pending = await db.get_pending_deletions(session.session_id, deletion_type="feedback")
        if pending:
            logger.debug(
                "Feedback cleanup (threaded output start): session=%s pending_count=%d",
                session.session_id,
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
        exit_code: int | None = None,
        render_markdown: bool = False,
    ) -> str | None:
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
            session.session_id,
            len(output),
            is_final,
        )

        # Cleanup feedback messages (e.g. transcription display) when output starts.
        # This keeps the thread clean by removing intermediate status updates
        # once the real agent output begins.
        pending = await db.get_pending_deletions(session.session_id, deletion_type="feedback")
        if pending:
            logger.debug(
                "Feedback cleanup (output start): session=%s pending_count=%d",
                session.session_id,
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
        """Reflect user input to all UI adapters.

        Core sends raw text + metadata to every adapter. Each adapter owns
        suppression (own-user echo) and presentation (headers, formatting).
        """
        default_actor = (
            "TUI" if source.lower() in {InputOrigin.API.value, InputOrigin.TERMINAL.value} else source.upper()
        )
        normalized_actor_name = (actor_name or "").strip() or (actor_id or "").strip() or default_actor
        fresh_session = await db.get_session(session.session_id)
        session_to_use = fresh_session or session

        reflection_origin = source.strip().lower()
        reflection_metadata = MessageMetadata(
            parse_mode=None,
            reflection_actor_id=(actor_id or "").strip() or None,
            reflection_actor_name=normalized_actor_name,
            reflection_actor_avatar_url=(actor_avatar_url or "").strip() or None,
            reflection_origin=reflection_origin,
        )

        def make_task(adapter: UiAdapter, lane_session: "Session") -> Awaitable[object]:
            return cast(
                Awaitable[object],
                adapter.send_message(
                    lane_session,
                    text,
                    metadata=reflection_metadata,
                ),
            )

        await self._broadcast_to_ui_adapters(
            session_to_use,
            "send_user_input_reflection",
            make_task,
        )

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
