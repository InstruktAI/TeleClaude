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


def _delivery_options_from_kwargs(delivery_kwargs: MutableMapping[str, object]) -> DeliveryOptions:
    """Normalize delivery kwargs while preserving the legacy call surface for tests."""
    options = delivery_kwargs.pop("options", None)
    if isinstance(options, DeliveryOptions):
        return options
    return DeliveryOptions(
        multi_message=bool(delivery_kwargs.get("multi_message", False)),
        dedupe_by_digest=bool(delivery_kwargs.get("dedupe_by_digest", True)),
    )
