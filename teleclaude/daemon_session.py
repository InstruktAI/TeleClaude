"""Session and agent event handling mixin for TeleClaudeDaemon."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Collection, Coroutine
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.agent_registry import AgentName
from teleclaude.config.machine import config
from teleclaude.core import polling_coordinator, session_cleanup
from teleclaude.core.agent_readiness import AGENT_START_STABILIZE_QUIET_S, await_agent_readiness
from teleclaude.core.agent_startup_delivery import (
    AgentStartupDeliveryMode,
    deliver_startup_message,
)
from teleclaude.core.agents import _get_agent_config
from teleclaude.core.cleanup_step import cleanup_step
from teleclaude.core.db import db
from teleclaude.core.degradation import DegradedComponent
from teleclaude.core.error_feedback import get_user_facing_error_message
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    ErrorEventContext,
    SystemCommandContext,
)
from teleclaude.core.injected_text import (
    InjectedInputAuthority,
    construct_delivered_text,
    is_command_loader,
    visible_input_update,
)
from teleclaude.core.models import HumanActionIntent, MessageMetadata, Session, SessionLaunchIntent, SessionLaunchKind
from teleclaude.core.models._session import authority_for_entry_point
from teleclaude.core.next_machine.session_hold import (
    clear_active_runner_for_session_end,
    reconcile_terminal_driver_ownership,
)
from teleclaude.core.runtime_readiness import RuntimeReadinessKey
from teleclaude.core.session_bootstrap import ensure_tmux_with_identity
from teleclaude.core.session_continuation import ContinuationRefused, rebuild_continuation_loader
from teleclaude.core.session_environment import build_agent_session_environment
from teleclaude.core.session_runtime_gate import session_runtime_owner
from teleclaude.core.session_startup import (
    BOOTSTRAP_OWNED_STATES,
    StartupHandover,
    StartupHandoverState,
    StartupMarkRefusedError,
    StartupRecovery,
    bootstrap_task_label,
    launch_dispatch_target,
    launch_is_owed,
    recovery_for,
)
from teleclaude.core.session_status import is_session_final
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.core.shutdown_drain import get_shutdown_drain
from teleclaude.core.tmux_bridge import input_effect_scope
from teleclaude.core.tmux_io import UserTurnDeliveryOutcome
from teleclaude.core.voice_assignment import get_voice_env_vars
from teleclaude.core.workflow_store.store_refusal import STORE_REFUSALS, describe_store_refusal
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.envelope_facts import home_for_session_config
from teleclaude.events.producer import publish_event
from teleclaude.events.references import SessionRef
from teleclaude.events.schemas.system import SessionBootstrapFailed, SessionBootstrapFailedData
from teleclaude.events.wire import LegacyFacts
from teleclaude.mirrors.event_handlers import handle_agent_stop as handle_mirror_agent_stop
from teleclaude.project_root import is_project_checkout
from teleclaude.services.project_catalog.service import get_project_catalog_service
from teleclaude.types.commands import ResumeAgentCommand, StartAgentCommand
from teleclaude.utils.transcript.source_views import clear_transcript_source

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.agent_coordinator import AgentCoordinator
    from teleclaude.core.command_service import CommandService
    from teleclaude.core.degradation import DegradationRecord
    from teleclaude.core.hook_outbox_queue import HookOutboxSessionQueue
    from teleclaude.core.output_poller import OutputPoller

logger = get_logger(__name__)

AGENT_PROMPT_READY_TIMEOUT_S = config.daemon.agent_prompt_ready_timeout_s
_AGENT_STARTUP_DELIVERY_OPPORTUNITY_EVENT = "agent_startup_delivery_opportunity"
_STARTUP_HANDOVER_OUTCOME_EVENT = "session_startup_handover_outcome"
_STARTUP_RECOVERY_DECISION_EVENT = "session_startup_recovery_decision"
_STARTUP_RECOVERY_FAILED_EVENT = "session_startup_recovery_failed"
_STARTUP_CONTINUATION_REFUSED_EVENT = "session_startup_continuation_refused"
_STARTUP_REPORT_UNDELIVERED_EVENT = "session_startup_report_undelivered"
_STARTUP_NO_PROCEDURE_DETAIL = "the unfinished startup carries a dispatch loader but its session records no procedure"
_SESSION_OUTBOX_WORKER_CLEANUP_COMPONENT = "session_outbox_worker"
_LAUNCH_STATUS_KEY = "status"
_LAUNCH_STATUS_SUCCESS = "success"


class _AgentStartupDeliveryOpportunityOutcome(StrEnum):
    """Closed outcomes for a fresh startup delivery opportunity."""

    ACCEPTED = "accepted"


class _AgentStartupDeliveryOpportunityReason(StrEnum):
    """Closed reasons for a fresh startup delivery opportunity."""

    POST_LAUNCH_MESSAGE = "post_launch_message"


@dataclass(frozen=True)
class _StartupRun:
    """The startup handover a running bootstrap advances and the pane its input lands in."""

    session_id: str
    pane_name: str
    state: StartupHandoverState


class _DaemonSessionMixin:  # pyright: ignore[reportUnusedClass]
    """Session and agent event handling methods extracted from TeleClaudeDaemon."""

    if TYPE_CHECKING:
        shutdown_event: asyncio.Event
        _background_tasks: set[asyncio.Task[object]]
        _session_outbox_queues: dict[str, HookOutboxSessionQueue]
        _session_outbox_workers: dict[str, asyncio.Task[None]]
        _hook_outbox_claim_paused_sessions: set[str]
        client: AdapterClient
        degradations: DegradationRecord
        agent_coordinator: AgentCoordinator
        command_service: CommandService
        output_poller: OutputPoller

        def _track_background_task(self, task: asyncio.Task[object], label: str) -> None: ...
        async def _poll_and_send_output(self, session_id: str, tmux_session_name: str) -> None: ...
        async def _start_polling_for_session(self, session_id: str, tmux_session_name: str) -> None: ...

    def _queue_background_task(self, coro: Coroutine[object, object, object], label: str) -> None:
        """Create and track a session bootstrap task that holds its accepted launch until the startup outcome.

        The caller already admitted the launch (or is resuming a startup an earlier
        process accepted), so the bootstrap registers the unit the drain waits for.
        """
        if len(self._background_tasks) > 200:
            logger.warning(
                "Background task cap reached (%d), skipping %s",
                len(self._background_tasks),
                label,
            )
            return
        task = asyncio.create_task(get_shutdown_drain().register(label).carry(coro), name=label)
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

    async def _handle_session_closed(self, session_id: str) -> None:
        """Clean up final session state only while the source row remains terminal.

        SESSION_CLOSED is a fact: the session record is now closed in DB.
        This handler cleans up in-memory state. It MUST NOT call
        terminate_session — doing so causes duplicate channel deletion
        (Topic_id_invalid). The close-intent path is SESSION_CLOSE_REQUESTED.

        """
        current = await db.get_session(session_id)
        if current is not None and not (
            current.deleted_at
            or is_session_final(lifecycle_status=current.lifecycle_status, closed_at=current.closed_at)
        ):
            return
        async with session_runtime_owner(session_id, wait=True):
            current = await db.get_session(session_id)
            if current is not None and not (
                current.deleted_at
                or is_session_final(lifecycle_status=current.lifecycle_status, closed_at=current.closed_at)
            ):
                logger.debug("Skipping delayed close cleanup for revived session %s", session_id)
                return

            logger.debug("session_closed observer: cleaning in-memory state for %s", session_id)
            self._session_outbox_queues.pop(session_id, None)
            self._hook_outbox_claim_paused_sessions.discard(session_id)
            worker = self._session_outbox_workers.pop(session_id, None)
            if worker and not worker.done():
                worker.cancel()
                with cleanup_step(_SESSION_OUTBOX_WORKER_CLEANUP_COMPONENT):
                    try:
                        await worker
                    except asyncio.CancelledError:
                        pass
            polling_coordinator._cleanup_codex_input_state(session_id)
            if current is not None and current.native_log_file:
                clear_transcript_source(current.native_log_file)
            try:
                await clear_active_runner_for_session_end(db, session_id)
            except Exception as exc:
                logger.error("Workflow active_runner clear failed for session %s: %s", session_id, exc, exc_info=True)

    async def _recover_session_housekeeping(self) -> None:
        """Recover resident terminal resources and workflow references from their owners.

        Each project's driver ownership is reconciled independently; one project's failure leaves only
        that project unreconciled.
        """
        identities = set(self._session_outbox_queues) | set(self._session_outbox_workers)
        identities.update(self._hook_outbox_claim_paused_sessions)
        for session_id in sorted(identities):
            await self._handle_session_closed(session_id)
        for project in get_project_catalog_service().list_projects():
            if is_project_checkout(project.root):
                await self._reconcile_project_driver_ownership(str(project.root))

    async def _reconcile_project_driver_ownership(self, project_root: str) -> None:
        """Reconcile one project's terminal driver ownership; its failure leaves that project alone unreconciled.

        Each project is an independent unit of the housekeeping sweep, so a refused or failing workflow
        store never withholds recovery from the other projects. A store refusal degrades the project's
        workflow store and is logged when that mark starts or changes; any other failure is logged and
        leaves the degradation record to the project listing.
        """
        try:
            await reconcile_terminal_driver_ownership(db, project_root)
        except STORE_REFUSALS as refused:
            door = describe_store_refusal(refused, Path(project_root))
            if self.degradations.mark(DegradedComponent.WORKFLOW_STORE, door, subject=project_root):
                logger.error(
                    "Project workflow store refused; its terminal driver ownership is left unreconciled",
                    project_root=project_root,
                    reason=str(refused),
                    door=door,
                    exc_info=True,
                )
        except Exception:
            logger.error(
                "Terminal driver ownership reconciliation failed; the project is left unreconciled",
                project_root=project_root,
                exc_info=True,
            )

    async def _handle_system_command_direct(self, context: SystemCommandContext) -> None:
        """Handle system commands routed directly to the runtime owner.

        System commands are daemon-level operations (restart, health_check, etc.)

        Args:
            context: System command context
        """
        ctx = context

        logger.info("Handling system command '%s' from %s", ctx.command, ctx.from_computer)

        if ctx.command == "health_check":
            await self._handle_health_check()
        else:
            logger.warning("Unknown system command: %s", ctx.command)

    async def _take_startup_mark(
        self,
        session_id: str,
        *,
        expected: Collection[StartupHandoverState],
        target: StartupHandoverState,
    ) -> None:
        """Record startup progress; refuse the input effect it guards when it cannot be recorded."""
        if not await db.advance_startup_handover(session_id, expected=expected, target=target):
            raise StartupMarkRefusedError(session_id, target)

    def _launch_mark_scope(
        self,
        startup: _StartupRun | None,
        intent: SessionLaunchIntent,
        *,
        message_follows_launch: bool = False,
    ) -> AbstractContextManager[None]:
        """Mark the launch attempt at the launcher command's first input into the child's pane."""
        if startup is None:
            return nullcontext()
        target = launch_dispatch_target(intent, message_follows_launch=message_follows_launch)

        async def _mark() -> None:
            await self._take_startup_mark(startup.session_id, expected=(StartupHandoverState.ACCEPTED,), target=target)

        return input_effect_scope(startup.pane_name, _mark)

    def _submission_mark_scope(self, startup: _StartupRun | None) -> AbstractContextManager[None]:
        """Mark the submission at the initial message's first input into the child's pane."""
        if startup is None:
            return nullcontext()

        async def _mark() -> None:
            await self._take_startup_mark(
                startup.session_id,
                expected=(StartupHandoverState.AGENT_LAUNCHED,),
                target=StartupHandoverState.SUBMITTING,
            )

        return input_effect_scope(startup.pane_name, _mark)

    async def _finish_startup(self, startup: _StartupRun | None, outcome: StartupHandoverState) -> None:
        """End the startup handover in `outcome` unless it already ended."""
        if startup is None:
            return
        recorded = await db.advance_startup_handover(
            startup.session_id, expected=BOOTSTRAP_OWNED_STATES, target=outcome
        )
        logger.info(
            _STARTUP_HANDOVER_OUTCOME_EVENT,
            session_id=startup.session_id,
            outcome=outcome.value,
            recorded=recorded,
        )

    async def _execute_launch_intent(
        self,
        session_id: str,
        launch_intent: SessionLaunchIntent | None,
        startup: _StartupRun | None = None,
    ) -> dict[str, str]:
        """Execute a typed post-session launch intent and return status/message."""
        if launch_intent is None or launch_intent.kind == SessionLaunchKind.EMPTY:
            return {"status": "success"}

        if launch_intent.kind == SessionLaunchKind.AGENT:
            if not launch_intent.agent:
                return {"status": "error", "message": "agent launch intent missing agent"}
            with self._launch_mark_scope(startup, launch_intent):
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
            with self._launch_mark_scope(startup, launch_intent):
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
                startup=startup,
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

        handover = await db.get_startup_handover(session_id)
        voice = await db.get_voice(session_id)
        env_vars = build_agent_session_environment(
            project_path=session.project_path,
            platform_env=get_voice_env_vars(voice) if voice else {},
        )
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        tmux_name = session.tmux_session_name or session_cleanup.host_pane_name(session_id)
        startup = (
            _StartupRun(session_id=session_id, pane_name=tmux_name, state=handover.state)
            if handover is not None
            else None
        )

        success = await ensure_tmux_with_identity(
            session,
            tmux_name,
            working_dir,
            env_vars,
        )
        if not success:
            logger.error("Bootstrap failed for %s — session left in initializing state", session_id)
            await publish_event(
                SessionBootstrapFailed(
                    subject=SessionRef(session_id),
                    home=home_for_session_config(session.config_subject),
                    data=SessionBootstrapFailedData(
                        session_id=session_id,
                        project_path=session.project_path,
                        reason="ensure_tmux_with_identity returned False",
                    ),
                ),
                LegacyFacts(
                    producer="daemon",
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
                ),
            )
            await self._finish_startup(startup, StartupHandoverState.FAILED)
            return

        session.tmux_session_name = tmux_name
        await db.update_session(session_id, tmux_session_name=tmux_name)
        await self._start_polling_for_session(session_id, tmux_name)

        # Run launch work BEFORE transitioning to active so that process_message
        # callers waiting on the initializing gate see the transition only after
        # the startup command has been dispatched into tmux.
        launch_result: dict[str, str] | None = None
        if launch_intent and launch_intent.kind != SessionLaunchKind.EMPTY:
            try:
                launch_result = await self._execute_launch_intent(session_id, launch_intent, startup)
            except Exception:
                logger.error(
                    "Bootstrap launch intent failed for session %s",
                    session_id,
                    exc_info=True,
                )
                launch_result = {"status": "error"}
        logger.info(
            "Bootstrap complete for session %s: launch_intent=%s result=%s",
            session_id,
            launch_intent.kind.value if launch_intent else SessionLaunchKind.EMPTY.value,
            launch_result.get("status") if launch_result else "n/a",
        )
        launch_failed = launch_result is not None and launch_result.get(_LAUNCH_STATUS_KEY) != _LAUNCH_STATUS_SUCCESS
        await self._finish_startup(
            startup, StartupHandoverState.FAILED if launch_failed else StartupHandoverState.HANDED_OVER
        )

    async def _recover_session_startups(self) -> None:
        """Take up the session startups a previous run left unfinished.

        A startup whose first input has not begun resumes in the background, so the
        boot never waits for an agent; one interrupted while submitting is reported
        as uncertain and never submitted again. Closing and closed sessions are
        outside the query. A fault in one startup is logged and leaves the others
        and the boot unaffected.
        """
        for handover in await db.list_unfinished_startup_handovers():
            try:
                await self._recover_session_startup(handover)
            except Exception:
                logger.error(_STARTUP_RECOVERY_FAILED_EVENT, session_id=handover.session_id, exc_info=True)

    async def _current_startup_intent(self, handover: StartupHandover) -> SessionLaunchIntent | None:
        """The intent an unfinished startup resumes with: a procedure-bearing startup resumes with a rebuilt loader.

        A startup that carries a resolved invocation, or a command-era loader recorded before the cutover,
        is a procedure startup. Its loader is rebuilt through the shared continuation path — from the
        persisted invocation, additional context included, or from the session's retained evidence when none
        was persisted — and replaces the stored message, which carries nothing beside it.
        The stored role is kept; an input the row does not retain, or a procedure that is no longer usable,
        ends the startup FAILED with the cause logged. A conversational start resumes unchanged.
        """
        intent = handover.intent
        if intent.invocation is None and (intent.message is None or not is_command_loader(intent.message)):
            return intent
        session = await db.get_session(handover.session_id)
        if session is None:
            return intent
        try:
            rebuilt = await rebuild_continuation_loader(session)
        except ContinuationRefused as refusal:
            rebuilt = None
            detail = refusal.detail
        else:
            detail = _STARTUP_NO_PROCEDURE_DETAIL
        if rebuilt is None:
            await db.advance_startup_handover(
                handover.session_id, expected=(handover.state,), target=StartupHandoverState.FAILED
            )
            logger.error(_STARTUP_CONTINUATION_REFUSED_EVENT, session_id=handover.session_id, detail=detail)
            return None
        return replace(intent, message=rebuilt.loader)

    async def _recover_session_startup(self, handover: StartupHandover) -> None:
        """Apply the recovery decision for one unfinished startup."""
        session_id = handover.session_id
        decision = recovery_for(handover.state)
        logger.info(
            _STARTUP_RECOVERY_DECISION_EVENT,
            session_id=session_id,
            state=handover.state.value,
            decision=decision.value,
        )
        if decision is StartupRecovery.RESUME:
            intent = await self._current_startup_intent(handover)
            if intent is None:
                return
            self._queue_background_task(
                self._bootstrap_session_resources(session_id, intent),
                bootstrap_task_label(session_id),
            )
            return
        if decision is StartupRecovery.REPORT_INTERRUPTED_SUBMISSION:
            await db.advance_startup_handover(
                session_id,
                expected=(StartupHandoverState.SUBMITTING,),
                target=StartupHandoverState.REPORTING_UNCERTAIN,
            )
        # The report stays owed (REPORTING_UNCERTAIN) until an audience has accepted it.
        if not await self.agent_coordinator.notify_startup_delivery_uncertain(session_id):
            logger.warning(_STARTUP_REPORT_UNDELIVERED_EVENT, session_id=session_id)
            return
        recorded = await db.advance_startup_handover(
            session_id,
            expected=(StartupHandoverState.REPORTING_UNCERTAIN,),
            target=StartupHandoverState.DELIVERY_UNCERTAIN,
        )
        logger.info(
            _STARTUP_HANDOVER_OUTCOME_EVENT,
            session_id=session_id,
            outcome=StartupHandoverState.DELIVERY_UNCERTAIN.value,
            recorded=recorded,
        )

    async def _handle_agent_then_message(
        self,
        session_id: str,
        *,
        agent_name: str,
        thinking_mode: str,
        message: str,
        launch_intent: SessionLaunchIntent,
        startup: _StartupRun | None = None,
    ) -> dict[str, str]:
        authority = authority_for_entry_point(launch_intent.entry_point)
        if authority is InjectedInputAuthority.CONVERSATION:
            async with session_runtime_owner(session_id, wait=True):
                return await self._handle_agent_then_message_under_owner(
                    session_id,
                    agent_name=agent_name,
                    thinking_mode=thinking_mode,
                    message=message,
                    launch_intent=launch_intent,
                    authority=authority,
                    startup=startup,
                )
        return await self._handle_agent_then_message_under_owner(
            session_id,
            agent_name=agent_name,
            thinking_mode=thinking_mode,
            message=message,
            launch_intent=launch_intent,
            authority=authority,
            startup=startup,
        )

    async def _handle_agent_then_message_under_owner(
        self,
        session_id: str,
        *,
        agent_name: str,
        thinking_mode: str,
        message: str,
        launch_intent: SessionLaunchIntent,
        authority: InjectedInputAuthority,
        startup: _StartupRun | None = None,
    ) -> dict[str, str]:
        """Start an agent and deliver its startup message through its configured input path.

        A startup whose agent was already launched (a resumed bootstrap) skips the
        launch and its accepted-input metadata, keeping the pane and the agent
        process in it, and goes on to the readiness wait and the submission.
        """
        start_time = time.time()
        logger.debug("agent_then_message: started for session=%s", session_id)
        if not message:
            return {"status": "error", "message": "agent_then_message requires a non-empty message"}

        starts_with_prompt = (
            bool(_get_agent_config(agent_name).interactive_flag) or _get_agent_config(agent_name).prompt_at_launch
        )
        startup_text = construct_delivered_text(message, authority, AgentName.from_str(agent_name))
        start_args = [startup_text] if starts_with_prompt else []
        launch_owed = startup is None or launch_is_owed(startup.state)

        if launch_owed:
            await db.update_session(
                session_id,
                last_message_sent=message[:200],
                **visible_input_update(message, visible_source_text=launch_intent.command_input_source_text),
                last_message_sent_at=datetime.now(UTC).isoformat(),
            )

        logger.debug("agent_then_message: agent=%s mode=%s msg=%s", agent_name, thinking_mode, message[:50])

        runtime_run_id = str(uuid4()) if launch_owed else None
        if not launch_owed:
            existing_session = await db.get_session(session_id)
            runtime_run_id = existing_session.runtime_run_id if existing_session is not None else None
        readiness_key = RuntimeReadinessKey.ordinary(session_id, runtime_run_id) if runtime_run_id is not None else None
        ready_future = (
            self.client.runtime_readiness.register(readiness_key)
            if readiness_key is not None
            else asyncio.get_running_loop().create_future()
        )
        try:
            t0 = time.time()
            if launch_owed:
                with self._launch_mark_scope(startup, launch_intent, message_follows_launch=not starts_with_prompt):
                    await self.command_service.start_agent(
                        StartAgentCommand(
                            session_id=session_id,
                            agent_name=agent_name,
                            thinking_mode=thinking_mode,
                            args=start_args,
                            runtime_run_id=runtime_run_id,
                            resolved_model_flags=launch_intent.resolved_model_flags,
                            visible_input_source_text=launch_intent.command_input_source_text,
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
            if (
                runtime_run_id is not None
                and session.runtime_run_id == runtime_run_id
                and session.runtime_start_observed
                and not ready_future.done()
            ):
                # The runtime's start boundary was recorded before this wait began (a
                # bootstrap resumed after the start signal arrived). Reading the
                # record writes no start evidence.
                ready_future.set_result(None)

            logger.debug("agent_then_message: awaiting AGENT_READY (session=%s)", session_id)
            t1 = time.time()
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
                return {
                    "status": "error",
                    "message": "Agent readiness timed out — session kept alive for inspection",
                }
            logger.debug("agent_then_message: readiness opened in %.3fs", time.time() - t1)
        finally:
            if readiness_key is not None:
                self.client.runtime_readiness.release(readiness_key, ready_future)

        if starts_with_prompt:
            await db.update_last_activity(session_id)
            await self._poll_and_send_output(session_id, session.tmux_session_name)
            logger.info("agent_then_message: completed in %.3fs", time.time() - start_time)
            return {"status": "success", "message": "Message supplied with agent start"}

        logger.debug("agent_then_message: delivering startup message to session=%s", session_id)
        with self._submission_mark_scope(startup):
            delivery_result = await deliver_startup_message(
                session=session,
                agent_name=agent_name,
                message=message,
                authority=authority,
                ready_future=ready_future,
                quiet_s=AGENT_START_STABILIZE_QUIET_S,
                timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
                delivery_mode=AgentStartupDeliveryMode.FRESH_START,
                readiness=self.client.runtime_readiness,
            )
        if not delivery_result.succeeded:
            return {"status": "error", "message": "Failed to submit message into agent prompt"}

        await db.update_last_activity(session_id)
        await self._poll_and_send_output(session_id, session.tmux_session_name)
        if delivery_result.outcome is not UserTurnDeliveryOutcome.SUBMITTED:
            # Text appended to an occupied composer was never submitted, so the
            # handover is not finished.
            return {"status": "error", "message": "Startup message left unsubmitted in an occupied composer"}

        logger.info("agent_then_message: completed in %.3fs", time.time() - start_time)
        return {"status": "success", "message": "Message submitted after agent start"}

    async def _await_agent_readiness(
        self,
        session: Session,
        session_id: str,
        agent_name: str,
        ready_future: asyncio.Future[None],
    ) -> None:
        """Open the prompt-injection gate on the provider's declared authority.

        This is used only for agents without an interactive launch-prompt flag.
        Their startup message is injected after launch through the shared
        provider-selected readiness and occupancy path.

        Pane admission authorizes prompt delivery only. Lifecycle state remains
        the authority of normalized runtime hooks.

        Raises TimeoutError when the provider-selected detector does not open within
        `AGENT_PROMPT_READY_TIMEOUT_S`.
        """
        await await_agent_readiness(
            agent_name=agent_name,
            session=session,
            session_id=session_id,
            ready_future=ready_future,
            quiet_s=AGENT_START_STABILIZE_QUIET_S,
            timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
            readiness=self.client.runtime_readiness,
        )

    async def _handle_error(self, context: ErrorEventContext) -> None:
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
