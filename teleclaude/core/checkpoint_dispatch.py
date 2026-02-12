"""Shared checkpoint dispatch logic for daemon-side tmux injection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.constants import CHECKPOINT_MESSAGE, CHECKPOINT_PREFIX
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.events import AgentHookEvents
from teleclaude.hooks.checkpoint_flags import is_checkpoint_disabled

logger = get_logger(__name__)


def _is_checkpoint_prompt(prompt: str) -> bool:
    prompt_clean = (prompt or "").strip()
    if not prompt_clean:
        return False
    if prompt_clean.startswith(CHECKPOINT_PREFIX):
        return True
    return prompt_clean == CHECKPOINT_MESSAGE.strip()


async def inject_checkpoint_if_needed(
    session_id: str,
    *,
    route: str,
    include_elapsed_since_turn_start: bool,
    default_agent: AgentName = AgentName.CLAUDE,
    get_session_cb: Callable[[str], Awaitable[object | None]] | None = None,
    update_session_cb: Callable[..., Awaitable[object]] | None = None,
) -> bool:
    """Inject a checkpoint message for daemon-managed agents when needed.

    Returns True when checkpoint was delivered to tmux; otherwise False.
    """
    if is_checkpoint_disabled(session_id):
        logger.debug("Checkpoint skipped (persistent clear flag) for session %s", session_id[:8])
        return False

    from teleclaude.core import tmux_bridge
    from teleclaude.hooks import checkpoint as checkpoint_module
    from teleclaude.utils import transcript as transcript_utils

    get_session = get_session_cb or db.get_session
    update_session = update_session_cb or db.update_session

    fresh = await get_session(session_id)
    if not fresh:
        return False

    tmux_name = fresh.tmux_session_name
    if not tmux_name:
        return False

    agent_name = str(fresh.active_agent or "")
    if agent_name in (AgentName.CLAUDE.value, AgentName.GEMINI.value):
        return False

    checkpoint_at = fresh.last_checkpoint_at
    message_at = fresh.last_message_sent_at
    now = datetime.now(timezone.utc)

    elapsed: float | None = None
    if include_elapsed_since_turn_start:
        turn_start = max(filter(None, [message_at, checkpoint_at]), default=None)
        if not turn_start:
            logger.debug("Checkpoint skipped (no turn start) for session %s", session_id[:8])
            return False
        elapsed = (now - turn_start).total_seconds()

    # Dedup for agents without TOOL_USE signal.
    agent_hooks = AgentHookEvents.HOOK_EVENT_MAP.get(agent_name, {})
    has_tool_use = AgentHookEvents.TOOL_USE in agent_hooks.values()
    if not has_tool_use:
        transcript_path = fresh.native_log_file
        if transcript_path:
            try:
                agent_enum = AgentName.from_str(agent_name)
                last_input = transcript_utils.extract_last_user_message(transcript_path, agent_enum) or ""
            except ValueError:
                last_input = ""
        else:
            last_input = ""
        if _is_checkpoint_prompt(last_input):
            logger.debug("Checkpoint skipped (last input was checkpoint) for %s session %s", agent_name, session_id[:8])
            return False

    transcript_path = fresh.native_log_file
    working_slug = getattr(fresh, "working_slug", None)
    project_path = str(getattr(fresh, "project_path", "") or "")
    if not project_path and transcript_path:
        project_path = transcript_utils.extract_workdir_from_transcript(transcript_path) or ""

    try:
        agent_enum_ckpt = AgentName.from_str(agent_name)
    except ValueError:
        agent_enum_ckpt = default_agent

    checkpoint_text = checkpoint_module.get_checkpoint_content(
        transcript_path=transcript_path,
        agent_name=agent_enum_ckpt,
        project_path=project_path,
        working_slug=working_slug,
        elapsed_since_turn_start_s=elapsed,
    )
    if not checkpoint_text:
        logger.debug(
            "Checkpoint skipped: no turn-local changes for session %s (transcript=%s)",
            session_id[:8],
            transcript_path or "<none>",
        )
        return False

    logger.info(
        "Checkpoint payload prepared",
        route=route,
        session=session_id[:8],
        agent=agent_name,
        transcript_present=bool(transcript_path),
        project_path=project_path or "",
        working_slug=working_slug or "",
        payload_len=len(checkpoint_text),
    )

    delivered = await tmux_bridge.send_keys_existing_tmux(
        session_name=tmux_name,
        text=checkpoint_text,
        send_enter=True,
    )
    if not delivered:
        logger.warning(
            "Checkpoint injection not delivered",
            route=route,
            session=session_id[:8],
            tmux_session=tmux_name,
            payload_len=len(checkpoint_text),
        )
        return False

    await update_session(session_id, last_checkpoint_at=now.isoformat())
    logger.debug("Checkpoint injected for session %s", session_id[:8])
    return True
