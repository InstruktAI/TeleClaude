"""Prepare state machine lifecycle events.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio

from teleclaude.events.envelope import EventLevel
from teleclaude.events.producer import emit_event
from teleclaude.session_identity import get_session_id


def _emit_prepare_event(event_type: str, payload: dict[str, str | list[str]]) -> None:
    """Fire-and-forget lifecycle event emission for prepare state machine."""

    async def _emit() -> None:
        try:
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
        except Exception:
            pass  # Never block prepare on event emission failure

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_emit(), name="prepare-event-emit")
    except RuntimeError:
        # No running loop (thread or sync CLI context) — fire-and-forget via new event loop
        try:
            asyncio.run(_emit())
        except Exception:
            pass  # Never block prepare on event emission failure


__all__ = [
    "_emit_prepare_event",
]
