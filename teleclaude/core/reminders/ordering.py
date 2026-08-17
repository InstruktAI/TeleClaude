"""Shared source-order contract for native and reminder projections."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum

from teleclaude.core.dates import ensure_utc


class ProjectionSourceKind(IntEnum):
    """Deterministic precedence for projection sources at the same instant."""

    NATIVE = 0
    REMINDER = 1


type ProjectionOrderKey = tuple[datetime, int, str]


def projection_order_key(
    *,
    occurred_at: datetime,
    source_kind: ProjectionSourceKind,
    stable_id: str | int,
) -> ProjectionOrderKey:
    """Return the canonical ``occurred_at, source_kind, stable_id`` key."""
    normalized_id = f"{stable_id:020d}" if isinstance(stable_id, int) else stable_id
    return ensure_utc(occurred_at), int(source_kind), normalized_id


def projection_source_key(*, source_kind: ProjectionSourceKind, stable_id: str | int) -> str:
    """Render a source identity without the ordering key's numeric padding."""
    return f"{source_kind.name.lower()}:{stable_id}"
