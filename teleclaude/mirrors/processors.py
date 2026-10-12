"""Processor registry for mirror-related event fan-out."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript_discovery import in_session_root, is_subagent_transcript

from .closure import refresh_and_report_coverage
from .generator import MirrorWriteTrigger
from .session_context import get_session_context

logger = get_logger(__name__)


@dataclass(frozen=True)
class MirrorEvent:
    """Normalized event payload for fan-out processors."""

    session_id: str | None
    transcript_path: str | None


MirrorProcessor = Callable[[MirrorEvent], Awaitable[None]]

_processors: list[MirrorProcessor] = []


def register_processor(processor: MirrorProcessor) -> None:
    """Register a processor once."""
    if processor in _processors:
        return
    _processors.append(processor)


def get_processors() -> list[MirrorProcessor]:
    """Return the registered processors."""
    return list(_processors)


async def process_mirror_event(event: MirrorEvent) -> None:
    """Refresh the session-owned mirror of the session a normalized event payload names."""
    context = get_session_context(session_id=event.session_id, transcript_path=event.transcript_path)
    if context is None:
        logger.debug("Mirror processor skipped: session context missing", session_id=event.session_id)
        return
    transcript_path = event.transcript_path or context.transcript_path
    if not transcript_path:
        logger.debug("Mirror processor skipped: transcript path missing", session_id=context.session_id)
        return
    if not context.agent:
        logger.debug("Mirror processor skipped: agent missing", session_id=context.session_id)
        return
    try:
        agent_name = AgentName(context.agent)
    except ValueError:
        logger.warning("Mirror processor skipped unknown agent %s for %s", context.agent, context.session_id)
        return
    if not in_session_root(transcript_path, agent_name):
        logger.debug("Mirror processor skipped non-canonical transcript", transcript_path=transcript_path)
        return
    if is_subagent_transcript(Path(transcript_path), agent_name):
        logger.info(
            "mirror.fanout.skipped",
            reason="subagent_transcript",
            transcript_path=transcript_path,
            session_id=context.session_id,
        )
        return

    await refresh_and_report_coverage(context.session_id, MirrorWriteTrigger.FANOUT)


def register_default_processors() -> None:
    """Register the default processor set."""
    register_processor(process_mirror_event)
