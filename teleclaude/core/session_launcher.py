"""Session launch orchestration.

Public entry points:
1) create_empty_session
2) create_agent_session

All functions return session_id/tmux name immediately and queue any slow work.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine

from instrukt_ai_logging import get_logger

from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.command_handlers import create_session as create_tmux_session
from teleclaude.core.models import AgentDispatchMode, SessionLaunchIntent, SessionLaunchKind
from teleclaude.types.commands import CreateSessionCommand

logger = get_logger(__name__)

QueueTask = Callable[[Coroutine[object, object, object], str], None]
BootstrapSession = Callable[[str, SessionLaunchIntent | None], Coroutine[object, object, None]]


async def create_empty_session(
    cmd: CreateSessionCommand,
    client: AdapterClient,
) -> dict[str, str]:
    """Create a session without any launch work."""
    return await create_tmux_session(cmd, client)


async def create_agent_session(
    cmd: CreateSessionCommand,
    client: AdapterClient,
    queue_background_task: QueueTask,
    bootstrap_session: BootstrapSession,
) -> dict[str, str]:
    """Create a session and start agent-related bootstrap immediately."""
    return await _create_session_with_intent(
        cmd,
        client,
        queue_background_task,
        bootstrap_session,
    )


def _validate_launch_intent(intent: SessionLaunchIntent | None) -> None:
    if intent is None or intent.kind == SessionLaunchKind.EMPTY:
        return
    if intent.kind == SessionLaunchKind.AGENT:
        if intent.dispatch_mode is AgentDispatchMode.AUTOMATIC and not intent.agent:
            return
        if not intent.agent or not intent.thinking_mode:
            raise ValueError("agent launch_intent requires agent and thinking_mode")
        return
    if intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE:
        if not intent.agent or not intent.thinking_mode or intent.message is None:
            raise ValueError("agent_then_message launch_intent requires agent, thinking_mode, and message")
        return
    if intent.kind == SessionLaunchKind.AGENT_RESUME:
        if not intent.agent:
            raise ValueError("agent_resume launch_intent requires agent")
        return
    raise ValueError(f"Unsupported launch_intent kind: {intent.kind}")


async def _create_session_with_intent(
    cmd: CreateSessionCommand,
    client: AdapterClient,
    queue_background_task: QueueTask,
    bootstrap_session: BootstrapSession,
) -> dict[str, str]:
    result = await create_tmux_session(cmd, client)
    _validate_launch_intent(cmd.launch_intent)

    session_id_raw = result.get("session_id")
    if not session_id_raw:
        return result

    session_id = str(session_id_raw)
    queue_background_task(
        bootstrap_session(session_id, cmd.launch_intent),
        f"session_bootstrap:{session_id}",
    )
    logger.debug(
        "NEW_SESSION result: session_id=%s, launch_intent=%s",
        session_id,
        cmd.launch_intent.kind.value if cmd.launch_intent else SessionLaunchKind.EMPTY.value,
    )
    return result


async def create_session(
    cmd: CreateSessionCommand,
    client: AdapterClient,
    queue_background_task: QueueTask,
    bootstrap_session: BootstrapSession,
) -> dict[str, str]:
    """Dispatch to the appropriate session creation intent."""
    if cmd.headless:
        return await create_empty_session(cmd, client)

    intent = cmd.launch_intent
    if intent and intent.kind == SessionLaunchKind.AGENT:
        return await create_agent_session(
            cmd,
            client,
            queue_background_task,
            bootstrap_session,
        )
    return await _create_session_with_intent(
        cmd,
        client,
        queue_background_task,
        bootstrap_session,
    )
