"""Event handlers that fan out to registered mirror processors."""

from __future__ import annotations

import asyncio

from instrukt_ai_logging import get_logger

from teleclaude.core.events import AgentEventContext, SessionLifecycleContext

from .processors import MirrorEvent, get_processors

logger = get_logger(__name__)


async def _dispatch(event: MirrorEvent) -> None:
    processors = get_processors()
    if not processors:
        return
    results = await asyncio.gather(*(processor(event) for processor in processors), return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error("Mirror processor failed: %s", result, exc_info=result)


async def handle_agent_stop(context: AgentEventContext) -> None:
    """Dispatch AGENT_STOP mirror processors after coordinator work completes."""
    payload = context.data
    await _dispatch(
        MirrorEvent(session_id=context.session_id, transcript_path=getattr(payload, "transcript_path", None))
    )


async def handle_session_closed(context: SessionLifecycleContext) -> None:
    """Dispatch SESSION_CLOSED mirror processors."""
    await _dispatch(MirrorEvent(session_id=context.session_id, transcript_path=None))
