"""Message and output delivery methods for AdapterRuntime."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.core.db import OutputGeneration, db
from teleclaude.core.delivery import Router
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionStatusContext, TeleClaudeEvents
from teleclaude.core.identity import get_identity_resolver, resolve_discord_author_alias
from teleclaude.core.models import (
    CleanupTrigger,
    MessageAuthor,
    MessageMetadata,
    Session,
    SessionOriginMetadata,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.reminders.models import ReminderEntry
from teleclaude.core.reminders.observability import observe_projection_decision, observe_projection_handoff
from teleclaude.core.status_contract import serialize_status_event
from teleclaude.events.envelope import EventVisibility

if TYPE_CHECKING:
    from teleclaude.adapters.base_adapter import BaseAdapter
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)

_PEER_REFLECTION_ORIGIN = "peer_reflection"


def _output_presentation_metadata(session: "Session") -> MessageMetadata | None:
    """Return the owning agent's Discord presentation for ordinary output."""
    if not session.active_agent:
        return None
    author = MessageAuthor.for_agent(
        session_id=session.session_id,
        active_agent=session.active_agent,
        thinking_mode=session.thinking_mode,
    )
    alias, avatar_url = resolve_discord_author_alias(author, owning_session_id=session.session_id, job_role=session.job)
    return MessageMetadata(reflection_actor_name=alias, reflection_actor_avatar_url=avatar_url)


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

    async def broadcast_peer_reflection(
        self,
        session: "Session",
        text: str,
        *,
        actor_name: str,
        actor_avatar_url: str | None = None,
    ) -> str | None:
        """Reflect one parsed peer segment to the Discord admin lane."""
        normalized_actor_name = actor_name.strip()
        if not normalized_actor_name:
            raise ValueError("broadcast_peer_reflection requires a non-empty actor name")
        result = await self._route_to_ui(
            session,
            "send_overflow_message",
            text,
            metadata=MessageMetadata(
                parse_mode=None,
                reflection_actor_name=normalized_actor_name,
                reflection_actor_avatar_url=(actor_avatar_url or "").strip() or None,
                reflection_origin=_PEER_REFLECTION_ORIGIN,
            ),
            include_adapters={"discord"},
        )
        if isinstance(result, list):
            return str(result[-1]) if result else None
        return str(result) if result is not None else None

    async def send_reminder_entry(
        self,
        session: "Session",
        entry: ReminderEntry,
        *,
        projection_pass_id: str,
    ) -> bool:
        """Deliver one typed reminder entry through each independently cursorred DUAL lane."""
        lanes = self._reminder_delivery_lanes(session)
        settled = True
        for lane in sorted(lanes):
            cursor = await db.get_consumer_cursor(session_id=session.session_id, consumer=lane)
            if cursor is not None and cursor.last_reminder_entry_id >= entry.entry_id:
                continue
            observe_projection_decision(
                entry,
                consumer=lane,
                outcome="eligible",
                reason="cursor_pending",
                projection_pass_id=projection_pass_id,
            )
            result = await self._route_to_ui(
                session,
                "send_reminder",
                entry,
                timezone_name=config.computer.timezone,
                include_adapters={lane},
            )
            if not result:
                settled = False
                continue
            await db.advance_reminder_consumer_cursor(
                session_id=session.session_id,
                consumer=lane,
                reminder_entry_id=entry.entry_id,
            )
            observe_projection_handoff(entry, consumer=lane, projection_pass_id=projection_pass_id)
        return settled

    def _reminder_delivery_lanes(self, session: "Session") -> set[str]:
        """Resolve the independently cursorred destinations for reminder delivery."""
        plan = self._router().plan(session, "reminder_lifecycle")
        return {
            destination.platform
            for destination in (plan.origin_endpoint, *plan.admin_lane_destinations)
            if destination is not None
        }

    async def reminder_projection_after_entry_id(self, session: "Session") -> int | None:
        """Return the oldest delivery cursor so projection reads only pending entries."""
        lanes = self._reminder_delivery_lanes(session)
        if not lanes:
            return None
        positions: list[int] = []
        for lane in lanes:
            cursor = await db.get_consumer_cursor(session_id=session.session_id, consumer=lane)
            positions.append(cursor.last_reminder_entry_id if cursor is not None else 0)
        return min(positions)

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
        output_metadata: MessageMetadata | None = None,
    ) -> str | None:
        """Deliver live output on the dual lane: origin UI + Discord admin copy.

        The origin UI adapter receives the session's direct output. Discord also
        receives an admin copy whenever the origin is not already Discord,
        whatever role the session carries. Mirrors the reflection lane's admin
        symmetry so non-Discord-origin sessions remain observable.
        """
        args = (
            output,
            started_at,
            last_output_changed_at,
            is_final,
            exit_code,
            render_markdown,
            multi_message,
            delivery_ts,
            output_metadata,
        )

        if is_final and delivery_ts is not None:
            # Resolved before the router is consulted at all. A versioned pass is
            # driven by the obligations persisted at staging: the lane owed this
            # turn may no longer be one the router would pick, and today's
            # resolution — including its "no target" early return — must not be
            # able to discard it.
            return await self._deliver_staged_final_output(session, delivery_ts, args)

        router = self._router()
        origin_adapter = router.resolve_origin_ui_adapter(session)
        admin_target = router.resolve_admin_output_target(origin_adapter)

        if origin_adapter is None and admin_target is None:
            logger.debug(
                "Skipping live UI output: session=%s origin=%s system_role=%s",
                session.session_id,
                (session.last_input_origin or "").strip() or "<none>",
                session.system_role or "<none>",
            )
            return None

        current_generation = await db.get_latest_output_generation(session.session_id)

        origin_result: object = None
        if origin_adapter is not None:
            origin_result = await self._dispatch_to_lane(session, origin_adapter, output, current_generation, args)

        if admin_target is not None:
            await self._dispatch_to_lane(session, admin_target, output, current_generation, args)

        return str(origin_result) if origin_result else None

    async def _dispatch_to_lane(
        self,
        session: "Session",
        lane: str,
        output: str,
        current_generation: OutputGeneration | None,
        args: tuple[object, ...],
    ) -> object:
        """Dispatch one output update to one lane, skipping and recording per its own cursor.

        Each UI lane owns its cursor independently (Task 11): a lane already
        caught up to this exact render for the session's current generation is
        skipped without dispatching, so one lane's advance can never mute
        another's — and a lane that fails to deliver leaves its own cursor
        behind, correctly retried on the next pass, while a lane that
        succeeded is not re-sent.
        """
        if current_generation is not None:
            cursor = await db.get_consumer_cursor(session_id=session.session_id, consumer=lane)
            if (
                cursor is not None
                and cursor.generation_id == current_generation.generation_id
                and cursor.char_offset >= len(output)
            ):
                return None

        result = await self._route_to_ui(session, "send_output_update", *args, include_adapters={lane})

        if result and current_generation is not None:
            await db.upsert_consumer_cursor(
                session_id=session.session_id,
                consumer=lane,
                generation_id=current_generation.generation_id,
                char_offset=len(output),
            )

        return result

    async def _deliver_staged_final_output(
        self,
        session: "Session",
        version: datetime,
        args: tuple[object, ...],
    ) -> str | None:
        """Deliver a staged final turn to exactly the lanes that were enrolled.

        Enumerates persisted obligations rather than current routing, so a lane
        owed this turn is reached even after origin or policy moved. A lane whose
        receipt already covers the version is skipped, making a repeat pass
        settle rather than resend.
        """
        origin_result: object = None
        origin_adapter = self._router().resolve_origin_ui_adapter(session)
        for lane in sorted(
            lane
            for lane, adapter in self.adapters.items()
            if isinstance(adapter, UiAdapter) and adapter.get_final_output_due_at(session) == version
        ):
            adapter = self.adapters[lane]
            if not isinstance(adapter, UiAdapter):
                continue
            receipt = adapter.get_last_delivered_at(session)
            if receipt is not None and receipt >= version:
                continue
            result = await self._route_to_ui(session, "send_output_update", *args, include_adapters={lane})
            if lane == origin_adapter:
                origin_result = result
        return str(origin_result) if origin_result else None

    @staticmethod
    def canonical_ui_lanes() -> list[str]:
        """Every UI lane that can ever hold an obligation.

        Deliberately not the *registered* set: an adapter that is down at stop
        time would keep an obligation from an older turn while the payload moves
        on, and would deliver that newer payload when it came back.
        """
        excluded = {InputOrigin.TERMINAL, InputOrigin.REMINDER}
        return sorted(origin.value for origin in InputOrigin if origin not in excluded)

    def resolve_final_output_lanes(self, session: "Session") -> list[str]:
        """Return the lanes owed this session's final output, for enrolment.

        Recipient selection happens once, at the agent-stop transition where
        finality is known — the projection that delivers cannot tell a final turn
        from a mid-turn chunk. Repair replays what was resolved here and never
        re-evaluates today's policy against an old turn.
        """
        router = self._router()
        origin_adapter = router.resolve_origin_ui_adapter(session)
        admin_target = router.resolve_admin_output_target(origin_adapter)
        return sorted(
            lane
            for lane in {origin_adapter, admin_target}
            if lane is not None and isinstance(self.adapters.get(lane), UiAdapter)
        )

    async def reconcile_outstanding_final_outputs(self, computer_name: str) -> int:
        """Repair persisted final output that never reached UI adapters.

        Repair replays a delivery obligation the lane already took; it never
        creates one. The obligation is recorded at emission, before delivery is
        attempted, so a first-ever delivery that dies mid-flight is still
        recoverable — a receipt would not survive that, which is why eligibility
        is not inferred from one. A lane holding no obligation predates the
        record and is never enrolled retroactively, so widening the routing
        policy cannot conscript the whole session history. The origin lane is
        exempt: it is the session's own endpoint, owed the output regardless.

        Returns the number of sessions a repair was *attempted* for. A route that
        the adapter then skips still counts, so this is a measure of work started,
        never of delivery confirmed.
        """
        sessions = await db.list_sessions(
            computer_name=computer_name,
            include_closed=True,
            include_headless=True,
        )
        repaired = 0
        for session in sessions:
            await asyncio.sleep(0)
            fresh_session = await db.get_session(session.session_id)
            if fresh_session is not None:
                session = fresh_session
            stop_at = session.last_agent_stop_at
            if not isinstance(stop_at, datetime) or not session.last_output_raw:
                continue

            # Enumerate the obligations this session actually took, never
            # today's routing policy: re-resolving would conscript every
            # historical session the moment the policy widens.
            origin_adapter = self._router().resolve_origin_ui_adapter(session)
            due_adapters = {
                lane
                for lane, adapter in self.adapters.items()
                if isinstance(adapter, UiAdapter) and adapter.get_final_output_due_at(session) is not None
            }
            # The provisioned origin lane is added only for a legacy session that
            # carries no obligation markers at all. Once markers exist they are
            # the whole truth: adding today's origin could deliver the turn to a
            # lane that was unavailable, and therefore not enrolled, at stop time.
            if (
                not due_adapters
                and origin_adapter is not None
                and self._router().origin_section_has_channel(session, origin_adapter)
            ):
                due_adapters.add(origin_adapter)
            if not due_adapters:
                continue
            session_repaired = False
            for adapter_type in sorted(due_adapters):
                adapter = self.adapters.get(adapter_type)
                if not isinstance(adapter, UiAdapter):
                    continue
                due_at = adapter.get_final_output_due_at(session)
                if due_at is None and adapter_type != origin_adapter:
                    continue
                # An enrolled lane is measured against the obligation it took,
                # not against the stop time: a normal delivery records its
                # receipt with the projection's timestamp, which can precede the
                # stop and would otherwise read as outstanding on every boot and
                # replay output the session already has. A legacy origin lane
                # carries no obligation and keeps the stop-time comparison.
                settled_at = due_at if due_at is not None else stop_at
                delivered_at = adapter.get_last_delivered_at(session)
                if delivered_at is not None and delivered_at >= settled_at:
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
                    output_metadata=_output_presentation_metadata(session),
                )
                session_repaired = True

            if session_repaired:
                repaired += 1

        return repaired

    async def start_input_turn(self, session: "Session") -> None:
        """Signal accepted inbound input and request early presence.

        Never clears adapter delivery state (Task 9): acceptance does not cut
        output. Turn-boundary clearing happens only at the generation
        boundary (``UiAdapter._maybe_clear_on_turn_boundary``, driven by
        Task 8's binding), so output still in flight from the previous turn
        keeps its edit target intact through this acceptance. Generation
        identity is the only mechanism that decides a turn boundary (Task
        16) — ``break_threaded_turn`` no longer exists as a second one.
        """
        fresh_session = await db.get_session(session.session_id)
        session_to_use = fresh_session or session

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
            origin_adapter if origin_adapter == "discord" else router.resolve_admin_output_target(origin_adapter)
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
        admin_target = router.resolve_admin_output_target(origin_adapter)
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
        admin_target = router.resolve_admin_output_target(origin_adapter)
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
            origin_adapter if origin_adapter == "discord" else router.resolve_admin_output_target(origin_adapter)
        )
        if discord_target is None:
            return False

        result = await self._route_to_ui(
            session, "delete_channel", include_adapters={discord_target}, ensure_channels=False
        )
        return bool(result)
