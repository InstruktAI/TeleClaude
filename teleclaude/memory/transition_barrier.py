"""The record that the conversation-memory worker transition is complete on this computer.

No extraction is released until it is recorded: pre-transition and identity-addressed workers must never run for
one scope at once.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db

logger = get_logger(__name__)

_TRANSITION_COMPLETE_SETTING = "memory_extraction_transition_complete"
_TRANSITION_COMPLETE_VALUE = "true"
_TRANSITION_RECORDED_EVENT = "memory_extraction_transition_recorded"


async def transition_is_complete() -> bool:
    """Whether the transition to identity-addressed workers is recorded complete on this computer."""
    return await db.get_system_setting(_TRANSITION_COMPLETE_SETTING) == _TRANSITION_COMPLETE_VALUE


async def record_transition_complete() -> None:
    """Record that no pre-transition worker remains and extractions may be released."""
    await db.set_system_setting(_TRANSITION_COMPLETE_SETTING, _TRANSITION_COMPLETE_VALUE)
    logger.info(_TRANSITION_RECORDED_EVENT)
