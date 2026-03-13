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
from teleclaude.core.db import db, resolve_session_principal
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
    parse_command_string,
)
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.core.status_contract import serialize_status_event
from teleclaude.core.voice_assignment import get_voice_env_vars
from teleclaude.mirrors.event_handlers import handle_agent_stop as handle_mirror_agent_stop
from teleclaude.mirrors.event_handlers import handle_session_closed as handle_mirror_session_closed
from teleclaude.types.commands import ResumeAgentCommand, StartAgentCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.agent_coordinator import AgentCoordinator
    from teleclaude.core.command_service import CommandService
    from teleclaude.core.output_poller import OutputPoller
    from teleclaude.services.headless_snapshot_service import HeadlessSnapshotService

logger = get_logger(__name__)

# Agent auto-command startup detection
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


class _DaemonSessionMixin:
    """Session and agent event handling methods extracted from TeleClaudeDaemon."""

    if TYPE_CHECKING:
        shutdown_event: asyncio.Event
        _background_tasks: set[asyncio.Task[object]]
        _session_outbox_queues: dict[str, object]
        _session_outbox_workers: dict[str, asyncio.Task[None]]
        _hook_outbox_claim_paused_sessions: set[str]
        client: AdapterClient
        agent_coordinator: AgentCoordinator
        command_service: CommandService
        headless_snapshot_service: HeadlessSnapshotService
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
        task = asyncio.create_task(coro)
        self._track_background_task(task, label)

    async def _handle_agent_event_direct(self, context: AgentEventContext) -> None:
        """Run coordinator logic first, then mirror fan-out for agent stop."""
        await self.agent_coordinator.handle_event(context)
        if context.event_type != AgentHookEvents.AGENT_STOP:
            return
        try:
            await handle_mirror_agent_stop(context)
        except Exception as exc:  # pylint: disable=broad-exception-caught
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
        except Exception as exc:  # pylint: disable=broad-exception-caught
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
                    )

    async def _handle_session_started(self, _event: str, context: SessionLifecycleContext) -> None:
        """Handler for session_started events (headless snapshot bootstrap)."""
        session = await db.get_session(context.session_id)
        if not session:
            return

        if session.lifecycle_status != "headless":
            return

        await self.headless_snapshot_service.send_snapshot(session, reason="session_started", client=self.client)

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

    async def _execute_auto_command(self, session_id: str, auto_command: str) -> dict[str, str]:
        """Execute a post-session auto_command and return status/message."""
        cmd_name, auto_args = parse_command_string(auto_command)

        if cmd_name and auto_command:
            session = await db.get_session(session_id)
            if not session or not session.last_input_origin:
                logger.error("Auto-command missing last_input_origin for session %s", session_id)
                await db.update_session(
                    session_id,
                    last_message_sent=auto_command[:200],
                    last_message_sent_at=datetime.now(UTC).isoformat(),
                )
            else:
                await db.update_session(
                    session_id,
                    last_message_sent=auto_command[:200],
                    last_message_sent_at=datetime.now(UTC).isoformat(),
                    last_input_origin=session.last_input_origin,
                )

        if cmd_name == "agent_then_message":
            return await self._handle_agent_then_message(session_id, auto_args)

        if cmd_name == "agent" and auto_args:
            agent_name = auto_args.pop(0)
            await self.command_service.start_agent(
                StartAgentCommand(session_id=session_id, agent_name=agent_name, args=auto_args)
            )
            return {"status": "success"}

        if cmd_name == "agent_resume" and auto_args:
            agent_name = auto_args.pop(0)
            native_session_id = auto_args[0] if auto_args else None
            await self.command_service.resume_agent(
                ResumeAgentCommand(
                    session_id=session_id,
                    agent_name=agent_name,
                    native_session_id=native_session_id,
                )
            )
            return {"status": "success"}

        logger.warning("Unknown or malformed auto_command: %s", auto_command)
        return {"status": "error", "message": f"Unknown or malformed auto_command: {auto_command}"}

    async def _bootstrap_session_resources(self, session_id: str, auto_command: str | None) -> None:
        """Create tmux + start polling + run auto command."""
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s missing during bootstrap", session_id)
            return

        voice = await db.get_voice(session_id)
        voice_env_vars = get_voice_env_vars(voice) if voice else {}
        env_vars = voice_env_vars.copy()
        working_dir = resolve_working_dir(session.project_path, session.subdir)

        # Issue a session token and inject it as TELEC_SESSION_TOKEN into the tmux env.
        # This gives every agent session a daemon-issued credential before the process starts.
        # Child sessions inherit the parent principal so the full agent chain shares one identity.
        principal, role = resolve_session_principal(session)
        session_token = await db.issue_session_token(session_id, principal, role)
        env_vars["TELEC_SESSION_TOKEN"] = session_token
        env_vars["TELECLAUDE_PRINCIPAL"] = principal
        env_vars["TELECLAUDE_PRINCIPAL_ROLE"] = role

        created = await tmux_bridge.ensure_tmux_session(
            name=session.tmux_session_name,
            working_dir=working_dir,
            session_id=session_id,
            env_vars=env_vars,
        )
        if not created:
            logger.error("Failed to create tmux session for %s", session_id)
            await db.update_session(
                session_id,
                lifecycle_status="closed",
                closed_at=datetime.now(UTC),
            )
            return

        # TTS session_start is triggered via event_bus (SESSION_STARTED event)
        await self._start_polling_for_session(session_id, session.tmux_session_name)

        # Run auto-command BEFORE transitioning to active so that process_message
        # callers waiting on the initializing gate see the transition only after
        # the startup command has been dispatched into tmux.
        auto_command_result: dict[str, str] | None = None
        if auto_command:
            try:
                auto_command_result = await self._execute_auto_command(session_id, auto_command)
            except Exception:
                logger.error(
                    "Bootstrap auto-command failed for session %s",
                    session_id,
                    exc_info=True,
                )
                auto_command_result = {"status": "error"}

        # Transition non-headless sessions to active so they appear in listings.
        # Headless sessions stay "headless" until explicitly adopted by a UI adapter.
        if session.lifecycle_status != "headless":
            await db.update_session(session_id, lifecycle_status="active")

        logger.info(
            "Bootstrap complete for session %s: auto_command=%s result=%s",
            session_id,
            bool(auto_command),
            auto_command_result.get("status") if auto_command_result else "n/a",
        )

    async def _handle_agent_then_message(self, session_id: str, args: list[str]) -> dict[str, str]:
        """Start agent, wait for TUI to stabilize, then inject message."""
        from teleclaude.core.agents import AgentName

        start_time = time.time()
        logger.debug("agent_then_message: started for session=%s", session_id)

        if len(args) < 3:
            return {"status": "error", "message": "agent_then_message requires agent, thinking_mode, message"}

        agent_name = args[0]
        thinking_mode = args[1]
        message = " ".join(args[2:]).strip()
        if not message:
            return {"status": "error", "message": "agent_then_message requires a non-empty message"}

        await db.update_session(
            session_id,
            last_message_sent=message[:200],
            last_message_sent_at=datetime.now(UTC).isoformat(),
        )

        logger.debug("agent_then_message: agent=%s mode=%s msg=%s", agent_name, thinking_mode, message[:50])

        # Fire-and-forget start command (don't wait for 1s driver sleep)
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

        # Step 1: Wait for output to stabilize (TUI banner and startup output complete)
        # We integrate the "process running" check into stabilization logic.
        # Gemini gets a longer quiet window to ensure heavy initialization is done.
        logger.debug("agent_then_message: waiting for TUI to stabilize (session=%s)", session_id)

        quiet_s = AGENT_START_STABILIZE_QUIET_S
        if agent_name == AgentName.GEMINI.value:
            quiet_s += max(0, GEMINI_START_EXTRA_DELAY_S)

        t1 = time.time()
        stabilized, _stable_tail = await self._wait_for_output_stable(
            session,
            AGENT_START_STABILIZE_TIMEOUT_S,
            quiet_s,
        )
        logger.debug("agent_then_message: stabilization took %.3fs", time.time() - t1)

        if not stabilized:
            logger.warning(
                "agent_then_message: stabilization timed out after %.1fs, proceeding anyway (session=%s)",
                AGENT_START_STABILIZE_TIMEOUT_S,
                session_id,
            )

        # Verify agent is actually running before injecting message
        if not await tmux_io.is_process_running(session):
            logger.error("agent_then_message: process not running after stabilization (session=%s)", session_id)
            return {"status": "error", "message": "Agent process exited/failed to start before message injection"}

        # Step 2: Inject the message immediately (TUI should be ready)
        logger.debug("agent_then_message: injecting message to session=%s", session_id)

        sanitized_message = tmux_io.wrap_bracketed_paste(message, active_agent=agent_name)
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        pasted = await tmux_io.process_text(
            session,
            sanitized_message,
            working_dir=working_dir,
            send_enter=True,  # Send Enter immediately
            active_agent=session.active_agent,
        )
        if not pasted:
            return {"status": "error", "message": "Failed to paste command into tmux"}

        await db.update_last_activity(session_id)
        await self._poll_and_send_output(session_id, session.tmux_session_name)

        # Step 3: Wait for command acceptance (Enter was already sent)
        accepted = await self._confirm_command_acceptance(session)
        if not accepted:
            logger.warning(
                "agent_then_message timed out waiting for command acceptance (session=%s)",
                session_id,
            )
            return {"status": "error", "message": "Timeout waiting for command acceptance"}

        logger.info("agent_then_message: completed in %.3fs", time.time() - start_time)
        return {"status": "success", "message": "Message injected after agent start"}

    async def _pane_output_snapshot(self, session: Session) -> tuple[str, str]:
        output = await tmux_bridge.capture_pane(session.tmux_session_name)
        if not output:
            return "", ""
        tail = output[-UI_MESSAGE_MAX_CHARS:]
        digest = hashlib.sha256(tail.encode("utf-8", errors="replace")).hexdigest()
        return tail, digest

    async def _wait_for_output_stable(
        self,
        session: Session,
        timeout_s: float,
        quiet_s: float,
    ) -> tuple[bool, str]:
        """Wait for output to stop changing (stabilize).

        Polls tmux output and waits until:
        1. Output has changed from the initial state (indicating process started)
        2. Output hasn't changed for `quiet_s` seconds (indicating TUI loaded)

        Args:
            session: The session to monitor
            timeout_s: Maximum time to wait for stabilization
            quiet_s: How long output must be unchanged to be considered stable

        Returns:
            Tuple of (stabilized, last_output_tail)
        """
        deadline = time.monotonic() + timeout_s
        initial_tail, initial_digest = await self._pane_output_snapshot(session)
        last_tail, last_digest = initial_tail, initial_digest

        has_changed = False
        quiet_since = time.monotonic()

        while time.monotonic() < deadline:
            await asyncio.sleep(AGENT_START_OUTPUT_POLL_INTERVAL_S)
            current_tail, current_digest = await self._pane_output_snapshot(session)

            if current_digest != last_digest:
                # Output changed
                has_changed = True
                last_tail, last_digest = current_tail, current_digest
                quiet_since = time.monotonic()
            elif has_changed and (time.monotonic() - quiet_since >= quiet_s):
                # Output changed at least once AND has been stable for quiet_s seconds
                logger.debug("Output stabilized after %.1fs quiet", quiet_s)
                return True, current_tail

        logger.debug("Output stabilization timed out after %.1fs (has_changed=%s)", timeout_s, has_changed)
        return False, last_tail

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

    async def _wait_for_output_contains(
        self,
        session: Session,
        needle: str,
        timeout_s: float,
    ) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout_s
        last_tail = ""
        while time.monotonic() < deadline:
            current_tail, _ = await self._pane_output_snapshot(session)
            last_tail = current_tail
            if needle and needle in current_tail:
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
