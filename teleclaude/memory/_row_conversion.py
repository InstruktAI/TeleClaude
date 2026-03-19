"""Shared SQL row conversion helpers for memory records."""

from __future__ import annotations

from teleclaude.core import db_models


def row_to_memory_observation(row: object) -> db_models.MemoryObservation:
    """Convert a raw SQL row to ``MemoryObservation``."""
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return db_models.MemoryObservation(**dict(mapping))
    if isinstance(row, tuple):
        return db_models.MemoryObservation(
            id=row[0],
            memory_session_id=row[1],
            project=row[2],
            type=row[3],
            title=row[4],
            subtitle=row[5],
            facts=row[6],
            narrative=row[7],
            concepts=row[8],
            files_read=row[9],
            files_modified=row[10],
            prompt_number=row[11],
            discovery_tokens=row[12],
            created_at=row[13],
            created_at_epoch=row[14],
            identity_key=row[15] if len(row) > 15 else None,
        )
    return row  # type: ignore[return-value]


def row_to_memory_summary(row: object) -> db_models.MemorySummary:
    """Convert a raw SQL row to ``MemorySummary``."""
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return db_models.MemorySummary(**dict(mapping))
    if isinstance(row, tuple):
        return db_models.MemorySummary(
            id=row[0],
            memory_session_id=row[1],
            project=row[2],
            request=row[3],
            investigated=row[4],
            learned=row[5],
            completed=row[6],
            next_steps=row[7],
            created_at=row[8],
            created_at_epoch=row[9],
        )
    return row  # type: ignore[return-value]
