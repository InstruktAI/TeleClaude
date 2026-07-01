"""Prepare state machine lifecycle events.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio

from teleclaude.events.envelope import EventLevel
from teleclaude.events.producer import emit_event
from teleclaude.session_identity import get_session_id


def _emit_prepare_event(event_type: str, payload: dict[str, str | list[str]]) -> None:
    """Emit a prepare lifecycle event, failing fast on emission errors."""

    async def _emit() -> None:
        slug = str(payload.get("slug", ""))
        description = f"prepare.{event_type.split('.')[-1]}: {slug}"
        await emit_event(
            event=event_type,
            source=f"orchestrator/{(get_session_id() or 'unknown')}",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            description=description,
            entity=slug,
            payload=dict(payload),
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_emit())
    else:
        loop.create_task(_emit(), name="prepare-event-emit")


__all__ = [
    "_emit_prepare_event",
]
