"""Output delivery dataclasses and helpers for UI adapters.

Shared data structures and utility functions for output delivery logic.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass

__all__ = ["DeliveryOptions", "_delivery_options_from_kwargs"]


@dataclass(frozen=True)
class DeliveryOptions:
    """Delivery flags shared between the lock wrapper and unlocked implementation."""

    multi_message: bool = False
    dedupe_by_digest: bool = True
    # The generation this render was computed against. When set, the edit
    # path refuses to apply if the session's current generation has since
    # advanced — an older-turn snapshot must never edit the next turn's
    # message, even if it arrives after a later input was accepted.
    generation_id: str | None = None


def _delivery_options_from_kwargs(delivery_kwargs: MutableMapping[str, object]) -> DeliveryOptions:
    """Normalize delivery kwargs while preserving the legacy call surface for tests."""
    options = delivery_kwargs.pop("options", None)
    if isinstance(options, DeliveryOptions):
        return options
    generation_id = delivery_kwargs.get("generation_id")
    return DeliveryOptions(
        multi_message=bool(delivery_kwargs.get("multi_message", False)),
        dedupe_by_digest=bool(delivery_kwargs.get("dedupe_by_digest", True)),
        generation_id=generation_id if isinstance(generation_id, str) else None,
    )
