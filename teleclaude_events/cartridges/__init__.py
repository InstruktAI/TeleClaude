"""Cartridges — pluggable pipeline processors."""

from teleclaude_events.cartridges.dedup import DeduplicationCartridge
from teleclaude_events.cartridges.integration_trigger import IntegrationTriggerCartridge
from teleclaude_events.cartridges.notification import NotificationProjectorCartridge
from teleclaude_events.cartridges.prepare_quality import PrepareQualityCartridge

__all__ = [
    "DeduplicationCartridge",
    "IntegrationTriggerCartridge",
    "NotificationProjectorCartridge",
    "PrepareQualityCartridge",
]
