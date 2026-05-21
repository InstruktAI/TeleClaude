"""Agent start, resume, restart, and run-command handlers."""

import asyncio
import shlex
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import HUMAN_ROLE_ADMIN, RESTART_CONTINUATION_STIMULUS
from teleclaude.core import tmux_bridge, tmux_io
from teleclaude.core.agent_readiness import WINNER_HOOK, race_for_readiness
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
from teleclaude.events.envelope import EventVisibility
from teleclaude.types.commands import RestartAgentCommand, ResumeAgentCommand, RunAgentCommand, StartAgentCommand

from ._keys import _ensure_tmux_for_headless
from ._utils import with_session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_THINKING_MODE_VALUES = {mode.value for mode in ThinkingMode}


def _get_session_profile(session: Session) -> str:
    """Determine agent profile based on human role."""
    if session.human_role == HUMAN_ROLE_ADMIN:
        return "default"
    return "restricted"


async def _await_restart_readiness(
    *,
    agent: str,
    session: Session,
    ready_future: asyncio.Future[None],
) -> None:
    """Race the hook AGENT_READY future against the pane-quiet detector.

    Hook delivery is fragile against daemon restarts, SQLite contention, and
    receiver subprocess churn — lag samples of 14s have been observed in
    production. The pane detector is independent (tmux capture-pane is OS-
    level state, decoupled from daemon health), so a hook-vs-pane race gives
    defense in depth: hook typically wins in healthy cases (sub-second),
    pane wins when the hook path is starved.

    Applied uniformly across Claude, Gemini, and Codex — every adapter now
    follows the same arbitration shape.

    Raises ``TimeoutError`` when neither detector resolves within
    ``AGENT_PROMPT_READY_TIMEOUT_S``.
    """
    result = await race_for_readiness(
        agent_name=agent,
        session=session,
        timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
        ready_future=ready_future,
        pane_task_name=f"agent-restart-readiness-pane:{session.session_id}",
        hook_task_name=f"agent-restart-readiness-hook:{session.session_id}",
    )
    if result.winner == WINNER_HOOK:
        logger.info(
            "readiness_winner",
            winner=WINNER_HOOK,
            adapter=agent,
            session_id=session.session_id,
            phase="restart",
            hook_lag_ms=int(result.elapsed_s * 1000),
        )
    else:
        logger.info(
            "readiness_winner",
            winner=result.winner,
            adapter=agent,
            session_id=session.session_id,
            phase="restart",
            elapsed_ms=int(result.elapsed_s * 1000),
        )


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

    now_iso = datetime.now(UTC).isoformat()
    if cmd.origin:
        await db.update_session(
            session.session_id,
            active_agent=agent_name,
            thinking_mode=start_args.thinking_mode.value,
            last_message_sent=truncated_prompt,
            last_message_sent_at=now_iso,
            last_input_origin=cmd.origin,
        )
    else:
        await db.update_session(
            session.session_id,
            active_agent=agent_name,
            thinking_mode=start_args.thinking_mode.value,
            last_message_sent=truncated_prompt,
            last_message_sent_at=now_iso,
        )

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


async def _terminate_agent_process(tmux_session_name: str) -> None:
    """Send SIGTERM directly to the agent process via its PID.

    tmux send-keys C-c goes through the terminal layer and gets swallowed
    when the agent is mid-tool-execution. Direct kill bypasses that.
    """
    logger.info("agent_restart: sending direct SIGTERM to agent in %s", tmux_session_name)
    pane_pid = await tmux_bridge.get_pane_pid(tmux_session_name)
    if not pane_pid:
        return
    child_procs = await asyncio.create_subprocess_exec(
        "pgrep",
        "-P",
        str(pane_pid),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await child_procs.communicate()
    if not stdout:
        return
    agent_pid = stdout.decode().strip().split("\n")[0].strip()
    if not agent_pid.isdigit():
        return
    logger.info("agent_restart: killing PID %s with SIGTERM", agent_pid)
    kill_proc = await asyncio.create_subprocess_exec(
        "kill",
        "-TERM",
        agent_pid,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await kill_proc.communicate()


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
        return False, error

    logger.info(
        "Restarting agent %s in session %s (tmux: %s)",
        target_agent,
        session.session_id,
        session.tmux_session_name,
    )

    await _terminate_agent_process(session.tmux_session_name)

    ready = await tmux_io.wait_for_shell_ready(session)
    if not ready:
        error = "Agent did not exit after SIGINT. Restart aborted."
        logger.error("agent_restart failed to stop process (session=%s)", session.session_id)
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
            visibility=EventVisibility.CLUSTER,
        )
        await client.send_message(session, f"❌ {error}")
        return False, error

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
                    await _await_restart_readiness(
                        agent=target_agent,
                        session=session,
                        ready_future=ready_future,
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
                    return
            finally:
                event_bus.unsubscribe(TeleClaudeEvents.AGENT_READY, ready_handler)
            # The agent has full context via --resume; it just needs a stimulus.
            await tmux_bridge.send_keys_existing_tmux(
                session_name=session.tmux_session_name or "",
                text=RESTART_CONTINUATION_STIMULUS,
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
