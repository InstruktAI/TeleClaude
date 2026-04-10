"""Helpdesk triage cartridge — classifies new tickets and surfaces for on-call notification."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude.events.envelope import EventEnvelope
    from teleclaude.events.pipeline import PipelineContext


async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
    """Pass through ticket_created events; guardian trust_threshold=strict controls autonomy."""
    return event
