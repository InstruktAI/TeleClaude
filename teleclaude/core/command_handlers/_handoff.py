"""Execution half of an in-place agent handoff."""

import shlex
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.core.agent_availability import launch_ownership
from teleclaude.core.agent_dispatch import resolve_launch_model
from teleclaude.core.agent_readiness import await_agent_readiness
from teleclaude.core.agent_startup_delivery import AgentStartupDeliveryMode, deliver_startup_message
from teleclaude.core.agent_status import AgentRunStart, transition_agent_status
from teleclaude.core.agents import _get_agent_config, assert_agent_enabled, get_agent_command
from teleclaude.core.db import db
from teleclaude.core.injected_text import (
    EnvelopeName,
    InjectedInputAuthority,
    render_bracket_envelope,
    semantic_envelope,
)
from teleclaude.core.models import Session, ThinkingMode
from teleclaude.core.runtime_readiness import RuntimeReadinessKey
from teleclaude.core.session_launch_profile import resolve_session_launch_profile
from teleclaude.core.session_runtime_gate import SessionRuntimeLease
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.core.session_transcript_chain import append_transcript_once
from teleclaude.daemon_session import AGENT_PROMPT_READY_TIMEOUT_S
from teleclaude.runtime.environment import runtime_run_command
from teleclaude.types.commands import HandoffAgentCommand

from ._restart import RELAUNCH_QUIET_S, StopDeadlineAnchor, stop_agent_process

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_HANDOFF_DELIVERY_FAILURE_NOTICE = "Handoff startup brief could not be delivered; session kept alive for inspection."
_HANDOFF_NOT_RUNNABLE_ERROR = "Session is not open and runnable for handoff"
_HANDOFF_SURFACE_UNAVAILABLE_ERROR = "Session has no runnable managed execution surface"
_HANDOFF_STOP_FAILED_ERROR = "Agent did not exit after termination. Handoff aborted."
_HANDOFF_SESSION_CLOSED_BEFORE_SUCCESSOR = "Session {} closed before successor launch"


async def execute_handoff(
    initial_session: Session,
    cmd: HandoffAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
    startup_message: str,
    lease: SessionRuntimeLease,
) -> None:
    """Replace the running CLI only after successor launch preparation succeeds.

    Runs synchronously inside the operation's work body: the lease is
    acquired and released entirely here, and every failure propagates as an
    exception so the operation's single terminal-transition path is the sole
    emitter of the outcome — never a parallel event this function emits itself.
    """
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
            successor, mode, ownership=launch_ownership(session.role), session_id=session.session_id
        )
        handoff_envelope = render_bracket_envelope(semantic_envelope(EnvelopeName.HANDOFF, body=startup_message))
        starts_with_prompt = bool(
            _get_agent_config(successor).interactive_flag or _get_agent_config(successor).prompt_at_launch
        )
        successor_profile = resolve_session_launch_profile(session, successor)
        successor_command = get_agent_command(
            agent=successor,
            thinking_mode=mode,
            interactive=starts_with_prompt,
            exec=False,
            native_session_id=None,
            profile=successor_profile.profile,
            launch_flags=successor_profile.flags,
            resolved_flags=launch.flags,
        )
        if starts_with_prompt:
            successor_command = f"{successor_command} {shlex.quote(handoff_envelope)}"
        stop = await stop_agent_process(session, deadline_anchor=StopDeadlineAnchor.AFTER_TERMINATION)
        if not stop.exited:
            raise RuntimeError(_HANDOFF_STOP_FAILED_ERROR)
        await db.update_session(
            session.session_id,
            active_agent=successor,
            native_session_id=None,
            native_log_file=None,
            runtime_start_observed=False,
            transcript_files=append_transcript_once(session.transcript_files, session.native_log_file),
        )
        current = await db.get_session(session.session_id)
        if current is None:
            raise RuntimeError(f"Session {session.session_id} vanished mid-handoff before launch")
        runtime_run_id = str(uuid4())
        if not await db.install_runtime_run(current.session_id, runtime_run_id):
            raise RuntimeError(_HANDOFF_SESSION_CLOSED_BEFORE_SUCCESSOR.format(current.session_id))
        successor_command = runtime_run_command(successor_command, runtime_run_id)
        readiness_key = RuntimeReadinessKey.ordinary(current.session_id, runtime_run_id)
        ready_future = client.runtime_readiness.register(readiness_key)
        try:
            run_started_at = datetime.now(UTC)
            await transition_agent_status(
                db,
                current.session_id,
                AgentRunStart(startup_work_expected=bool(startup_message), run_id=runtime_run_id),
                at=run_started_at,
            )
            if not await execute_terminal_command(current.session_id, successor_command, None, True):
                raise RuntimeError(f"Handoff launch failed for session {current.session_id}")
            await await_agent_readiness(
                agent_name=successor,
                session=current,
                session_id=current.session_id,
                ready_future=ready_future,
                quiet_s=RELAUNCH_QUIET_S,
                timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
                readiness=client.runtime_readiness,
            )
        finally:
            client.runtime_readiness.release(readiness_key, ready_future)
        current = await db.get_session(current.session_id)
        if current is None:
            raise RuntimeError(f"Session {session.session_id} vanished mid-handoff after launch")
        if not starts_with_prompt:
            delivery = await deliver_startup_message(
                session=current,
                agent_name=successor,
                message=handoff_envelope,
                authority=InjectedInputAuthority.INTERFACE,
                ready_future=ready_future,
                quiet_s=RELAUNCH_QUIET_S,
                timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
                delivery_mode=AgentStartupDeliveryMode.HANDOFF,
                readiness=client.runtime_readiness,
            )
            if not delivery.succeeded:
                await client.send_message(current, _HANDOFF_DELIVERY_FAILURE_NOTICE)
                raise RuntimeError(_HANDOFF_DELIVERY_FAILURE_NOTICE)
        await db.update_last_activity(current.session_id)
