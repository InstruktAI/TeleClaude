"""Agent start, resume, restart, and run-command handlers."""

import asyncio
import os
import shlex
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import HUMAN_ROLE_ADMIN, RESTART_CONTINUATION_STIMULUS
from teleclaude.core import tmux_bridge, tmux_io
from teleclaude.core.agent_readiness import await_agent_readiness
from teleclaude.core.agents import AgentName, assert_agent_enabled, get_agent_command
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentRestartDispatchedPayload,
    ErrorEventContext,
    SessionLifecycleContext,
    TeleClaudeEvents,
)
from teleclaude.core.models import AgentResumeArgs, AgentStartArgs, Session, ThinkingMode
from teleclaude.daemon_session import AGENT_PROMPT_READY_TIMEOUT_S
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.producer import emit_event
from teleclaude.types.commands import RestartAgentCommand, ResumeAgentCommand, RunAgentCommand, StartAgentCommand

from ._keys import _ensure_tmux_for_headless
from ._utils import with_session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_THINKING_MODE_VALUES = {mode.value for mode in ThinkingMode}
_RESTART_QUIET_S = 1.0
_RESTART_STOP_TIMEOUT_S = 30.0
_RESTART_STOP_POLL_INTERVAL_S = 1.0


class RestartFailurePhase(StrEnum):
    """Closed vocabulary of the restart-failure exits that emit `agent_runtime.restart.failed`."""

    STOP_TIMEOUT = "stop_timeout"
    AGENT_DISABLED = "agent_disabled"
    READINESS_TIMEOUT = "readiness_timeout"


async def _emit_restart_failed(session: Session, *, reason: str, phase: RestartFailurePhase) -> None:
    """Emit the typed restart-failure event so the delivery-edge debounce coalesces operator notifications."""
    await emit_event(
        "agent_runtime.restart.failed",
        source="agent_restart",
        level=EventLevel.OPERATIONAL,
        domain="agent_runtime",
        visibility=EventVisibility.LOCAL,
        payload={
            "session_id": session.session_id,
            "restart_group": session.session_id,
            "reason": reason,
            "phase": phase.value,
            "computer": config.computer.name,
        },
    )


@dataclass(frozen=True)
class _RestartStopAttempt:
    pane_pid: int | None = None
    agent_pid: int | None = None
    child_count: int = 0
    kill_returncode: int | None = None


def _get_session_profile(session: Session) -> str:
    """Determine agent profile based on human role."""
    if session.human_role == HUMAN_ROLE_ADMIN:
        return "default"
    return "restricted"


@with_session
async def start_agent(
    session: Session,
    cmd: StartAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> None:
    """Start a generic AI agent in session with optional arguments."""
    if session.lifecycle_status == "headless" or not session.tmux_session_name:
        adopted = await _ensure_tmux_for_headless(
            session,
            client,
            None,
            resume_native=False,
        )
        if not adopted:
            return
        session = adopted

    agent_name = cmd.agent_name
    args = list(cmd.args)
    logger.debug(
        "agent_start: session=%s agent_name=%r args=%s config_agents=%s",
        session.session_id,
        agent_name,
        args,
        list(config.agents.keys()),
    )
    try:
        agent_name = assert_agent_enabled(agent_name)
    except ValueError as exc:
        error = str(exc)
        logger.error(
            "Agent start rejected: %r (session=%s, available=%s, error=%s)",
            agent_name,
            session.session_id,
            list(config.agents.keys()),
            error,
        )
        await client.send_message(session, error)
        return

    stored_mode_raw = session.thinking_mode if isinstance(session.thinking_mode, str) else None
    stored_mode = stored_mode_raw or ThinkingMode.SLOW.value

    user_args = list(args)
    thinking_mode = stored_mode
    if user_args and user_args[0] in _THINKING_MODE_VALUES:
        thinking_mode = user_args.pop(0)

    if thinking_mode == ThinkingMode.DEEP.value and agent_name != AgentName.CODEX.value:
        await client.send_message(
            session,
            "deep is only supported for codex. Use fast/med/slow for other agents.",
        )
        return

    start_args = AgentStartArgs(
        agent_name=agent_name,
        thinking_mode=ThinkingMode(thinking_mode),
        user_args=user_args,
    )

    await db.update_session(session.session_id, thinking_mode=start_args.thinking_mode.value)

    has_prompt = bool(start_args.user_args)
    base_cmd = get_agent_command(
        start_args.agent_name,
        thinking_mode=start_args.thinking_mode.value,
        interactive=has_prompt,
        profile=_get_session_profile(session),
    )

    cmd_parts = [base_cmd]

    if start_args.user_args:
        quoted_args = [shlex.quote(arg) for arg in start_args.user_args]
        cmd_parts.extend(quoted_args)

    command_str = " ".join(cmd_parts)
    logger.info("Executing agent start command for %s: %s", agent_name, command_str)

    initial_prompt = " ".join(start_args.user_args) if start_args.user_args else None
    truncated_prompt = initial_prompt[:200] if initial_prompt is not None else None

    updates: dict[str, object] = {  # guard: loose-dict - optional session field set
        "active_agent": agent_name,
        "thinking_mode": start_args.thinking_mode.value,
    }
    # A start that carries no prompt of its own leaves the acceptance marker
    # alone. Clearing it discards the proof that an origin accepted the pending
    # turn, so the prompt hook cannot attribute that turn and relabels it
    # terminal — which reflects the input straight back into the thread already
    # showing it.
    if truncated_prompt is not None:
        updates["last_message_sent"] = truncated_prompt
        updates["last_message_sent_at"] = datetime.now(UTC).isoformat()
    if cmd.origin:
        updates["last_input_origin"] = cmd.origin
    await db.update_session(session.session_id, **updates)

    await execute_terminal_command(session.session_id, command_str, None, True)


@with_session
async def resume_agent(
    session: Session,
    cmd: ResumeAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> None:
    """Resume a generic AI agent session."""
    if session.lifecycle_status == "headless" or not session.tmux_session_name:
        adopted = await _ensure_tmux_for_headless(
            session,
            client,
            None,
            resume_native=False,
        )
        if not adopted:
            return
        session = adopted

    agent_name = cmd.agent_name or ""
    args = [cmd.native_session_id] if cmd.native_session_id else []

    if not agent_name:
        active = session.active_agent
        if not active:
            await client.send_message(session, "No active agent to resume")
            return
        agent_name = active

    try:
        agent_name = assert_agent_enabled(agent_name)
    except ValueError as exc:
        await client.send_message(session, str(exc))
        return

    thinking_raw = session.thinking_mode
    native_session_id_override = args[0].strip() if args else ""
    native_session_id = native_session_id_override or session.native_session_id
    if native_session_id_override:
        await db.update_session(session.session_id, native_session_id=native_session_id_override)

    resume_args = AgentResumeArgs(
        agent_name=agent_name,
        native_session_id=native_session_id,
        thinking_mode=ThinkingMode(thinking_raw) if thinking_raw else None,
    )

    command_str = get_agent_command(
        agent=resume_args.agent_name,
        thinking_mode=resume_args.thinking_mode.value if resume_args.thinking_mode else None,
        exec=False,
        resume=not resume_args.native_session_id,
        native_session_id=resume_args.native_session_id,
        profile=_get_session_profile(session),
    )

    if resume_args.native_session_id:
        logger.info("Resuming %s session %s (from database)", agent_name, resume_args.native_session_id)
    else:
        logger.info("Continuing latest %s session (no native session ID in database)", agent_name)

    if cmd.origin:
        await db.update_session(session.session_id, active_agent=agent_name, last_input_origin=cmd.origin)
    else:
        await db.update_session(session.session_id, active_agent=agent_name)

    await execute_terminal_command(session.session_id, command_str, None, True)


async def _terminate_agent_process(tmux_session_name: str) -> _RestartStopAttempt:
    """Send SIGTERM directly to the agent process via its PID.

    tmux send-keys C-c goes through the terminal layer and gets swallowed
    when the agent is mid-tool-execution. Direct kill bypasses that.
    """
    pane_pid = await tmux_bridge.get_pane_pid(tmux_session_name)
    if not pane_pid:
        return _RestartStopAttempt()
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
        return _RestartStopAttempt(pane_pid=pane_pid)
    child_pids = tuple(int(line.strip()) for line in stdout.decode().splitlines() if line.strip().isdigit())
    if not child_pids:
        return _RestartStopAttempt(pane_pid=pane_pid)
    agent_pid = child_pids[0]
    kill_returncode = 0
    try:
        os.kill(agent_pid, signal.SIGTERM)
    except OSError as exc:
        kill_returncode = exc.errno or 1
    attempt = _RestartStopAttempt(
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
    stop_attempt: _RestartStopAttempt,
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


async def _wait_for_restart_barrier(
    session: Session,
    *,
    stop_attempt: _RestartStopAttempt,
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


@with_session
async def agent_restart(
    session: Session,
    cmd: RestartAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> tuple[bool, str | None]:
    """Restart an AI agent in the session by resuming the native session."""
    active_agent = session.active_agent
    native_session_id = session.native_session_id

    target_agent = cmd.agent_name or active_agent
    if not target_agent:
        error = "Cannot restart agent: no active agent for this session."
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
            visibility=EventVisibility.CLUSTER,
        )
        await client.send_message(session, f"❌ {error}")
        return False, error

    if not native_session_id:
        error = "Cannot restart agent: no native session ID stored. Start the agent first."
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
            visibility=EventVisibility.CLUSTER,
        )
        await client.send_message(session, f"❌ {error}")
        return False, error

    session_updates: dict[str, str | None] = {}
    if session.closed_at is not None:
        session_updates["closed_at"] = None
        session_updates["lifecycle_status"] = "headless"
        logger.info("Reviving closed session before agent restart (session=%s)", session.session_id)

    tmux_exists = False
    if session.tmux_session_name:
        tmux_exists = await tmux_bridge.session_exists(session.tmux_session_name, log_missing=False)
        if not tmux_exists:
            session_updates["tmux_session_name"] = None
            session_updates["lifecycle_status"] = "headless"
            logger.info(
                "Session tmux missing; forcing headless adoption before restart (session=%s tmux=%s)",
                session.session_id,
                session.tmux_session_name,
            )

    if session_updates:
        await db.update_session(session.session_id, **session_updates)
        refreshed = await db.get_session(session.session_id)
        if refreshed:
            session = refreshed

    if session.lifecycle_status == "headless" or not session.tmux_session_name:
        adopted = await _ensure_tmux_for_headless(
            session,
            client,
            None,
            resume_native=False,
        )
        if not adopted:
            return False, "Failed to adopt headless session."
        session = adopted

    try:
        target_agent = assert_agent_enabled(target_agent)
    except ValueError as exc:
        error = str(exc)
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
            visibility=EventVisibility.CLUSTER,
        )
        await client.send_message(session, f"❌ {error}")
        await _emit_restart_failed(session, reason=error, phase=RestartFailurePhase.AGENT_DISABLED)
        return False, error

    logger.info(
        "Restarting agent %s in session %s (tmux: %s)",
        target_agent,
        session.session_id,
        session.tmux_session_name,
    )

    stop_started = time.monotonic()
    stop_attempt = await _terminate_agent_process(session.tmux_session_name)
    stop_deadline = stop_started + _RESTART_STOP_TIMEOUT_S
    ready = await _wait_for_restart_barrier(
        session,
        stop_attempt=stop_attempt,
        stop_deadline=stop_deadline,
    )
    stop_elapsed_ms = int((time.monotonic() - stop_started) * 1000)
    if not ready:
        error = "Agent did not exit after termination. Restart aborted."
        await _log_restart_shell_ready_timeout(
            session,
            target_agent=target_agent,
            stop_attempt=stop_attempt,
            elapsed_ms=stop_elapsed_ms,
        )
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
            visibility=EventVisibility.CLUSTER,
        )
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

    restart_cmd = get_agent_command(
        agent=target_agent,
        thinking_mode=(session.thinking_mode if session.thinking_mode else "slow"),
        exec=False,
        native_session_id=native_session_id,
        profile=_get_session_profile(session),
    )

    if cmd.self_restart:
        # Subscribe BEFORE the restart paste — the agent's SessionStart hook
        # can race execute_terminal_command and emit AGENT_READY before the
        # wait task runs. event_bus has no replay; subscribing after the
        # launch loses the event.
        loop = asyncio.get_running_loop()
        ready_future: asyncio.Future[None] = loop.create_future()

        async def _on_ready(_event_type: str, ctx: SessionLifecycleContext) -> None:
            if ctx.session_id == session.session_id and not ready_future.done():
                ready_future.set_result(None)

        ready_handler = event_bus.subscribe(TeleClaudeEvents.AGENT_READY, _on_ready)

        await execute_terminal_command(session.session_id, restart_cmd, None, True)

        async def _inject_after_restart() -> None:
            try:
                try:
                    # Shared start/restart readiness combiner: races the pane-quiet
                    # detector against the native hook and synthesizes AGENT_READY on
                    # a pane-win (start-path parity). The gate winner is logged inside
                    # the helper.
                    gate_winner = await await_agent_readiness(
                        agent_name=target_agent,
                        session=session,
                        session_id=session.session_id,
                        ready_future=ready_future,
                        coordinator=client.agent_coordinator,
                        quiet_s=_RESTART_QUIET_S,
                        timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
                    )
                except TimeoutError:
                    logger.warning(
                        "agent_restart readiness timeout: session=%s timeout_s=%.1f — continuation stimulus not sent",
                        session.session_id,
                        AGENT_PROMPT_READY_TIMEOUT_S,
                    )
                    event_bus.emit(
                        TeleClaudeEvents.AGENT_READINESS_TIMEOUT,
                        SessionLifecycleContext(session_id=session.session_id),
                        visibility=EventVisibility.LOCAL,
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
                event_bus.unsubscribe(TeleClaudeEvents.AGENT_READY, ready_handler)

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

            # The agent has full context via --resume; it just needs a stimulus.
            logger.info(
                "agent_restart: sending continuation stimulus session=%s gate=%s",
                session.session_id,
                gate_winner.value,
            )
            delivered = await tmux_io.inject_user_turn(
                session,
                RESTART_CONTINUATION_STIMULUS,
                active_agent=target_agent,
            )
            if delivered:
                logger.info("agent_restart: continuation stimulus delivered session=%s", session.session_id)
                return
            logger.warning(
                "agent_restart: continuation stimulus not confirmed after retries session=%s",
                session.session_id,
            )
            event_bus.emit(
                TeleClaudeEvents.AGENT_READINESS_TIMEOUT,
                SessionLifecycleContext(session_id=session.session_id),
                visibility=EventVisibility.LOCAL,
            )
            await client.send_message(
                session,
                "Restart continuation stimulus could not be confirmed delivered. Session kept alive for inspection.",
            )

        asyncio.create_task(_inject_after_restart(), name="send-restart-stimulus")
    else:
        await execute_terminal_command(session.session_id, restart_cmd, None, True)

    event_bus.emit(
        cmd.completion_event,  # type: ignore[arg-type]
        AgentRestartDispatchedPayload(session_id=session.session_id),
        visibility=EventVisibility.CLUSTER,
    )

    return True, None


@with_session
async def run_agent_command(
    session: Session,
    cmd: RunAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> None:
    """Send a slash command directly to the running agent."""
    if not cmd.command:
        logger.warning("run_agent_command called without a command")
        return
    if session.active_agent:
        try:
            assert_agent_enabled(session.active_agent)
        except ValueError as exc:
            await client.send_message(session, str(exc))
            return
    if session.lifecycle_status == "headless" or not session.tmux_session_name:
        adopted = await _ensure_tmux_for_headless(
            session,
            client,
            None,
            resume_native=True,
        )
        if not adopted:
            return
        session = adopted

    command_text = f"/{cmd.command}".strip()
    if cmd.args:
        command_text = f"{command_text} {cmd.args}".strip()

    await db.update_session(
        session.session_id,
        last_message_sent=command_text[:200],
        last_message_sent_at=datetime.now(UTC).isoformat(),
        last_input_origin=cmd.origin,
    )

    await execute_terminal_command(session.session_id, command_text, None, True)
