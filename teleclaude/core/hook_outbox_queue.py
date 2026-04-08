"""Queue-state types for daemon hook outbox processing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from teleclaude.core.db import HookOutboxRow


@dataclass
class HookOutboxQueueItem:
    """In-memory queue payload for per-session hook outbox processing."""

    row: HookOutboxRow
    event_type: str
    classification: Literal["critical", "bursty"]


@dataclass
class HookOutboxSessionQueue:
    """Per-session hook queue state."""

    pending: list[HookOutboxQueueItem] = field(default_factory=list)
    claimed_row_ids: set[int] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    notify: asyncio.Event = field(default_factory=asyncio.Event)
