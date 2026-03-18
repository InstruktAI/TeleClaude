"""Support types and lock helpers for next-work orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import _SINGLE_FLIGHT_GUARD, FinalizeState, StateValue
from teleclaude.core.next_machine.slug_resolution import resolve_canonical_project_root

_SINGLE_FLIGHT_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


@dataclass(frozen=True)
class DispatchState:
    """Current build/review/finalize status loaded from worktree state."""

    state: dict[str, StateValue]
    build_status: str
    review_status: str
    finalize_state: FinalizeState


@dataclass(frozen=True)
class ResolutionContext:
    """Inputs for explicit-slug readiness validation."""

    cwd: str
    slug: str
    deps: object
    is_bug: bool
    phase_slug: str
    started_at: float


@dataclass(frozen=True)
class WorkDispatchContext:
    """Common dispatch inputs shared across next-work routing branches."""

    db: Db
    cwd: str
    worktree_cwd: str
    resolved_slug: str
    phase_slug: str
    dispatch_started: float


@dataclass(frozen=True)
class GateContext:
    """Inputs for build gate and artifact verification checks."""

    worktree_cwd: str
    resolved_slug: str
    phase_slug: str
    review_round: int


@dataclass(frozen=True)
class ReviewRepairContext:
    """Inputs for stale-review approval repair checks."""

    worktree_cwd: str
    resolved_slug: str
    phase_slug: str


async def get_slug_single_flight_lock(cwd: str, slug: str) -> asyncio.Lock:
    """Return repo+slug lock keyed by canonical project root for strict isolation."""
    canonical_cwd = await asyncio.to_thread(resolve_canonical_project_root, cwd)
    key = (canonical_cwd, slug)
    with _SINGLE_FLIGHT_GUARD:
        lock = _SINGLE_FLIGHT_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _SINGLE_FLIGHT_LOCKS[key] = lock
    return lock
