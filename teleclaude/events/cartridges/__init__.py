"""Cartridges — pluggable pipeline processors."""

from teleclaude.events.cartridges.classification import ClassificationCartridge
from teleclaude.events.cartridges.dedup import DeduplicationCartridge
from teleclaude.events.cartridges.enrichment import EnrichmentCartridge
from teleclaude.events.cartridges.notification import NotificationProjectorCartridge
from teleclaude.events.cartridges.trust import TrustCartridge

__all__ = [
    "ClassificationCartridge",
    "DeduplicationCartridge",
    "EnrichmentCartridge",
    "NotificationProjectorCartridge",
    "TrustCartridge",
]
