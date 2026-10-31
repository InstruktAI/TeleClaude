"""In-place agent restart: revive the record, stop the running agent, relaunch it from its transcript.

Restarts the agent CLI inside a live session — revives a closed, soft-deleted or pane-less
record, stops the running agent under one stop deadline, relaunches it with resume-from-transcript,
and, for a self-restart, hands the continuation to control delivery. Also exposes the stop barrier
that in-place handoff reuses.
"""

import asyncio
import os
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.constants import RESTART_CONTINUATION_STIMULUS
from teleclaude.core import tmux_bridge, tmux_io
from teleclaude.core.agent_availability import launch_ownership
from teleclaude.core.agent_dispatch import resolve_launch_model
from teleclaude.core.agent_readiness import await_agent_readiness
from teleclaude.core.agents import assert_agent_enabled, get_agent_command
from teleclaude.core.control_delivery import ControlDeliveryWakeDecision, handoff_control_payload
from teleclaude.core.db import db
from teleclaude.core.injected_text import EnvelopeName, InjectedTextSourceFeature, semantic_envelope
from teleclaude.core.models import HumanActionIntent, Session, SessionField
from teleclaude.core.runtime_events import publish_runtime_error
from teleclaude.core.runtime_readiness import RuntimeReadinessKey
from teleclaude.core.session_continuation import ContinuationRefused, rebuild_continuation_loader
from teleclaude.core.session_launch_profile import resolve_session_launch_profile
from teleclaude.core.session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from teleclaude.core.session_runtime_gate import mark_relaunch_awaiting_readiness, session_runtime_owner
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.core.tmux_bridge._keys import discard_shell_input
from teleclaude.daemon_session import AGENT_PROMPT_READY_TIMEOUT_S
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.envelope_facts import home_for_session_config
from teleclaude.events.producer import publish_event
from teleclaude.events.references import SessionRef
from teleclaude.events.schemas.system import SessionRestartFailed, SessionRestartFailedData
from teleclaude.events.wire import LegacyFacts
from teleclaude.runtime.environment import runtime_run_command
from teleclaude.types.commands import RestartAgentCommand, RestartAgentResult, ReviveAgentCommand

from ._keys import _bind_host_pane
from ._utils import with_session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
RELAUNCH_QUIET_S, _AGENT_STOP_TIMEOUT_S, _RESTART_STOP_POLL_INTERVAL_S = 1.0, 30.0, 1.0
_AGENT_RESTART_READINESS_OPPORTUNITY_EVENT = "agent_restart_readiness_opportunity"
_TMUX_SESSION_NAME_FIELD = "tmux_session_name"
_RESTART_REVIVE_CLOSED_EVENT = "agent_restart.session_revived"
_RESTART_RESTORE_DELETED_EVENT = "agent_restart.soft_deleted_session_restored"
_RESTART_PANE_MISSING_EVENT = "agent_restart_pane_missing"
_CONTINUATION_REFUSED_TEMPLATE = "Cannot restart agent: {detail}."
_CONTINUATION_SECTION_SEPARATOR = "\n\n"


class _AgentRestartReadinessOpportunityOutcome(StrEnum):
    """Closed outcomes for a self-restart readiness opportunity."""

    ACCEPTED = "accepted"


class _AgentRestartReadinessOpportunityReason(StrEnum):
    """Closed reasons for a self-restart readiness opportunity."""

    SELF_RESTART_RELAUNCHED = "self_restart_relaunched"


class RestartFailurePhase(StrEnum):
    """Closed vocabulary of the restart-failure exits that emit `teleclaude.agent_runtime.session.restart_failed`."""

    STOP_TIMEOUT = "stop_timeout"
    AGENT_DISABLED = "agent_disabled"
    READINESS_TIMEOUT = "readiness_timeout"
    INPUT_DISCARD_FAILED = "input_discard_failed"


async def _emit_restart_failed(session: Session, *, reason: str, phase: RestartFailurePhase) -> None:
    """Emit the typed restart-failure event so the delivery-edge debounce coalesces operator notifications."""
    await publish_event(
        SessionRestartFailed(
            subject=SessionRef(session.session_id),
            home=home_for_session_config(session.config_subject),
            data=SessionRestartFailedData(
                session_id=session.session_id,
                restart_group=session.session_id,
                reason=reason,
                phase=phase.value,
                computer=config.computer.name,
            ),
        ),
        LegacyFacts(
            producer="agent_restart",
            level=EventLevel.OPERATIONAL,
            domain="agent_runtime",
            visibility=EventVisibility.LOCAL,
            human_action=HumanActionIntent(
                topic="Agent restart failed",
                summary="The session was kept alive for inspection.",
                action="Inspect it and restart manually",
                origin_session_id=session.session_id,
            ),
        ),
    )


@dataclass(frozen=True)
class AgentStopAttempt:
    pane_pid: int | None = None
    agent_pid: int | None = None
    child_count: int = 0
    kill_returncode: int | None = None


async def _terminate_agent_process(tmux_session_name: str) -> AgentStopAttempt:
    """Send SIGTERM directly to the agent process via its PID.

    tmux send-keys C-c goes through the terminal layer and gets swallowed
    when the agent is mid-tool-execution. Direct kill bypasses that.
    """
    pane_pid = await tmux_bridge.get_pane_pid(tmux_session_name)
    if not pane_pid:
        return AgentStopAttempt()
    # Python stdlib has no portable child-process enumeration; pgrep locates the tmux pane child.
    child_procs = await asyncio.create_subprocess_exec(
        "pgrep",
        "-P",
        str(pane_pid),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await child_procs.communicate()
    if not stdout:
        return AgentStopAttempt(pane_pid=pane_pid)
    child_pids = tuple(int(line.strip()) for line in stdout.decode().splitlines() if line.strip().isdigit())
    if not child_pids:
        return AgentStopAttempt(pane_pid=pane_pid)
    agent_pid = child_pids[0]
    kill_returncode = 0
    try:
        os.kill(agent_pid, signal.SIGTERM)
    except OSError as exc:
        kill_returncode = exc.errno or 1
    attempt = AgentStopAttempt(
        pane_pid=pane_pid,
        agent_pid=agent_pid,
        child_count=len(child_pids),
        kill_returncode=kill_returncode,
    )
    logger.debug(
        "agent_restart_sigterm_sent",
        tmux_session=tmux_session_name,
        pane_pid=attempt.pane_pid,
        agent_pid=attempt.agent_pid,
        child_count=attempt.child_count,
        kill_returncode=attempt.kill_returncode,
    )
    return attempt


async def _log_restart_shell_ready_timeout(
    session: Session,
    *,
    target_agent: str,
    stop_attempt: AgentStopAttempt,
    elapsed_ms: int,
) -> None:
    tmux_session = session.tmux_session_name or ""
    current_command = await tmux_bridge.get_current_command(tmux_session)
    tmux_exists = await tmux_bridge.session_exists(tmux_session, log_missing=False)
    pane_dead = await tmux_bridge.is_pane_dead(tmux_session) if tmux_exists else None
    agent_pid_alive = tmux_bridge.pid_is_alive(stop_attempt.agent_pid) if stop_attempt.agent_pid else None
    logger.warning(
        "agent_restart_shell_ready_timeout",
        session_id=session.session_id,
        tmux_session=tmux_session,
        target_agent=target_agent,
        pane_pid=stop_attempt.pane_pid,
        agent_pid=stop_attempt.agent_pid,
        child_count=stop_attempt.child_count,
        kill_returncode=stop_attempt.kill_returncode,
        agent_pid_alive=agent_pid_alive,
        current_command=current_command,
        tmux_exists=tmux_exists,
        pane_dead=pane_dead,
        elapsed_ms=elapsed_ms,
    )


async def _wait_for_agent_exit(
    session: Session,
    *,
    stop_attempt: AgentStopAttempt,
    stop_deadline: float,
) -> bool:
    """Wait for both the host shell and the terminated agent process under one deadline."""
    while True:
        remaining_stop_s = stop_deadline - time.monotonic()
        if remaining_stop_s <= 0:
            return False
        shell_ready = await tmux_io.wait_for_shell_ready(
            session,
            timeout_s=remaining_stop_s,
            poll_interval_s=_RESTART_STOP_POLL_INTERVAL_S,
        )
        if not shell_ready:
            return False
        agent_exited = not stop_attempt.agent_pid or not tmux_bridge.pid_is_alive(stop_attempt.agent_pid)
        if agent_exited:
            return True
        await asyncio.sleep(min(_RESTART_STOP_POLL_INTERVAL_S, remaining_stop_s))


class StopDeadlineAnchor(StrEnum):
    """Where the single stop deadline starts counting: before the termination signal or once it returned."""

    BEFORE_TERMINATION = "before_termination"
    AFTER_TERMINATION = "after_termination"


@dataclass(frozen=True)
class AgentStopResult:
    """Outcome of stopping the agent: what was signalled, whether it exited in time, and how long it took."""

    attempt: AgentStopAttempt
    exited: bool
    elapsed_ms: int


async def stop_agent_process(session: Session, *, deadline_anchor: StopDeadlineAnchor) -> AgentStopResult:
    """Terminate the session's agent process and wait for it and the host shell under one stop deadline."""
    stop_started = time.monotonic()
    attempt = await _terminate_agent_process(session.tmux_session_name)
    deadline_started = stop_started if deadline_anchor is StopDeadlineAnchor.BEFORE_TERMINATION else time.monotonic()
    exited = await _wait_for_agent_exit(
        session,
        stop_attempt=attempt,
        stop_deadline=deadline_started + _AGENT_STOP_TIMEOUT_S,
    )
    return AgentStopResult(attempt=attempt, exited=exited, elapsed_ms=int((time.monotonic() - stop_started) * 1000))


async def _revival_record_updates(session: Session) -> dict[str, str | None]:
    """The stored fields a revival clears: a close, a soft deletion, and a host pane that no longer exists."""
    updates: dict[str, str | None] = {}
    if session.closed_at is not None:
        updates[SessionField.CLOSED_AT.value] = None
        logger.info(_RESTART_REVIVE_CLOSED_EVENT, session_id=session.session_id)
    if session.deleted_at is not None:
        updates[SessionField.DELETED_AT.value] = None
        logger.info(_RESTART_RESTORE_DELETED_EVENT, session_id=session.session_id)
    if session.tmux_session_name and not await tmux_bridge.session_exists(session.tmux_session_name, log_missing=False):
        updates[_TMUX_SESSION_NAME_FIELD] = None
        logger.info(_RESTART_PANE_MISSING_EVENT, session_id=session.session_id, tmux_session=session.tmux_session_name)
    return updates


async def _restart_agent(
    session: Session,
    cmd: RestartAgentCommand | ReviveAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> tuple[bool, str | None] | RestartAgentResult:
    """Restart an AI agent in the session by resuming the native session."""
    active_agent = session.active_agent
    native_session_id = session.native_session_id

    target_agent = active_agent
    if not target_agent:
        error = "Cannot restart agent: no active agent for this session."
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        await publish_runtime_error(source="agent_restart", message=error, session_id=session.session_id)
        await client.send_message(session, f"❌ {error}")
        return False, error

    if not native_session_id:
        error = "Cannot restart agent: no native session ID stored. Start the agent first."
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        await publish_runtime_error(source="agent_restart", message=error, session_id=session.session_id)
        await client.send_message(session, f"❌ {error}")
        return False, error

    try:
        continuation = await rebuild_continuation_loader(session)
    except ContinuationRefused as exc:
        error = _CONTINUATION_REFUSED_TEMPLATE.format(detail=exc.detail)
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        await publish_runtime_error(source="agent_restart", message=error, session_id=session.session_id)
        await client.send_message(session, f"❌ {error}")
        return False, error

    session_updates = await _revival_record_updates(session)

    if session_updates:
        await db.update_session(session.session_id, **session_updates)
        refreshed = await db.get_session(session.session_id)
        if refreshed:
            session = refreshed

    if session.lifecycle_status == "headless" or not session.tmux_session_name:
        bound = await _bind_host_pane(session, client)
        if bound is None:
            return False, "Failed to adopt headless session."
        session, _ = bound

    if session.lifecycle_status in {SessionLifecycleStatus.CLOSED, SessionLifecycleStatus.HEADLESS}:
        await transition_session(
            db,
            session.session_id,
            LifecycleTransition(SessionLifecycleStatus.ACTIVE, LifecycleTransitionReason.RELAUNCH_REOPENED),
        )
        refreshed = await db.get_session(session.session_id)
        if refreshed:
            session = refreshed

    try:
        target_agent = assert_agent_enabled(target_agent)
    except ValueError as exc:
        error = str(exc)
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        await publish_runtime_error(source="agent_restart", message=error, session_id=session.session_id)
        await client.send_message(session, f"❌ {error}")
        await _emit_restart_failed(session, reason=error, phase=RestartFailurePhase.AGENT_DISABLED)
        return False, error

    logger.info(
        "Restarting agent %s in session %s (tmux: %s)",
        target_agent,
        session.session_id,
        session.tmux_session_name,
    )

    stop = await stop_agent_process(session, deadline_anchor=StopDeadlineAnchor.BEFORE_TERMINATION)
    stop_attempt, stop_elapsed_ms = stop.attempt, stop.elapsed_ms
    if not stop.exited:
        error = "Agent did not exit after termination. Restart aborted."
        await _log_restart_shell_ready_timeout(
            session,
            target_agent=target_agent,
            stop_attempt=stop_attempt,
            elapsed_ms=stop_elapsed_ms,
        )
        await publish_runtime_error(source="agent_restart", message=error, session_id=session.session_id)
        await client.send_message(session, f"❌ {error}")
        await _emit_restart_failed(session, reason=error, phase=RestartFailurePhase.STOP_TIMEOUT)
        return False, error
    logger.debug(
        "agent_restart_shell_ready",
        session_id=session.session_id,
        tmux_session=session.tmux_session_name,
        target_agent=target_agent,
        pane_pid=stop_attempt.pane_pid,
        agent_pid=stop_attempt.agent_pid,
        child_count=stop_attempt.child_count,
        kill_returncode=stop_attempt.kill_returncode,
        elapsed_ms=stop_elapsed_ms,
    )

    # The shell is the foreground program now, so an interrupt reaches only it. Clear any
    # unsubmitted input before the run is registered, so the relaunch command cannot fuse
    # onto it and an abort leaves no registered run behind.
    if not await discard_shell_input(session.tmux_session_name):
        error = "Could not clear the host shell's pending input. Restart aborted."
        await publish_runtime_error(source="agent_restart", message=error, session_id=session.session_id)
        await client.send_message(session, f"❌ {error}")
        await _emit_restart_failed(session, reason=error, phase=RestartFailurePhase.INPUT_DISCARD_FAILED)
        return False, error

    restart_mode = session.thinking_mode if session.thinking_mode else "slow"
    launch = await resolve_launch_model(
        target_agent,
        restart_mode,
        ownership=launch_ownership(session.role),
        session_id=session.session_id,
    )
    launch_profile = resolve_session_launch_profile(session, target_agent)
    restart_cmd = get_agent_command(
        agent=target_agent,
        thinking_mode=restart_mode,
        exec=False,
        native_session_id=native_session_id,
        profile=launch_profile.profile,
        launch_flags=launch_profile.flags,
        resolved_flags=launch.flags,
    )
    runtime_run_id = str(uuid4())
    if not await db.install_runtime_run(session.session_id, runtime_run_id):
        return False, None
    restart_cmd = runtime_run_command(restart_cmd, runtime_run_id)

    if cmd.self_restart:
        readiness_key = RuntimeReadinessKey.ordinary(session.session_id, runtime_run_id)
        ready_future = client.runtime_readiness.register(readiness_key)

        mark_relaunch_awaiting_readiness(session.session_id)
        await execute_terminal_command(session.session_id, restart_cmd, None, True)
        logger.info(
            _AGENT_RESTART_READINESS_OPPORTUNITY_EVENT,
            session_id=session.session_id,
            agent_name=target_agent,
            outcome=_AgentRestartReadinessOpportunityOutcome.ACCEPTED.value,
            reason=_AgentRestartReadinessOpportunityReason.SELF_RESTART_RELAUNCHED.value,
        )

        async def _inject_after_restart() -> None:
            try:
                try:
                    # Shared start/restart readiness follows the provider-declared
                    # native signal or complete-pane authority.
                    gate_winner = await await_agent_readiness(
                        agent_name=target_agent,
                        session=session,
                        session_id=session.session_id,
                        ready_future=ready_future,
                        quiet_s=RELAUNCH_QUIET_S,
                        timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
                        readiness=client.runtime_readiness,
                    )
                except TimeoutError:
                    logger.warning(
                        "agent_restart readiness timeout: session=%s timeout_s=%.1f — continuation stimulus not sent",
                        session.session_id,
                        AGENT_PROMPT_READY_TIMEOUT_S,
                    )
                    await client.send_message(
                        session,
                        "Agent readiness timed out after restart. Session kept alive for inspection; continuation stimulus not sent.",
                    )
                    await _emit_restart_failed(
                        session,
                        reason="Agent readiness timed out after restart.",
                        phase=RestartFailurePhase.READINESS_TIMEOUT,
                    )
                    return
            finally:
                client.runtime_readiness.release(readiness_key, ready_future)

            # Start-path parity: confirm the process is live before injecting.
            if not await tmux_io.is_process_running(session):
                logger.error(
                    "agent_restart: process not running after readiness session=%s — continuation stimulus not sent",
                    session.session_id,
                )
                await client.send_message(
                    session,
                    "Agent process exited after restart before the continuation stimulus could be sent; session kept alive for inspection.",
                )
                return

            # The shared control-delivery handoff persists the semantic payload and
            # queues only the content-free wake; the adapter drains the payload at
            # its declared hook boundary.
            logger.info(
                "agent_restart: queueing continuation stimulus session=%s gate=%s",
                session.session_id,
                gate_winner.value,
            )
            occurrence_key = f"restart-continuation:{session.session_id}:{cmd.request_id or time.time_ns()}"
            await handoff_control_payload(
                session_id=session.session_id,
                body=(
                    RESTART_CONTINUATION_STIMULUS
                    if continuation is None
                    else _CONTINUATION_SECTION_SEPARATOR.join((RESTART_CONTINUATION_STIMULUS, continuation.loader))
                ),
                source_key=occurrence_key,
                envelope=semantic_envelope(EnvelopeName.RESTART_CONTINUATION),
                wake_decision=ControlDeliveryWakeDecision.OBSERVED_IDLE,
                wake_source_feature=InjectedTextSourceFeature.AGENT_RESTART,
            )
            logger.info("agent_restart: continuation stimulus accepted session=%s", session.session_id)

        asyncio.create_task(_inject_after_restart(), name="send-restart-stimulus")
    else:
        mark_relaunch_awaiting_readiness(session.session_id)
        await execute_terminal_command(session.session_id, restart_cmd, None, True)

    return True, None


@with_session
async def agent_restart(
    session: Session,
    cmd: RestartAgentCommand | ReviveAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> tuple[bool, str | None] | RestartAgentResult:
    """Serialize ordinary restart with every other session runtime mutation."""
    async with session_runtime_owner(session.session_id):
        return await _restart_agent(session, cmd, client, execute_terminal_command)
