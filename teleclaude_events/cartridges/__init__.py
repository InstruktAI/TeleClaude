"""Cartridges — pluggable pipeline processors."""

from teleclaude_events.cartridges.dedup import DeduplicationCartridge
from teleclaude_events.cartridges.notification import NotificationProjectorCartridge

__all__ = ["DeduplicationCartridge", "NotificationProjectorCartridge"]
