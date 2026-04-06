"""Review gatekeeper cartridge — routes review requests and enforces SLA."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.envelope import EventEnvelope
    from teleclaude.events.pipeline import PipelineContext


async def process(event: "EventEnvelope", context: "PipelineContext") -> "EventEnvelope | None":  # noqa: ARG001
    """Pass through review_requested events; marked actionable in catalog for human routing."""
    return event
