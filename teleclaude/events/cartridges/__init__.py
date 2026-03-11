"""Cartridges — pluggable pipeline processors."""

from teleclaude.events.cartridges.classification import ClassificationCartridge
from teleclaude.events.cartridges.correlation import CorrelationCartridge
from teleclaude.events.cartridges.dedup import DeduplicationCartridge
from teleclaude.events.cartridges.enrichment import EnrichmentCartridge
from teleclaude.events.cartridges.integration_trigger import IntegrationTriggerCartridge
from teleclaude.events.cartridges.notification import NotificationProjectorCartridge
from teleclaude.events.cartridges.prepare_quality import PrepareQualityCartridge
from teleclaude.events.cartridges.trust import TrustCartridge

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
