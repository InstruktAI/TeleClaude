"""Session and agent event handling mixin for TeleClaudeDaemon."""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core import polling_coordinator, session_cleanup, tmux_bridge, tmux_io
from teleclaude.core.agent_readiness import wait_for_agent_ready
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.error_feedback import get_user_facing_error_message
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    AgentSessionStartPayload,
    ErrorEventContext,
    SessionLifecycleContext,
    SessionStatusContext,
    SystemCommandContext,
    TeleClaudeEvents,
)
from teleclaude.core.models import MessageMetadata, Session, SessionLaunchIntent, SessionLaunchKind
from teleclaude.core.session_bootstrap import ensure_tmux_with_identity
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.core.status_contract import serialize_status_event
from teleclaude.core.voice_assignment import get_voice_env_vars
from teleclaude.events.envelope import EventVisibility
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

# Agent startup detection
AGENT_START_TIMEOUT_S = 5.0
AGENT_START_POLL_INTERVAL_S = 0.5
AGENT_START_SETTLE_DELAY_S = 0.5  # Initial delay after process starts
AGENT_START_CONFIRM_ENTER_DELAY_S = 1.0
AGENT_START_CONFIRM_ENTER_ATTEMPTS = 4
AGENT_START_OUTPUT_POLL_INTERVAL_S = 0.2
AGENT_START_OUTPUT_CHANGE_TIMEOUT_S = 2.5
AGENT_START_ENTER_INTER_DELAY_S = 0.2
AGENT_START_POST_INJECT_DELAY_S = 1.0
AGENT_START_STABILIZE_TIMEOUT_S = 10.0  # Max wait for output to stop changing during startup
AGENT_START_STABILIZE_QUIET_S = 1.0  # How long output must be quiet to be "stable"
AGENT_START_POST_STABILIZE_DELAY_S = 0.5  # Safety buffer after stabilization
GEMINI_START_EXTRA_DELAY_S = float(os.getenv("GEMINI_START_EXTRA_DELAY_S", "3"))

AGENT_PROMPT_READY_TIMEOUT_S = float(os.getenv("AGENT_PROMPT_READY_TIMEOUT_S", "60"))


@dataclass(frozen=True)
class OutputChangeSummary:
    """Summary details for tmux output changes."""

    changed: bool
    reason: str | None = None
    before_len: int | None = None
    after_len: int | None = None
    diff_index: int | None = None
    before_snippet: str | None = None
    after_snippet: str | None = None


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
        env_vars = get_voice_env_vars(voice) if voice else {}
        working_dir = resolve_working_dir(session.project_path, session.subdir)

        success = await ensure_tmux_with_identity(
            session,
            session.tmux_session_name,
            working_dir,
            env_vars,
        )
        if not success:
            logger.error("Bootstrap failed for %s — session left in initializing state", session_id)
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
    ) -> dict[str, str]:
        """Start agent, wait for TUI input prompt, then inject message."""
        start_time = time.time()
        logger.debug("agent_then_message: started for session=%s", session_id)
        if not message:
            return {"status": "error", "message": "agent_then_message requires a non-empty message"}

        await db.update_session(
            session_id,
            last_message_sent=message[:200],
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

        ready_handler = event_bus.subscribe(TeleClaudeEvents.AGENT_READY, _on_ready)  # type: ignore[arg-type]
        try:
            t0 = time.time()
            await self.command_service.start_agent(
                StartAgentCommand(
                    session_id=session_id,
                    agent_name=agent_name,
                    thinking_mode=thinking_mode,
                    args=[],
                )
            )
            logger.debug("agent_then_message: agent_start took %.3fs", time.time() - t0)

            session = await db.get_session(session_id)
            if not session:
                return {"status": "error", "message": "Session not found after creation"}

            logger.debug("agent_then_message: awaiting AGENT_READY (session=%s)", session_id)
            t1 = time.time()
            try:
                if agent_name == AgentName.CODEX.value:
                    await self._await_codex_readiness(session, session_id, ready_future)
                else:
                    await asyncio.wait_for(ready_future, timeout=AGENT_PROMPT_READY_TIMEOUT_S)
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
                return {
                    "status": "error",
                    "message": "Agent readiness timed out — session kept alive for inspection",
                }
            logger.debug("agent_then_message: AGENT_READY arrived in %.3fs", time.time() - t1)
        finally:
            event_bus.unsubscribe(TeleClaudeEvents.AGENT_READY, ready_handler)

        # Verify agent is actually running before injecting message
        if not await tmux_io.is_process_running(session):
            logger.error("agent_then_message: process not running after readiness (session=%s)", session_id)
            return {"status": "error", "message": "Agent process exited/failed to start before message injection"}

        # Step 2: Inject the message — the agent's stdin loop is live.
        logger.debug("agent_then_message: injecting message to session=%s", session_id)

        working_dir = resolve_working_dir(session.project_path, session.subdir)
        pasted = await tmux_io.process_text(
            session,
            message,
            working_dir=working_dir,
            active_agent=session.active_agent,
        )
        if not pasted:
            return {"status": "error", "message": "Failed to paste command into tmux"}

        await db.update_last_activity(session_id)
        await self._poll_and_send_output(session_id, session.tmux_session_name)

        logger.info("agent_then_message: completed in %.3fs", time.time() - start_time)
        return {"status": "success", "message": "Message injected after agent start"}

    async def _await_codex_readiness(
        self,
        session: Session,
        session_id: str,
        ready_future: asyncio.Future[None],
    ) -> None:
        """Race Codex's broken native SessionStart hook against the pane-quiet detector.

        Codex CLI v0.130+ does not fire its native `SessionStart` hook on cold
        thread_spawn (the hook arrives combined with the first `user_prompt_submit`),
        so the hook-only `ready_future` would time out for ~55% of dispatches. The
        pane-quiet detector (the proven `wait_for_agent_ready` polling loop using
        the `CodexReadinessProfile`'s live-prompt-marker detection) races the hook
        subscription.

        When the pane detector wins, synthesize a `session_start` event with
        `source="startup"` (matching Codex's real-shape contract) but with empty
        native fields — `native_session_id` and `native_log_file` get back-filled
        idempotently when the real hook eventually arrives along with the first
        user prompt.

        Raises TimeoutError if both detectors fail within `AGENT_PROMPT_READY_TIMEOUT_S`.
        """
        pane_task = asyncio.create_task(
            wait_for_agent_ready(
                AgentName.CODEX.value,
                session,
                AGENT_PROMPT_READY_TIMEOUT_S,
                AGENT_START_STABILIZE_QUIET_S,
            )
        )
        hook_task = asyncio.create_task(asyncio.wait_for(ready_future, timeout=AGENT_PROMPT_READY_TIMEOUT_S))
        try:
            done, _pending = await asyncio.wait(
                {pane_task, hook_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (pane_task, hook_task):
                if not task.done():
                    task.cancel()

        hook_won = hook_task in done and not hook_task.cancelled() and hook_task.exception() is None
        if hook_won:
            return

        pane_won = False
        if pane_task in done and not pane_task.cancelled() and pane_task.exception() is None:
            ready, _tail = pane_task.result()
            pane_won = ready

        if not pane_won:
            raise TimeoutError("codex readiness: pane and hook both failed within timeout")

        logger.info(
            "Synthetic session_start emitted for Codex (pane-quiet detector) session=%s",
            session_id,
        )
        synthetic_payload = AgentSessionStartPayload(
            raw={"cwd": session.project_path or "", "source": "startup"},
            transcript_path=None,
            session_id=None,
        )
        synthetic_ctx = AgentEventContext(
            session_id=session_id,
            data=synthetic_payload,
            event_type=AgentHookEvents.AGENT_SESSION_START,
        )
        await self.agent_coordinator.handle_session_start(synthetic_ctx)
        try:
            await asyncio.wait_for(ready_future, timeout=2.0)
        except TimeoutError:
            logger.debug(
                "agent_then_message: synthetic AGENT_READY didn't resolve future — proceeding anyway session=%s",
                session_id,
            )

    async def _pane_output_snapshot(self, session: Session) -> tuple[str, str]:
        output = await tmux_bridge.capture_pane(session.tmux_session_name)
        if not output:
            return "", ""
        tail = output[-UI_MESSAGE_MAX_CHARS:]
        digest = hashlib.sha256(tail.encode("utf-8", errors="replace")).hexdigest()
        return tail, digest

    @staticmethod
    def _summarize_output_change(before: str, after: str) -> OutputChangeSummary:
        if before == after:
            return OutputChangeSummary(changed=False, reason="identical")

        min_len = min(len(before), len(after))
        diff_index = None
        for idx in range(min_len):
            if before[idx] != after[idx]:
                diff_index = idx
                break
        if diff_index is None:
            diff_index = min_len

        snippet_len = 160
        before_snippet = before[max(0, diff_index - 40) : diff_index + snippet_len]
        after_snippet = after[max(0, diff_index - 40) : diff_index + snippet_len]

        return OutputChangeSummary(
            changed=True,
            before_len=len(before),
            after_len=len(after),
            diff_index=diff_index,
            before_snippet=repr(before_snippet),
            after_snippet=repr(after_snippet),
        )

    async def _wait_for_output_change(
        self,
        session: Session,
        before: str,
        before_digest: str,
        timeout_s: float,
    ) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout_s
        last_tail = ""
        while time.monotonic() < deadline:
            current_tail, current_digest = await self._pane_output_snapshot(session)
            last_tail = current_tail
            if current_digest != before_digest:
                return True, current_tail
            await asyncio.sleep(AGENT_START_OUTPUT_POLL_INTERVAL_S)
        return False, last_tail

    async def _confirm_command_acceptance(self, session: Session) -> bool:
        attempts = max(1, AGENT_START_CONFIRM_ENTER_ATTEMPTS)
        for attempt in range(attempts):
            before_tail, before_digest = await self._pane_output_snapshot(session)
            await tmux_io.send_enter(session)
            await asyncio.sleep(AGENT_START_ENTER_INTER_DELAY_S)
            await tmux_io.send_enter(session)

            changed, after_tail = await self._wait_for_output_change(
                session,
                before_tail,
                before_digest,
                AGENT_START_OUTPUT_CHANGE_TIMEOUT_S,
            )
            if changed:
                summary = self._summarize_output_change(before_tail, after_tail)
                logger.debug(
                    "agent_then_message acceptance output change: %s",
                    summary,
                )
                return True
            logger.trace(
                "agent_then_message no output change after enter attempt %d: tail=%s",
                attempt + 1,
                repr(after_tail[-160:]) if after_tail else "''",
            )

            if attempt < attempts - 1:
                await asyncio.sleep(AGENT_START_CONFIRM_ENTER_DELAY_S)
        return False

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
