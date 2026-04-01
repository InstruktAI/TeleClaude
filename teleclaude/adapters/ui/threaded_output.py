"""Threaded output dataclasses for UI adapters.

Shared data structures for append-only threaded message delivery with smart
pagination, continuation markers, and markdown-aware overflow splitting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OverflowPlan:
    """Plan for sealing one threaded output chunk and continuing with the remainder."""

    chunk: str
    split_idx: int
    next_state: Any  # opaque — owned by the adapter's markdown strategy


@dataclass(frozen=True)
class OverflowContext:
    """Inputs shared by the overflow planning helpers."""

    continuation_prefix: str
    continuation_state: Any  # opaque — owned by the adapter's markdown strategy
    available_for_content: int


@dataclass(frozen=True)
class ThreadDelivery:
    """Delivery inputs for the non-overflow threaded render path."""

    output_message_id: str | None
    multi_message: bool
