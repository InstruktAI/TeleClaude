"""Processor registry for mirror-related event fan-out."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.agents import AgentName
from teleclaude.core.models._adapter import SessionAdapterMetadata
from teleclaude.utils.transcript_discovery import build_source_identity, extract_session_id, in_session_root

from .generator import generate_mirror
from .store import get_session_context

logger = get_logger(__name__)

_ADAPTER_ORIGINS = frozenset({"telegram", "discord", "whatsapp"})


def _extract_channel_identifiers(origin: str | None, raw_json: str | None) -> dict[str, str]:
    """Extract platform-specific identifiers from adapter metadata JSON."""
    if not origin or origin not in _ADAPTER_ORIGINS or not raw_json:
        return {}
    try:
        adapter = SessionAdapterMetadata.from_json(raw_json)
    except (ValueError, KeyError, TypeError):
        return {}
    identifiers: dict[str, str] = {}
    ui = adapter.get_ui()
    if origin == "telegram":
        tg = ui.telegram
        if tg and tg.user_id is not None:
            identifiers["user_id"] = str(tg.user_id)
    elif origin == "discord":
        dc = ui.discord
        if dc:
            if dc.user_id is not None:
                identifiers["user_id"] = dc.user_id
            if dc.channel_id is not None:
                identifiers["channel_id"] = str(dc.channel_id)
    elif origin == "whatsapp":
        wa = ui.whatsapp
        if wa and wa.phone_number is not None:
            identifiers["phone_number"] = wa.phone_number
    return identifiers


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
    """Generate a mirror for a normalized event payload."""
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

    transcript_session_id = extract_session_id(Path(transcript_path), agent_name)

    channel_identifiers = _extract_channel_identifiers(context.last_input_origin, context.adapter_metadata_json)

    await generate_mirror(
        session_id=transcript_session_id,
        source_identity=build_source_identity(transcript_path, agent_name),
        transcript_path=transcript_path,
        agent_name=agent_name,
        computer=context.computer or config.computer.name,
        project=context.project or "",
        db=None,
        human_email=context.human_email,
        visibility=context.visibility or "private",
        last_input_origin=context.last_input_origin,
        channel_identifiers=channel_identifiers,
    )


def register_default_processors() -> None:
    """Register the default processor set."""
    register_processor(process_mirror_event)
