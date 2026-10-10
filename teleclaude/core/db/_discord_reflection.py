"""Database adapter for integration-owned Discord reflection state."""

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import select

from teleclaude.core import db_models
from teleclaude.core.integration.discord_admin_state import (
    DiscordArtifactKind,
    DiscordProvider,
    DiscordReflectionRecord,
    DiscordReflectionScope,
    DiscordScopeKind,
)


class DbDiscordReflectionMixin:
    """Persist Discord reflection records without leaking SQL rows to adapters."""

    async def get_discord_reflection(self, logical_key: str) -> DiscordReflectionRecord | None:
        """Read one Discord reflection record by its stable logical key."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.DiscordReflectionRow, (DiscordProvider.DISCORD.value, logical_key))
        return _to_record(row) if row is not None else None

    async def list_discord_reflections(
        self, scope: DiscordReflectionScope | None = None
    ) -> list[DiscordReflectionRecord]:
        """List records, optionally narrowed to one integration-owned scope."""
        statement = select(db_models.DiscordReflectionRow).where(
            db_models.DiscordReflectionRow.provider == DiscordProvider.DISCORD.value
        )
        if scope is not None:
            statement = statement.where(
                db_models.DiscordReflectionRow.scope_kind == scope.kind.value,
                db_models.DiscordReflectionRow.scope_value == scope.value,
            )
        async with self._session() as db_session:
            rows = (await db_session.exec(statement)).all()
        return [_to_record(row) for row in rows]

    async def upsert_discord_reflection(self, record: DiscordReflectionRecord) -> None:
        """Create or replace one observed provider binding by provider and logical key."""
        statement = sqlite_insert(db_models.DiscordReflectionRow).values(
            provider=record.provider.value,
            logical_key=record.logical_key,
            artifact_kind=record.artifact_kind.value,
            scope_kind=record.scope.kind.value,
            scope_value=record.scope.value,
            provider_id=record.provider_id,
            parent_provider_id=record.parent_provider_id,
            metadata_json=record.metadata_json,
            verified_at=record.verified_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["provider", "logical_key"],
            set_={
                "artifact_kind": statement.excluded.artifact_kind,
                "scope_kind": statement.excluded.scope_kind,
                "scope_value": statement.excluded.scope_value,
                "provider_id": statement.excluded.provider_id,
                "parent_provider_id": statement.excluded.parent_provider_id,
                "metadata_json": statement.excluded.metadata_json,
                "verified_at": statement.excluded.verified_at,
            },
        )
        async with self._session() as db_session:
            await db_session.exec(statement)
            await db_session.commit()

    async def touch_discord_reflection(self, logical_key: str, verified_at: datetime) -> None:
        """Advance the verified timestamp for an already-recorded artifact."""
        async with self._session() as db_session:
            row = await db_session.get(db_models.DiscordReflectionRow, (DiscordProvider.DISCORD.value, logical_key))
            if row is None:
                return
            row.verified_at = verified_at
            db_session.add(row)
            await db_session.commit()

    async def delete_discord_reflection(self, logical_key: str) -> None:
        """Remove one reflection record so a later natural reconciliation can recreate it."""
        statement = delete(db_models.DiscordReflectionRow).where(
            db_models.DiscordReflectionRow.provider == DiscordProvider.DISCORD.value,
            db_models.DiscordReflectionRow.logical_key == logical_key,
        )
        async with self._session() as db_session:
            await db_session.exec(statement)
            await db_session.commit()


def _to_record(row: db_models.DiscordReflectionRow) -> DiscordReflectionRecord:
    """Translate one database row into the integration-owned DTO."""
    return DiscordReflectionRecord(
        provider=DiscordProvider(row.provider),
        logical_key=row.logical_key,
        artifact_kind=DiscordArtifactKind(row.artifact_kind),
        scope=DiscordReflectionScope(kind=DiscordScopeKind(row.scope_kind), value=row.scope_value),
        provider_id=row.provider_id,
        parent_provider_id=row.parent_provider_id,
        metadata_json=row.metadata_json,
        verified_at=row.verified_at,
    )
