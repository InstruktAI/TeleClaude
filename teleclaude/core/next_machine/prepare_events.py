"""Prepare state machine lifecycle events.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventLevel
from teleclaude.events.producer import emit_event
from teleclaude.session_identity import get_session_id

logger = get_logger(__name__)


def _emit_prepare_event(event_type: str, payload: dict[str, str | list[str]]) -> None:
    """Emit a best-effort prepare lifecycle notification.

    The event is published after the source-of-truth state is committed and has
    no correctness consumer, so an emission failure is logged at error level —
    surfacing a genuine producer/transport fault to the bug runner — and never
    propagated: a lost telemetry event must not crash the committed prepare flow.
    """

    async def _emit() -> None:
        slug = str(payload.get("slug", ""))
        description = f"prepare.{event_type.split('.')[-1]}: {slug}"
        try:
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
            logger.error("prepare event emission failed", event=event_type, slug=slug, exc_info=True)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_emit())
    else:
        loop.create_task(_emit(), name="prepare-event-emit")


__all__ = [
    "_emit_prepare_event",
]
