"""Session launch orchestration.

Public entry points:
1) create_empty_session
2) create_agent_session
3) create_agent_session_with_auto_command

All functions return session_id/tmux name immediately and queue any slow work.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Coroutine

from instrukt_ai_logging import get_logger

from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.command_handlers import handle_create_session
from teleclaude.core.events import EventContext
from teleclaude.core.models import MessageMetadata, SessionLaunchIntent, SessionLaunchKind

logger = get_logger(__name__)

QueueTask = Callable[[Coroutine[object, object, object], str], None]
ExecuteAuto = Callable[[str, str], Coroutine[object, object, dict[str, str]]]


async def create_empty_session(
    context: EventContext,
    args: list[str],
    metadata: MessageMetadata,
    client: AdapterClient,
) -> dict[str, str]:
    """Create a session without auto commands."""
    return await handle_create_session(context, args, metadata, client)


async def create_agent_session(
    context: EventContext,
    args: list[str],
    metadata: MessageMetadata,
    client: AdapterClient,
    execute_auto_command: ExecuteAuto,
    queue_background_task: QueueTask,
) -> dict[str, str]:
    """Create a session and start agent immediately (async)."""
    return await _create_session_with_intent(
        context,
        args,
        metadata,
        client,
        execute_auto_command,
        queue_background_task,
    )


async def create_agent_session_with_auto_command(
    context: EventContext,
    args: list[str],
    metadata: MessageMetadata,
    client: AdapterClient,
    execute_auto_command: ExecuteAuto,
    queue_background_task: QueueTask,
) -> dict[str, str]:
    """Create a session and run auto_command (async)."""
    return await _create_session_with_intent(
        context,
        args,
        metadata,
        client,
        execute_auto_command,
        queue_background_task,
    )


def _intent_to_auto_command(intent: SessionLaunchIntent) -> str | None:
    if intent.kind == SessionLaunchKind.EMPTY:
        return None
    if intent.kind == SessionLaunchKind.AGENT:
        if not intent.agent or not intent.thinking_mode:
            return None
        return f"agent {intent.agent} {intent.thinking_mode}"
    if intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE:
        if not intent.agent or not intent.thinking_mode or intent.message is None:
            return None
        quoted_message = shlex.quote(intent.message)
        return f"agent_then_message {intent.agent} {intent.thinking_mode} {quoted_message}"
    if intent.kind == SessionLaunchKind.AGENT_RESUME:
        if not intent.agent:
            return None
        if intent.native_session_id:
            return f"agent_resume {intent.agent} {intent.native_session_id}"
        return f"agent_resume {intent.agent}"
    return None


async def _create_session_with_intent(
    context: EventContext,
    args: list[str],
    metadata: MessageMetadata,
    client: AdapterClient,
    execute_auto_command: ExecuteAuto,
    queue_background_task: QueueTask,
) -> dict[str, str]:
    result = await handle_create_session(context, args, metadata, client)

    intent = metadata.launch_intent
    auto_command = metadata.auto_command or (_intent_to_auto_command(intent) if intent else None)
    if not auto_command or not result.get("session_id"):
        return result

    session_id = str(result["session_id"])
    logger.debug(
        "NEW_SESSION result: session_id=%s, auto_command=%s",
        session_id,
        auto_command,
    )

    if metadata.adapter_type in ("redis", "mcp"):
        queue_background_task(
            execute_auto_command(session_id, auto_command),
            f"auto_command:{session_id[:8]}",
        )
        result["auto_command_status"] = "queued"
        result["auto_command_message"] = "Auto-command queued"
    else:
        auto_result = await execute_auto_command(session_id, auto_command)
        result["auto_command_status"] = auto_result.get("status", "error")
        if auto_result.get("message"):
            result["auto_command_message"] = auto_result["message"]

    return result


async def create_session(
    context: EventContext,
    args: list[str],
    metadata: MessageMetadata,
    client: AdapterClient,
    execute_auto_command: ExecuteAuto,
    queue_background_task: QueueTask,
) -> dict[str, str]:
    """Dispatch to the appropriate session creation intent."""
    intent = metadata.launch_intent
    if not intent or intent.kind == SessionLaunchKind.EMPTY:
        if metadata.auto_command:
            return await create_agent_session_with_auto_command(
                context,
                args,
                metadata,
                client,
                execute_auto_command,
                queue_background_task,
            )
        return await create_empty_session(context, args, metadata, client)
    if intent.kind == SessionLaunchKind.AGENT:
        return await create_agent_session(
            context,
            args,
            metadata,
            client,
            execute_auto_command,
            queue_background_task,
        )
    return await create_agent_session_with_auto_command(
        context,
        args,
        metadata,
        client,
        execute_auto_command,
        queue_background_task,
    )
