"""Execution half of an in-place agent handoff."""

import asyncio
import shlex
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.core.agent_availability import launch_ownership
from teleclaude.core.agent_dispatch import resolve_launch_model
from teleclaude.core.agent_readiness import await_agent_readiness
from teleclaude.core.agent_startup_delivery import AgentStartupDeliveryMode, deliver_startup_message
from teleclaude.core.agents import _get_agent_config, assert_agent_enabled, get_agent_command
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionLifecycleContext, TeleClaudeEvents
from teleclaude.core.injected_text import EnvelopeName, render_bracket_envelope, semantic_envelope
from teleclaude.core.models import Session, ThinkingMode
from teleclaude.core.session_runtime_gate import RuntimeMutationInProgress, SessionRuntimeLease
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.core.session_transcript_chain import append_transcript_once
from teleclaude.daemon_session import AGENT_PROMPT_READY_TIMEOUT_S
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.producer import emit_event
from teleclaude.types.commands import HandoffAgentCommand

from . import _agent

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_HANDOFF_COMPLETED_EVENT = "agent_runtime.handoff.completed"
_HANDOFF_FAILED_EVENT = "agent_runtime.handoff.failed"
_HANDOFF_EVENT_SOURCE = "agent_handoff"
_HANDOFF_EVENT_DOMAIN = "agent_runtime"
_HANDOFF_DELIVERY_FAILURE_NOTICE = "Handoff startup brief could not be delivered; session kept alive for inspection."
_HANDOFF_NOT_RUNNABLE_ERROR = "Session is not open and runnable for handoff"
_HANDOFF_SURFACE_UNAVAILABLE_ERROR = "Session has no runnable managed execution surface"
_HANDOFF_STOP_FAILED_ERROR = "Agent did not exit after termination. Handoff aborted."


class HandoffFailurePhase(StrEnum):
    """Closed terminal phases for a handoff that cannot complete."""

    PREPARATION = "preparation"
    STOP = "stop"
    LAUNCH = "launch"
    READINESS = "readiness"
    COMPLETION = "completion"


async def execute_handoff(
    initial_session: Session,
    cmd: HandoffAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
    startup_message: str,
    lease: SessionRuntimeLease,
) -> None:
    """Replace the running CLI only after successor launch preparation succeeds."""
    completed = False
    failure_phase = HandoffFailurePhase.PREPARATION
    try:
        async with lease:
            session = await db.get_session(initial_session.session_id)
            if (
                session is None
                or session.closed_at is not None
                or session.lifecycle_status == SessionLifecycleStatus.HEADLESS
            ):
                raise ValueError(_HANDOFF_NOT_RUNNABLE_ERROR)
            if not session.tmux_session_name or not await tmux_bridge.session_exists(
                session.tmux_session_name, log_missing=False
            ):
                raise ValueError(_HANDOFF_SURFACE_UNAVAILABLE_ERROR)
            successor = assert_agent_enabled(cmd.agent_name or "")
            mode = session.thinking_mode or ThinkingMode.SLOW.value
            launch = await resolve_launch_model(
                successor, mode, ownership=launch_ownership(session.job), session_id=session.session_id
            )
            handoff_envelope = render_bracket_envelope(semantic_envelope(EnvelopeName.HANDOFF, body=startup_message))
            starts_with_prompt = bool(
                _get_agent_config(successor).interactive_flag or _get_agent_config(successor).prompt_at_launch
            )
            successor_command = get_agent_command(
                agent=successor,
                thinking_mode=mode,
                interactive=starts_with_prompt,
                exec=False,
                native_session_id=None,
                profile=_agent._get_session_profile(session),
                resolved_flags=launch.flags,
            )
            if starts_with_prompt:
                successor_command = f"{successor_command} {shlex.quote(handoff_envelope)}"
            stop_attempt = await _agent._terminate_agent_process(session.tmux_session_name)
            failure_phase = HandoffFailurePhase.STOP
            if not await _agent._wait_for_restart_barrier(
                session, stop_attempt=stop_attempt, stop_deadline=time.monotonic() + _agent._RESTART_STOP_TIMEOUT_S
            ):
                raise RuntimeError(_HANDOFF_STOP_FAILED_ERROR)
            await db.update_session(
                session.session_id,
                active_agent=successor,
                native_session_id=None,
                native_log_file=None,
                runtime_start_observed=False,
                runtime_activity_at=None,
                transcript_files=append_transcript_once(session.transcript_files, session.native_log_file),
            )
            current = await db.get_session(session.session_id)
            if current is None:
                return
            ready_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()

            async def on_ready(_event_type: str, context: SessionLifecycleContext) -> None:
                if context.session_id == current.session_id and not ready_future.done():
                    ready_future.set_result(None)

            handler = event_bus.subscribe(TeleClaudeEvents.AGENT_READY, on_ready)
            try:
                failure_phase = HandoffFailurePhase.LAUNCH
                if not await execute_terminal_command(current.session_id, successor_command, None, True):
                    return
                failure_phase = HandoffFailurePhase.READINESS
                await await_agent_readiness(
                    agent_name=successor,
                    session=current,
                    session_id=current.session_id,
                    ready_future=ready_future,
                    quiet_s=_agent._RESTART_QUIET_S,
                    timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
                )
            finally:
                event_bus.unsubscribe(TeleClaudeEvents.AGENT_READY, handler)
            current = await db.get_session(current.session_id)
            if current is None:
                return
            if not starts_with_prompt:
                delivery = await deliver_startup_message(
                    session=current,
                    agent_name=successor,
                    message=handoff_envelope,
                    ready_future=ready_future,
                    quiet_s=_agent._RESTART_QUIET_S,
                    timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
                    delivery_mode=AgentStartupDeliveryMode.HANDOFF,
                )
                if not delivery.succeeded:
                    await client.send_message(current, _HANDOFF_DELIVERY_FAILURE_NOTICE)
                    return
            failure_phase = HandoffFailurePhase.COMPLETION
            await db.update_last_activity(current.session_id)
            await emit_event(
                _HANDOFF_COMPLETED_EVENT,
                source=_HANDOFF_EVENT_SOURCE,
                level=EventLevel.OPERATIONAL,
                domain=_HANDOFF_EVENT_DOMAIN,
                visibility=EventVisibility.LOCAL,
                payload={"session_id": current.session_id, "request_id": cmd.request_id, "successor": successor},
            )
            completed = True
    except RuntimeMutationInProgress:
        logger.info("agent_handoff refused: runtime mutation in progress", session_id=initial_session.session_id)
    except (RuntimeError, ValueError) as exc:
        logger.error("agent_handoff failed: %s", exc, session_id=initial_session.session_id)
    finally:
        if not completed:
            await emit_event(
                _HANDOFF_FAILED_EVENT,
                source=_HANDOFF_EVENT_SOURCE,
                level=EventLevel.OPERATIONAL,
                domain=_HANDOFF_EVENT_DOMAIN,
                visibility=EventVisibility.LOCAL,
                payload={
                    "session_id": initial_session.session_id,
                    "request_id": cmd.request_id,
                    "phase": failure_phase.value,
                },
            )
