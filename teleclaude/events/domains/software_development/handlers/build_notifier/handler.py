"""Build notifier cartridge — surfaces build completion for developer notification."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.envelope import EventEnvelope
    from teleclaude.events.pipeline import PipelineContext


async def process(event: "EventEnvelope", context: "PipelineContext") -> "EventEnvelope | None":  # noqa: ARG001
    """Pass through build.completed events so the pipeline surfaces them to the developer."""
    return event
