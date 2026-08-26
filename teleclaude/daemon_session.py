"""Session and agent event handling mixin for TeleClaudeDaemon."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Coroutine
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core import polling_coordinator, session_cleanup, tmux_io
from teleclaude.core.agent_readiness import await_agent_readiness, pane_shows_ready_prompt
from teleclaude.core.agents import _get_agent_config
from teleclaude.core.db import db
from teleclaude.core.error_feedback import get_user_facing_error_message
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    ErrorEventContext,
    SessionLifecycleContext,
    SessionStatusContext,
    SystemCommandContext,
    TeleClaudeEvents,
)
from teleclaude.core.injected_text import visible_input_preview
from teleclaude.core.models import HumanActionIntent, MessageMetadata, Session, SessionLaunchIntent, SessionLaunchKind
from teleclaude.core.next_machine.session_hold import clear_active_runner_for_session_end
from teleclaude.core.session_bootstrap import ensure_tmux_with_identity
from teleclaude.core.session_environment import build_agent_session_environment
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.core.status_contract import serialize_status_event
from teleclaude.core.voice_assignment import get_voice_env_vars
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.producer import emit_event
from teleclaude.mirrors.event_handlers import handle_agent_stop as handle_mirror_agent_stop
from teleclaude.mirrors.event_handlers import handle_session_closed as handle_mirror_session_closed
from teleclaude.types.commands import ResumeAgentCommand, StartAgentCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.agent_coordinator import AgentCoordinator
    from teleclaude.core.command_service import CommandService
    from teleclaude.core.hook_outbox_queue import HookOutboxSessionQueue
    from teleclaude.core.output_poller import OutputPoller

logger = get_logger(__name__)

AGENT_START_STABILIZE_QUIET_S = 3.0  # How long output must be quiet to be "stable"
AGENT_PROMPT_READY_TIMEOUT_S = float(os.getenv("AGENT_PROMPT_READY_TIMEOUT_S", "60"))
_AGENT_STARTUP_DELIVERY_OPPORTUNITY_EVENT = "agent_startup_delivery_opportunity"
_AGENT_STARTUP_DELIVERY_DECIDED_EVENT = "agent_startup_delivery_decided"


class _AgentStartupDeliveryOpportunityOutcome(StrEnum):
    """Closed outcomes for a fresh startup delivery opportunity."""

    ACCEPTED = "accepted"


class _AgentStartupDeliveryOpportunityReason(StrEnum):
    """Closed reasons for a fresh startup delivery opportunity."""

    POST_LAUNCH_MESSAGE = "post_launch_message"


class _AgentStartupDeliveryMode(StrEnum):
    """Closed delivery modes for startup message placement."""

    FRESH_START = "fresh_start"


class _DaemonSessionMixin:  # pyright: ignore[reportUnusedClass]
    """Session and agent event handling methods extracted from TeleClaudeDaemon."""

    if TYPE_CHECKING:
        shutdown_event: asyncio.Event
        _background_tasks: set[asyncio.Task[object]]
        _session_outbox_queues: dict[str, HookOutboxSessionQueue]
        _session_outbox_workers: dict[str, asyncio.Task[None]]
        _hook_outbox_claim_paused_sessions: set[str]
        client: AdapterClient
        agent_coordinator: AgentCoordinator
        command_service: CommandService
        output_poller: OutputPoller

        def _track_background_task(self, task: asyncio.Task[object], label: str) -> None: ...
        async def _poll_and_send_output(self, session_id: str, tmux_session_name: str) -> None: ...
        async def _start_polling_for_session(self, session_id: str, tmux_session_name: str) -> None: ...

    def _queue_background_task(self, coro: Coroutine[object, object, object], label: str) -> None:
        """Create and track a background task."""
        if len(self._background_tasks) > 200:
            logger.warning(
                "Background task cap reached (%d), skipping %s",
                len(self._background_tasks),
                label,
            )
            return
        task = asyncio.create_task(coro, name=label)
        self._track_background_task(task, label)

    async def _handle_agent_event_direct(self, context: AgentEventContext) -> None:
        """Run coordinator logic first, then mirror fan-out for agent stop."""
        await self.agent_coordinator.handle_event(context)
        if context.event_type != AgentHookEvents.AGENT_STOP:
            return
        try:
            await handle_mirror_agent_stop(context)
        except Exception as exc:
            logger.error("Mirror AGENT_STOP handler failed: %s", exc, exc_info=True)

    async def _handle_session_closed(self, _event: str, context: SessionLifecycleContext) -> None:
        """Observer-only handler for session_closed events.

        SESSION_CLOSED is a fact: the session record is now closed in DB.
        This handler cleans up in-memory state and dispatches mirror cleanup. It MUST NOT call
        terminate_session — doing so causes duplicate channel deletion
        (Topic_id_invalid). The close-intent path is SESSION_CLOSE_REQUESTED.

        Args:
            _event: Event type (always "session_closed") - unused but required by event handler signature
            context: Session lifecycle context
        """
        ctx = context
        logger.debug("session_closed observer: cleaning in-memory state for %s", ctx.session_id)

        self._session_outbox_queues.pop(ctx.session_id, None)
        self._hook_outbox_claim_paused_sessions.discard(ctx.session_id)
        worker = self._session_outbox_workers.pop(ctx.session_id, None)
        if worker and not worker.done():
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        polling_coordinator._cleanup_codex_input_state(ctx.session_id)
        try:
            await clear_active_runner_for_session_end(db, ctx.session_id)
        except Exception as exc:
            logger.error("Workflow active_runner clear failed for session %s: %s", ctx.session_id, exc, exc_info=True)
        try:
            await handle_mirror_session_closed(ctx)
        except Exception as exc:
            logger.error("Mirror SESSION_CLOSED handler failed: %s", exc, exc_info=True)

    async def _handle_session_close_requested(self, _event: str, context: SessionLifecycleContext) -> None:
        """Handler for session_close_requested events — performs termination exactly once.

        SESSION_CLOSE_REQUESTED is an intent: something wants this session closed.
        This handler calls terminate_session, which deletes channels and closes
        the DB record (emitting SESSION_CLOSED as a fact afterwards).

        Args:
            _event: Event type (always "session_close_requested") - unused but required by event handler signature
            context: Session lifecycle context
        """
        ctx = context

        session = await db.get_session(ctx.session_id)
        if not session:
            logger.warning("Session %s not found for session_close_requested", ctx.session_id)
            return

        logger.info("Handling session_close_requested for %s", ctx.session_id)
        try:
            await session_cleanup.terminate_session(
                ctx.session_id,
                self.client,
                reason="close_requested",
                session=session,
            )
        except Exception as exc:
            logger.error("Failed to close session %s: %s", ctx.session_id, exc, exc_info=True)

            restored = await db.get_session(ctx.session_id)
            if restored and not restored.closed_at:
                await db.update_session(ctx.session_id, lifecycle_status="active")
                timestamp = datetime.now(UTC).isoformat()
                canonical = serialize_status_event(
                    session_id=ctx.session_id,
                    status="error",
                    reason="close_failed",
                    timestamp=timestamp,
                )
                if canonical is not None:
                    event_bus.emit(
                        TeleClaudeEvents.SESSION_STATUS,
                        SessionStatusContext(
                            session_id=ctx.session_id,
                            status="error",
                            reason="close_failed",
                            timestamp=timestamp,
                            message_intent=canonical.message_intent,
                            delivery_scope=canonical.delivery_scope,
                        ),
                        visibility=EventVisibility.CLUSTER,
                    )

    async def _handle_session_started(self, _event: str, _context: SessionLifecycleContext) -> None:
        """No-op handler; headless snapshot delivery is event-driven via the coordinator."""

    async def _handle_system_command(self, _event: str, context: SystemCommandContext) -> None:
        """Handler for SYSTEM_COMMAND events.

        System commands are daemon-level operations (restart, health_check, etc.)

        Args:
            _event: Event type (always "system_command") - unused but required by event handler signature
            context: System command context
        """
        ctx = context

        logger.info("Handling system command '%s' from %s", ctx.command, ctx.from_computer)

        if ctx.command == "health_check":
            await self._handle_health_check()
        else:
            logger.warning("Unknown system command: %s", ctx.command)

    async def _handle_agent_event(self, _event: str, context: AgentEventContext) -> None:
        """Central handler for AGENT_EVENT."""
        await self.agent_coordinator.handle_event(context)

    async def _execute_launch_intent(
        self,
        session_id: str,
        launch_intent: SessionLaunchIntent | None,
    ) -> dict[str, str]:
        """Execute a typed post-session launch intent and return status/message."""
        if launch_intent is None or launch_intent.kind == SessionLaunchKind.EMPTY:
            return {"status": "success"}

        if launch_intent.kind == SessionLaunchKind.AGENT:
            if not launch_intent.agent:
                return {"status": "error", "message": "agent launch intent missing agent"}
            await self.command_service.start_agent(
                StartAgentCommand(
                    session_id=session_id,
                    agent_name=launch_intent.agent,
                    thinking_mode=launch_intent.thinking_mode or "slow",
                    resolved_model_flags=launch_intent.resolved_model_flags,
                )
            )
            return {"status": "success"}

        if launch_intent.kind == SessionLaunchKind.AGENT_RESUME:
            if not launch_intent.agent:
                return {"status": "error", "message": "agent_resume launch intent missing agent"}
            await self.command_service.resume_agent(
                ResumeAgentCommand(
                    session_id=session_id,
                    agent_name=launch_intent.agent,
                    native_session_id=launch_intent.native_session_id,
                )
            )
            return {"status": "success"}

        if launch_intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE:
            if not launch_intent.agent or launch_intent.message is None:
                return {"status": "error", "message": "agent_then_message launch intent incomplete"}
            return await self._handle_agent_then_message(
                session_id,
                agent_name=launch_intent.agent,
                thinking_mode=launch_intent.thinking_mode or "slow",
                message=launch_intent.message,
                launch_intent=launch_intent,
            )

        return {"status": "error", "message": f"Unsupported launch intent: {launch_intent.kind.value}"}

    async def _bootstrap_session_resources(
        self,
        session_id: str,
        launch_intent: SessionLaunchIntent | None,
    ) -> None:
        """Create tmux, start polling, and execute typed launch intent."""
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s missing during bootstrap", session_id)
            return

        voice = await db.get_voice(session_id)
        env_vars = build_agent_session_environment(
            project_path=session.project_path,
            platform_env=get_voice_env_vars(voice) if voice else {},
        )
        working_dir = resolve_working_dir(session.project_path, session.subdir)

        success = await ensure_tmux_with_identity(
            session,
            session.tmux_session_name,
            working_dir,
            env_vars,
        )
        if not success:
            logger.error("Bootstrap failed for %s — session left in initializing state", session_id)
            await emit_event(
                event="system.session.bootstrap_failed",
                source="daemon",
                level=EventLevel.OPERATIONAL,
                domain="system",
                visibility=EventVisibility.CLUSTER,
                human_action=HumanActionIntent(
                    topic="Session bootstrap failed",
                    summary="The session is stranded in initializing.",
                    action="Inspect and re-create or clean up",
                    origin_session_id=session_id,
                ),
                entity=session_id,
                description=f"Session {session_id} bootstrap failed — stranded in initializing",
                payload={
                    "session_id": session_id,
                    "project_path": session.project_path,
                    "reason": "ensure_tmux_with_identity returned False",
                },
            )
            return

        await self._start_polling_for_session(session_id, session.tmux_session_name)

        # Run launch work BEFORE transitioning to active so that process_message
        # callers waiting on the initializing gate see the transition only after
        # the startup command has been dispatched into tmux.
        launch_result: dict[str, str] | None = None
        if launch_intent and launch_intent.kind != SessionLaunchKind.EMPTY:
            try:
                launch_result = await self._execute_launch_intent(session_id, launch_intent)
            except Exception:
                logger.error(
                    "Bootstrap launch intent failed for session %s",
                    session_id,
                    exc_info=True,
                )
                launch_result = {"status": "error"}
        # Transition non-headless sessions to active so they appear in listings.
        # Headless sessions stay "headless" until explicitly adopted by a UI adapter.
        if session.lifecycle_status != "headless":
            await db.update_session(session_id, lifecycle_status="active")

        logger.info(
            "Bootstrap complete for session %s: launch_intent=%s result=%s",
            session_id,
            launch_intent.kind.value if launch_intent else SessionLaunchKind.EMPTY.value,
            launch_result.get("status") if launch_result else "n/a",
        )

    async def _handle_agent_then_message(
        self,
        session_id: str,
        *,
        agent_name: str,
        thinking_mode: str,
        message: str,
        launch_intent: SessionLaunchIntent,
    ) -> dict[str, str]:
        """Start an agent and deliver its startup message through its configured input path."""
        start_time = time.time()
        logger.debug("agent_then_message: started for session=%s", session_id)
        if not message:
            return {"status": "error", "message": "agent_then_message requires a non-empty message"}

        starts_with_prompt = (
            bool(_get_agent_config(agent_name).interactive_flag) or _get_agent_config(agent_name).prompt_at_launch
        )
        start_args = [message] if starts_with_prompt else []

        await db.update_session(
            session_id,
            last_message_sent=message[:200],
            last_input=visible_input_preview(message),
            last_message_sent_at=datetime.now(UTC).isoformat(),
        )

        logger.debug("agent_then_message: agent=%s mode=%s msg=%s", agent_name, thinking_mode, message[:50])

        # Subscribe BEFORE issuing start_agent. The agent's SessionStart hook
        # can race the daemon's command-dispatch overhead and emit AGENT_READY
        # before this coroutine resumes — subscribing after the launch loses
        # the event (event_bus does not replay).
        loop = asyncio.get_running_loop()
        ready_future: asyncio.Future[None] = loop.create_future()

        async def _on_ready(_event_type: str, ctx: SessionLifecycleContext) -> None:
            if ctx.session_id == session_id and not ready_future.done():
                ready_future.set_result(None)

        ready_handler = event_bus.subscribe(TeleClaudeEvents.AGENT_READY, _on_ready)
        try:
            t0 = time.time()
            await self.command_service.start_agent(
                StartAgentCommand(
                    session_id=session_id,
                    agent_name=agent_name,
                    thinking_mode=thinking_mode,
                    args=start_args,
                    resolved_model_flags=launch_intent.resolved_model_flags,
                )
            )
            if not starts_with_prompt:
                logger.info(
                    _AGENT_STARTUP_DELIVERY_OPPORTUNITY_EVENT,
                    session_id=session_id,
                    agent_name=agent_name,
                    outcome=_AgentStartupDeliveryOpportunityOutcome.ACCEPTED.value,
                    reason=_AgentStartupDeliveryOpportunityReason.POST_LAUNCH_MESSAGE.value,
                )
            logger.debug("agent_then_message: agent_start took %.3fs", time.time() - t0)

            session = await db.get_session(session_id)
            if not session:
                return {"status": "error", "message": "Session not found after creation"}

            logger.debug("agent_then_message: awaiting AGENT_READY (session=%s)", session_id)
            t1 = time.time()
            readiness_timed_out = False
            try:
                if starts_with_prompt:
                    await asyncio.wait_for(ready_future, timeout=AGENT_PROMPT_READY_TIMEOUT_S)
                else:
                    await self._await_agent_readiness(session, session_id, agent_name, ready_future)
            except TimeoutError:
                logger.warning(
                    "agent_then_message readiness timeout: session=%s timeout_s=%.1f — session kept alive",
                    session_id,
                    AGENT_PROMPT_READY_TIMEOUT_S,
                )
                event_bus.emit(
                    TeleClaudeEvents.AGENT_READINESS_TIMEOUT,
                    SessionLifecycleContext(session_id=session_id),
                    visibility=EventVisibility.LOCAL,
                )
                # The readiness poll can lose a race with a composer present at its deadline;
                # recheck the same idle-prompt predicate once before attempting any paste.
                readiness_timed_out = True
                if starts_with_prompt or not await pane_shows_ready_prompt(agent_name, session):
                    return {
                        "status": "error",
                        "message": "Agent readiness timed out — session kept alive for inspection",
                    }
            if not readiness_timed_out:
                logger.debug("agent_then_message: AGENT_READY arrived in %.3fs", time.time() - t1)
        finally:
            event_bus.unsubscribe(TeleClaudeEvents.AGENT_READY, ready_handler)

        if starts_with_prompt:
            await db.update_last_activity(session_id)
            await self._poll_and_send_output(session_id, session.tmux_session_name)
            logger.info("agent_then_message: completed in %.3fs", time.time() - start_time)
            return {"status": "success", "message": "Message supplied with agent start"}

        # Verify agent is actually running before injecting message
        if not await tmux_io.is_process_running(session):
            logger.error("agent_then_message: process not running after readiness (session=%s)", session_id)
            return {"status": "error", "message": "Agent process exited/failed to start before message injection"}

        # Step 2: Submit the initial turn without observing a composer that does
        # not yet belong to a human-editable session.
        logger.debug("agent_then_message: submitting fresh-start message to session=%s", session_id)

        delivery_result = await tmux_io.submit_fresh_start_turn(
            session,
            message,
            active_agent=session.active_agent,
        )
        logger.info(
            _AGENT_STARTUP_DELIVERY_DECIDED_EVENT,
            session_id=session_id,
            agent_name=agent_name,
            delivery_mode=_AgentStartupDeliveryMode.FRESH_START.value,
            composer_observed=False,
            outcome=delivery_result.outcome.value,
            reason=delivery_result.reason.value,
            stage=delivery_result.stage.value,
            paste_performed=delivery_result.paste_performed,
            platform_enter_sent=delivery_result.platform_enter_sent,
            existing_input_preserved=delivery_result.existing_input_preserved,
        )
        if delivery_result.outcome is not tmux_io.UserTurnDeliveryOutcome.SUBMITTED:
            return {"status": "error", "message": "Failed to submit message into agent prompt"}

        await db.update_last_activity(session_id)
        await self._poll_and_send_output(session_id, session.tmux_session_name)

        logger.info("agent_then_message: completed in %.3fs", time.time() - start_time)
        return {"status": "success", "message": "Message submitted after agent start"}

    async def _await_agent_readiness(
        self,
        session: Session,
        session_id: str,
        agent_name: str,
        ready_future: asyncio.Future[None],
    ) -> None:
        """Open the prompt-injection gate on whichever readiness signal arrives first.

        This is used only for agents without an interactive launch-prompt flag.
        Their startup message is injected after launch, so the pane-quiet detector
        (`wait_for_agent_ready` with the agent's readiness profile) races the
        native-hook `ready_future`, and injection proceeds on the first signal.

        A pane win authorizes prompt delivery only. Lifecycle state remains the
        authority of normalized runtime hooks.

        Raises TimeoutError if both detectors fail within `AGENT_PROMPT_READY_TIMEOUT_S`.
        """
        await await_agent_readiness(
            agent_name=agent_name,
            session=session,
            session_id=session_id,
            ready_future=ready_future,
            quiet_s=AGENT_START_STABILIZE_QUIET_S,
            timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
        )

    async def _handle_error(self, _event: str, context: ErrorEventContext) -> None:
        """Handle error events (fail-fast contract violations, hook issues)."""
        if not context.session_id:
            logger.error("Error event without session: %s", context.message)
            return

        session = await db.get_session(context.session_id)
        if not session:
            logger.error("Error event for unknown session %s: %s", context.session_id, context.message)
            return

        user_message = get_user_facing_error_message(context)
        if user_message is None:
            logger.debug(
                "Suppressing non-user-facing error event",
                session_id=context.session_id,
                source=context.source,
                code=context.code,
            )
            return

        await self.client.send_message(session, f"❌ {user_message}", metadata=MessageMetadata())

    async def _handle_health_check(self) -> None:
        """Handle health check requested."""
        logger.info("Health check requested")
