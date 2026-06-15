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


__all__ = ["DispatchClaim", "acquire_dispatch_claim", "list_dispatch_claims", "release_dispatch_claim"]
