"""Cartridges — pluggable pipeline processors."""

from teleclaude_events.cartridges.classification import ClassificationCartridge
from teleclaude_events.cartridges.correlation import CorrelationCartridge
from teleclaude_events.cartridges.dedup import DeduplicationCartridge
from teleclaude_events.cartridges.enrichment import EnrichmentCartridge
from teleclaude_events.cartridges.integration_trigger import IntegrationTriggerCartridge
from teleclaude_events.cartridges.notification import NotificationProjectorCartridge
from teleclaude_events.cartridges.prepare_quality import PrepareQualityCartridge
from teleclaude_events.cartridges.trust import TrustCartridge

__all__ = [
    "ClassificationCartridge",
    "CorrelationCartridge",
    "DeduplicationCartridge",
    "EnrichmentCartridge",
    "IntegrationTriggerCartridge",
    "NotificationProjectorCartridge",
    "PrepareQualityCartridge",
    "TrustCartridge",
]
