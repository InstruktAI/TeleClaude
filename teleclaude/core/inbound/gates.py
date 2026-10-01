"""Bounded per-conversation state for the conversation seam: reply cooldowns and turn locks.

Strangers can open any number of conversations, so every map here is bounded
and evicts its oldest entries; nothing a stranger sends grows memory without
limit.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

# A miss's reply is sent at most once per conversation within this window.
NEUTRAL_REPLY_COOLDOWN = 600.0
# The most conversations whose reply cooldown is remembered at once.
REPLY_GATE_MAX_KEYS = 10_000
# The most idle conversation locks kept at once; held locks are never evicted.
CONVERSATION_LOCKS_MAX_KEYS = 10_000

Clock = Callable[[], float]


class CooldownGate:
    """Admit one event per key within a cooldown window, remembering a bounded set of keys."""

    def __init__(
        self,
        *,
        cooldown_s: float = NEUTRAL_REPLY_COOLDOWN,
        max_keys: int = REPLY_GATE_MAX_KEYS,
        clock: Clock = time.monotonic,
    ) -> None:
        self._cooldown_s = cooldown_s
        self._max_keys = max_keys
        self._clock = clock
        self._admitted_at: OrderedDict[str, float] = OrderedDict()

    def admit(self, key: str) -> bool:
        """Whether an event for ``key`` may happen now; admitting starts its window."""
        now = self._clock()
        last = self._admitted_at.get(key)
        if last is not None and now - last < self._cooldown_s:
            return False
        self._admitted_at[key] = now
        self._admitted_at.move_to_end(key)
        while len(self._admitted_at) > self._max_keys:
            self._admitted_at.popitem(last=False)
        return True


class ConversationLocks:
    """One lock per conversation, so its turns are decided one at a time on this computer."""

    def __init__(self, *, max_keys: int = CONVERSATION_LOCKS_MAX_KEYS) -> None:
        self._max_keys = max_keys
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        """Hold ``key``'s lock for one turn."""
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        self._locks.move_to_end(key)
        self._evict_idle()
        async with lock:
            yield

    def _evict_idle(self) -> None:
        if len(self._locks) <= self._max_keys:
            return
        for key in [key for key, lock in self._locks.items() if not lock.locked()]:
            if len(self._locks) <= self._max_keys:
                return
            del self._locks[key]


__all__ = [
    "CONVERSATION_LOCKS_MAX_KEYS",
    "NEUTRAL_REPLY_COOLDOWN",
    "REPLY_GATE_MAX_KEYS",
    "Clock",
    "ConversationLocks",
    "CooldownGate",
]
