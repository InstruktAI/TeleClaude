"""Agent start, resume, restart, and run-command handlers."""

import asyncio
import shlex
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.core.agents import AgentName, assert_agent_enabled, get_agent_command
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import ErrorEventContext, TeleClaudeEvents
from teleclaude.core.models import AgentResumeArgs, AgentStartArgs, Session, ThinkingMode
from teleclaude.types.commands import (
    RestartAgentCommand,
    ResumeAgentCommand,
    RunAgentCommand,
    StartAgentCommand,
)

from ._keys import _ensure_tmux_for_headless
from ._utils import with_session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


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
    if user_args and user_args[0] in ThinkingMode._value2member_map_:
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

    await db.update_session(
        session.session_id,
        active_agent=agent_name,
        thinking_mode=start_args.thinking_mode.value,
        last_message_sent=truncated_prompt,
        last_message_sent_at=datetime.now(UTC).isoformat(),
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

    await db.update_session(session.session_id, active_agent=agent_name)

    await execute_terminal_command(session.session_id, command_str, None, True)


@with_session
async def agent_restart(
    session: Session,
    cmd: RestartAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> tuple[bool, str | None]:
    """Restart an AI agent in the session by resuming the native session."""
    from teleclaude.core import tmux_bridge, tmux_io

    active_agent = session.active_agent
    native_session_id = session.native_session_id

    target_agent = cmd.agent_name or active_agent
    if not target_agent:
        error = "Cannot restart agent: no active agent for this session."
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
        )
        await client.send_message(session, f"❌ {error}")
        return False, error

    if not native_session_id:
        error = "Cannot restart agent: no native session ID stored. Start the agent first."
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
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
        )
        await client.send_message(session, f"❌ {error}")
        return False, error

    logger.info(
        "Restarting agent %s in session %s (tmux: %s)",
        target_agent,
        session.session_id,
        session.tmux_session_name,
    )

    sent = await tmux_io.send_signal(session, "SIGINT")
    if sent:
        await asyncio.sleep(0.2)
        await tmux_io.send_signal(session, "SIGINT")
        await asyncio.sleep(0.5)

    ready = await tmux_io.wait_for_shell_ready(session)
    if not ready:
        error = "Agent did not exit after SIGINT. Restart aborted."
        logger.error("agent_restart failed to stop process (session=%s)", session.session_id)
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
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

    await execute_terminal_command(session.session_id, restart_cmd, None, True)

    async def _inject_checkpoint_after_restart() -> None:
        from teleclaude.core.checkpoint_dispatch import inject_checkpoint_if_needed

        await asyncio.sleep(5)
        await inject_checkpoint_if_needed(
            session.session_id,
            route="restart_tmux",
            include_elapsed_since_turn_start=False,
            default_agent=target_agent,
            get_session_cb=db.get_session,
            update_session_cb=db.update_session,
        )

    asyncio.create_task(_inject_checkpoint_after_restart())

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
