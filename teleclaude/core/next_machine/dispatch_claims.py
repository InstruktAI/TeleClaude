"""Boot-gap dispatch claims for lifecycle runner spawns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, delete, select

from teleclaude.core.todos_db._models import TodoDispatchClaim

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

# The bug lane's diagnosis dispatch lease lane. Distinct from `RunnerLane`'s
# boot-gap dedup lanes (prepare, work, ...): this claim is not released when
# ownership moves to `active_runner` — the driving session keeps its claim for
# the whole phase — it exists solely so the artifact write boundary can admit
# the dispatched diagnosis peer for one artifact while its lease is live. See
# the Write authority contract in
# docs/project/spec/feature/workflow/artifact-versioning.md.
DIAGNOSIS_DISPATCH_LANE = "diagnosis"

# A diagnosis investigation plus its interrogation exchange runs inside one
# continuous working session and can run considerably longer than the
# short boot-gap dedup window other dispatch claims use. Generous but bounded:
# a peer that genuinely outlives this window stops writing (fail-closed)
# rather than holding the exemption open indefinitely.
DIAGNOSIS_LEASE_SECONDS = 4 * 60 * 60


@dataclass(frozen=True)
class DispatchClaim:
    """A held boot-gap claim for one slug/lane pair."""

    slug: str
    lane: str
    owner: str
    claimed_at: str
    expires_at: str


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat()


async def acquire_dispatch_claim(
    todos_db: TodosDb,
    *,
    slug: str,
    lane: str,
    owner: str,
    lease_seconds: int = 120,
) -> bool:
    """Acquire a short-lived `(slug, lane)` claim in the project todos DB."""
    now = _now()
    expires_at = now + timedelta(seconds=lease_seconds)
    async with todos_db._session() as session:  # pylint: disable=protected-access
        await session.exec(delete(TodoDispatchClaim).where(col(TodoDispatchClaim.expires_at) <= _iso(now)))
        session.add(
            TodoDispatchClaim(
                slug=slug,
                lane=lane,
                owner=owner,
                claimed_at=_iso(now),
                expires_at=_iso(expires_at),
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return False
    return True


async def release_dispatch_claim(todos_db: TodosDb, *, slug: str, lane: str, owner: str | None = None) -> bool:
    """Release a claim once ownership has moved to `active_runner`."""
    async with todos_db._session() as session:  # pylint: disable=protected-access
        stmt = delete(TodoDispatchClaim).where(
            col(TodoDispatchClaim.slug) == slug,
            col(TodoDispatchClaim.lane) == lane,
        )
        if owner is not None:
            stmt = stmt.where(col(TodoDispatchClaim.owner) == owner)
        result = await session.exec(stmt)
        await session.commit()
    return bool(result.rowcount)


async def get_dispatch_claim(todos_db: TodosDb, *, slug: str, lane: str) -> DispatchClaim | None:
    """Return the live `(slug, lane)` claim, or ``None`` if absent or expired.

    Sweeps expired claims first, so an expired-but-not-yet-swept row never
    reads as live: a lapsed claim and an absent one are indistinguishable to
    every caller of this primitive.
    """
    now = _iso(_now())
    async with todos_db._session() as session:  # pylint: disable=protected-access
        await session.exec(delete(TodoDispatchClaim).where(col(TodoDispatchClaim.expires_at) <= now))
        result = await session.exec(
            select(TodoDispatchClaim).where(
                col(TodoDispatchClaim.slug) == slug,
                col(TodoDispatchClaim.lane) == lane,
            )
        )
        await session.commit()
        claim = result.first()
    if claim is None:
        return None
    return DispatchClaim(
        slug=claim.slug,
        lane=claim.lane,
        owner=claim.owner,
        claimed_at=claim.claimed_at,
        expires_at=claim.expires_at,
    )


async def list_dispatch_claims(todos_db: TodosDb) -> list[DispatchClaim]:
    """Return current non-expired dispatch claims."""
    now = _iso(_now())
    async with todos_db._session() as session:  # pylint: disable=protected-access
        await session.exec(delete(TodoDispatchClaim).where(col(TodoDispatchClaim.expires_at) <= now))
        result = await session.exec(select(TodoDispatchClaim).order_by(TodoDispatchClaim.slug, TodoDispatchClaim.lane))
        await session.commit()
    return [
        DispatchClaim(
            slug=claim.slug,
            lane=claim.lane,
            owner=claim.owner,
            claimed_at=claim.claimed_at,
            expires_at=claim.expires_at,
        )
        for claim in result.all()
    ]


__all__ = [
    "DIAGNOSIS_DISPATCH_LANE",
    "DIAGNOSIS_LEASE_SECONDS",
    "DispatchClaim",
    "acquire_dispatch_claim",
    "get_dispatch_claim",
    "list_dispatch_claims",
    "release_dispatch_claim",
]
