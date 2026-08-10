"""Message and output delivery methods for AdapterRuntime."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.core.db import db
from teleclaude.core.delivery import Router
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionStatusContext, TeleClaudeEvents
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import (
    CleanupTrigger,
    MessageMetadata,
    Session,
    SessionOriginMetadata,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.status_contract import serialize_status_event
from teleclaude.events.envelope import EventVisibility

if TYPE_CHECKING:
    from teleclaude.adapters.base_adapter import BaseAdapter
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)


class _OutputMixin:  # pyright: ignore[reportUnusedClass]
    """Message, output, and delivery operations for AdapterRuntime."""

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
            ensure_channels: bool = True,
            **kwargs: object,
        ) -> object: ...

        cache: "DaemonCache | None"

    @staticmethod
    def _message_ids_from_result(result: object) -> list[str]:
        """Normalize adapter message-send results into concrete message IDs."""
        if result is None:
            return []
        if isinstance(result, list | tuple):
            return [str(item) for item in result if item]
        return [str(result)] if result else []

    def _router(self) -> Router:
        """Build a Router over the currently-registered UI adapter types.

        Cheap and stateless beyond the frozenset snapshot; built fresh per
        call so registry changes (adapter start/stop) are always reflected.
        """
        return Router(adapter_type for adapter_type, _ in self._ui_adapters())

    def _get_cached_session_for_ui_dispatch(self, session_id: str) -> "Session | None":
        """Rebuild enough Session state from a remote cache snapshot for UI control routing."""
        cache = self.cache
        if cache is None:
            return None
        for snapshot in cache.get_sessions():
            if snapshot.session_id != session_id:
                continue
            return Session(
                session_id=snapshot.session_id,
                computer_name=snapshot.computer or "",
                tmux_session_name=snapshot.tmux_session_name or "",
                title=snapshot.title,
                last_input_origin=snapshot.last_input_origin,
                origin_metadata=cast(SessionOriginMetadata, dict(snapshot.origin_metadata)),
                system_role=snapshot.system_role,
                job=snapshot.job,
                project_path=snapshot.project_path,
                subdir=snapshot.subdir,
                initiator_session_id=snapshot.initiator_session_id,
                detached=snapshot.detached,
                native_session_id=snapshot.native_session_id,
                active_agent=snapshot.active_agent,
                thinking_mode=snapshot.thinking_mode,
                human_email=snapshot.human_email,
                human_role=snapshot.human_role,
                lifecycle_status=snapshot.status,
            )
        return None

    async def send_error_feedback(self, session_id: str, error_message: str) -> None:
        """Send error feedback to all UI adapters, surfacing failures."""
        ui_adapters = [
            (adapter_type, adapter) for adapter_type, adapter in self.adapters.items() if isinstance(adapter, UiAdapter)
        ]
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

        delivery_method = (
            "send_overflow_message" if metadata is not None and metadata.is_transcription else "send_message"
        )

        # Route to chosen UI adapters (entry point result preferred)
        result = await self._route_to_ui(
            session_to_use,
            delivery_method,
            text,
            metadata=metadata,
            multi_message=multi_message,
            include_adapters=include_adapters,
        )
        message_ids = self._message_ids_from_result(result)
        message_id = message_ids[-1] if message_ids else None

        # Track for deletion if ephemeral
        if ephemeral and message_ids:
            deletion_type: Literal["user_input", "feedback"] = "feedback" if feedback else "user_input"
            for tracked_message_id in message_ids:
                await db.add_pending_deletion(
                    session.session_id,
                    tracked_message_id,
                    deletion_type=deletion_type,
                )
            if feedback:
                logger.debug(
                    "Feedback tracked for deletion: session=%s message_ids=%s",
                    session.session_id,
                    message_ids,
                )

        return message_id

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
        """Reflect user input to the Discord admin adapter.

        The normal origin-path delivery remains unchanged elsewhere. This path
        only creates the extra admin reflection, and only when the origin is
        not already Discord.
        """
        if not source:
            raise ValueError("broadcast_user_input requires a non-empty source")
        fresh_session = await db.get_session(session.session_id)
        session_to_use = fresh_session or session

        resolver = get_identity_resolver()
        normalized_actor_name = (actor_name or "").strip()
        reflection_origin = source.strip().lower()

        # Transcript-projected terminal input may not have a persisted
        # terminal origin_metadata section, but it should still resolve to
        # the session's human identity for Discord reflection.
        if not normalized_actor_name and reflection_origin == InputOrigin.TERMINAL.value:
            terminal_email = session_to_use.human_email
            if not terminal_email or not terminal_email.strip():
                raise ValueError("Terminal user input reflection requires session.human_email")
            normalized_actor_name = resolver.resolve_by_email(terminal_email).display_name

        if not normalized_actor_name:
            identity = resolver.resolve(source, session_to_use.get_origin_section(source))
            normalized_actor_name = identity.display_name

        reflection_metadata = MessageMetadata(
            parse_mode=None,
            reflection_actor_id=(actor_id or "").strip() or None,
            reflection_actor_name=normalized_actor_name,
            reflection_actor_avatar_url=(actor_avatar_url or "").strip() or None,
            reflection_origin=reflection_origin,
        )
        if reflection_origin == "discord":
            return

        await self._route_to_ui(
            session_to_use,
            "send_overflow_message",
            text,
            metadata=reflection_metadata,
            include_adapters={"discord"},
        )

    async def send_output_update(
        self,
        session: "Session",
        output: str,
        started_at: float,
        last_output_changed_at: float,
        is_final: bool = False,
        exit_code: int | None = None,
        render_markdown: bool = False,
        multi_message: bool = False,
        delivery_ts: datetime | None = None,
    ) -> str | None:
        """Deliver live output on the dual lane: origin UI + Discord admin copy.

        The origin UI adapter receives the session's direct output. Discord also
        receives an admin copy whenever the origin is not already Discord,
        whatever role the session carries. Mirrors the reflection lane's admin
        symmetry so non-Discord-origin sessions remain observable.
        """
        router = self._router()
        origin_adapter = router.resolve_origin_ui_adapter(session)
        admin_target = router.resolve_admin_output_target(session, origin_adapter)

        if origin_adapter is None and admin_target is None:
            logger.debug(
                "Skipping live UI output: session=%s origin=%s system_role=%s",
                session.session_id,
                (session.last_input_origin or "").strip() or "<none>",
                session.system_role or "<none>",
            )
            return None

        args = (
            output,
            started_at,
            last_output_changed_at,
            is_final,
            exit_code,
            render_markdown,
            multi_message,
            delivery_ts,
        )

        origin_result: object = None
        if origin_adapter is not None:
            origin_result = await self._route_to_ui(
                session,
                "send_output_update",
                *args,
                include_adapters={origin_adapter},
            )

        if admin_target is not None:
            await self._route_to_ui(
                session,
                "send_output_update",
                *args,
                include_adapters={admin_target},
            )

        return str(origin_result) if origin_result else None

    async def reconcile_outstanding_final_outputs(self, computer_name: str) -> int:
        """Repair persisted final output that never reached UI adapters.

        Iterates every target resolved by the dual-lane contract so the Discord
        admin copy is repaired alongside origin delivery when eligible.
        """
        sessions = await db.list_sessions(
            computer_name=computer_name,
            include_closed=True,
            include_headless=True,
        )
        repaired = 0
        for session in sessions:
            fresh_session = await db.get_session(session.session_id)
            if fresh_session is not None:
                session = fresh_session
            stop_at = session.last_agent_stop_at
            if not isinstance(stop_at, datetime) or not session.last_output_raw:
                continue

            due_adapters = self._router().resolve_final_output_targets(session)
            if not due_adapters:
                continue

            session_repaired = False
            for adapter_type in sorted(due_adapters):
                adapter = self.adapters.get(adapter_type)
                if not isinstance(adapter, UiAdapter):
                    continue
                delivered_at = adapter.get_last_delivered_at(session)
                if delivered_at is not None and delivered_at >= stop_at:
                    continue

                await self._route_to_ui(
                    session,
                    "send_output_update",
                    session.last_output_raw,
                    0.0,
                    stop_at.timestamp(),
                    is_final=True,
                    include_adapters={adapter_type},
                    delivery_ts=stop_at,
                )
                session_repaired = True

            if session_repaired:
                repaired += 1

        return repaired

    async def break_threaded_turn(self, session: "Session") -> None:
        """Drop pending QoS payloads on all UI adapters.

        Rendering state is managed by the cadence loop, not the lifecycle layer.
        """
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

    async def start_input_turn(self, session: "Session") -> None:
        """Open a UI turn for accepted inbound input and request early presence."""
        await self.break_threaded_turn(session)

        fresh_session = await db.get_session(session.session_id)
        session_to_use = fresh_session or session
        router = self._router()
        origin_adapter = router.resolve_origin_ui_adapter(session_to_use)
        admin_target = router.resolve_admin_output_target(session_to_use, origin_adapter)

        if origin_adapter is not None:
            await self._route_to_ui(
                session_to_use,
                "open_input_turn",
                include_adapters={origin_adapter},
                ensure_channels=False,
            )
        if admin_target is not None:
            await self._route_to_ui(
                session_to_use,
                "open_input_turn",
                include_adapters={admin_target},
                ensure_channels=False,
            )

        self._emit_input_accepted_status(session_to_use.session_id)

    def _emit_input_accepted_status(self, session_id: str) -> None:
        """Emit the canonical accepted status for a UI input acceptance boundary."""
        try:
            now_ts = datetime.now(UTC).isoformat()
            canonical = serialize_status_event(
                session_id=session_id,
                status="accepted",
                reason="user_prompt_accepted",
                timestamp=now_ts,
                last_activity_at=now_ts,
            )
            if canonical is None:
                return
            event_bus.emit(
                TeleClaudeEvents.SESSION_STATUS,
                SessionStatusContext(
                    session_id=session_id,
                    status="accepted",
                    reason="user_prompt_accepted",
                    timestamp=now_ts,
                    last_activity_at=now_ts,
                    message_intent=canonical.message_intent,
                    delivery_scope=canonical.delivery_scope,
                ),
                visibility=EventVisibility.CLUSTER,
            )
        except Exception as exc:
            logger.error(
                "Failed to emit input accepted status: %s",
                exc,
                exc_info=True,
                extra={"session_id": session_id, "status": "accepted"},
            )

    async def edit_message(
        self,
        session: "Session",
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        """Edit message in all UI adapters.

        Args:
            session: Session object
            message_id: Platform-specific message ID
            text: New message text

        Returns:
            True if edit succeeded
        """
        result = await self._route_to_ui(session, "edit_message", message_id, text, metadata=metadata)
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

    async def update_channel_title(self, session: "Session") -> bool:
        """Rename the Discord channel to match the current session state.

        Channel-lifecycle mutation is Discord-only: the Discord adapter is
        resolved as the origin adapter when the session originates on
        Discord, otherwise as the admin-reflection target. Non-Discord
        adapters carry no channel title to update and are never dispatched.

        The display title is derived inside the Discord adapter from session
        state. Caller passes only the session.

        Returns True when the rename succeeded.
        """
        fresh_session = await db.get_session(session.session_id)
        session_to_use = fresh_session or session

        router = self._router()
        origin_adapter = router.resolve_origin_ui_adapter(session_to_use)
        discord_target = (
            origin_adapter
            if origin_adapter == "discord"
            else router.resolve_admin_output_target(session_to_use, origin_adapter)
        )

        if discord_target is None:
            logger.debug(
                "Skipping channel title push: session=%s origin=%s",
                session_to_use.session_id,
                (session_to_use.last_input_origin or "").strip() or "<none>",
            )
            return False

        result = await self._route_to_ui(session_to_use, "update_channel_title", include_adapters={discord_target})
        return bool(result)

    async def dispatch_session_status(self, session_id: str, status: str) -> None:
        """Route a status transition to the session's origin + admin-reflection UI adapters.

        Routing layer responsibility: resolve origin and admin-reflection
        target (mirroring ``update_channel_title``), dispatch. Each adapter
        decides which status values it cares about and what to do with them.
        """
        session = await db.get_session(session_id)
        ensure_channels = True
        if session is None:
            session = self._get_cached_session_for_ui_dispatch(session_id)
            if session is None:
                return
            ensure_channels = False
        router = self._router()
        origin_adapter = router.resolve_origin_ui_adapter(session)
        admin_target = router.resolve_admin_output_target(session, origin_adapter)
        if origin_adapter is not None:
            await self._route_to_ui(
                session,
                "on_session_status",
                status,
                include_adapters={origin_adapter},
                ensure_channels=ensure_channels,
            )
        if admin_target is not None:
            await self._route_to_ui(
                session,
                "on_session_status",
                status,
                include_adapters={admin_target},
                ensure_channels=ensure_channels,
            )

    async def dispatch_session_update(self, session_id: str, updated_fields: Mapping[str, object]) -> None:
        """Route a session field-update to the session's origin + admin-reflection UI adapters.

        Routing layer responsibility: resolve origin and admin-reflection
        target (mirroring ``update_channel_title``), dispatch. Each adapter
        decides which field changes it cares about and what to do with them.
        """
        session = await db.get_session(session_id)
        if session is None:
            return
        router = self._router()
        origin_adapter = router.resolve_origin_ui_adapter(session)
        admin_target = router.resolve_admin_output_target(session, origin_adapter)
        if origin_adapter is not None:
            await self._route_to_ui(
                session,
                "on_session_updated",
                updated_fields,
                include_adapters={origin_adapter},
            )
        if admin_target is not None:
            await self._route_to_ui(
                session,
                "on_session_updated",
                updated_fields,
                include_adapters={admin_target},
            )

    async def delete_channel(self, session: "Session") -> bool:
        """Delete the Discord channel for a session.

        Channel-lifecycle mutation is Discord-only: the Discord adapter is
        resolved as the origin adapter when the session originates on
        Discord, otherwise as the admin-reflection target. Does not
        provision channels — during teardown, never create channels just to
        delete them.

        Args:
            session: Session object (caller already fetched it)

        Returns:
            True if the deletion succeeded
        """
        router = self._router()
        origin_adapter = router.resolve_origin_ui_adapter(session)
        discord_target = (
            origin_adapter
            if origin_adapter == "discord"
            else router.resolve_admin_output_target(session, origin_adapter)
        )
        if discord_target is None:
            return False

        result = await self._route_to_ui(
            session, "delete_channel", include_adapters={discord_target}, ensure_channels=False
        )
        return bool(result)
