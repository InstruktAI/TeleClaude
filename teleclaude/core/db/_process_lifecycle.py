"""Mixin: daemon-owned process lifecycle persistence helpers."""

from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import select

from .. import db_models


class DbProcessLifecycleMixin:
    """Process janitor policy and spawn registry persistence helpers."""

    async def list_process_janitor_policies(
        self, *, include_disabled: bool = False
    ) -> list[db_models.ProcessJanitorPolicy]:
        """Return process janitor policies, optionally including disabled rows."""
        stmt = select(db_models.ProcessJanitorPolicy)
        if not include_disabled:
            stmt = stmt.where(db_models.ProcessJanitorPolicy.enabled == 1)
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())

    async def upsert_process_janitor_policy(
        self,
        *,
        signature_id: str,
        name: str,
        matcher_kind: str,
        matcher_params_json: str,
        ttl_seconds: int,
        enabled: bool = True,
        dry_run: bool = False,
    ) -> None:
        """Insert or update one signature policy row."""
        now = datetime.now(UTC).isoformat()
        stmt = sqlite_insert(db_models.ProcessJanitorPolicy).values(
            signature_id=signature_id,
            name=name,
            matcher_kind=matcher_kind,
            matcher_params_json=matcher_params_json,
            ttl_seconds=ttl_seconds,
            enabled=1 if enabled else 0,
            dry_run=1 if dry_run else 0,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["signature_id"],
            set_={
                "name": stmt.excluded.name,
                "matcher_kind": stmt.excluded.matcher_kind,
                "matcher_params_json": stmt.excluded.matcher_params_json,
                "ttl_seconds": stmt.excluded.ttl_seconds,
                "enabled": stmt.excluded.enabled,
                "dry_run": stmt.excluded.dry_run,
                "updated_at": now,
            },
        )
        async with self._session() as db_session:
            await db_session.exec(stmt)
            await db_session.commit()

    async def get_process_spawn_registry_entry(self, owner: str) -> db_models.ProcessSpawnRegistryEntry | None:
        """Return one spawn registry entry by owner."""
        async with self._session() as db_session:
            return await db_session.get(db_models.ProcessSpawnRegistryEntry, owner)

    async def replace_process_spawn_registry_entry(
        self,
        *,
        owner: str,
        pid: int,
        lease_expires_at: str,
        registered_at: str | None = None,
    ) -> db_models.ProcessSpawnRegistryEntry | None:
        """Atomically replace the owner row and return the previous registrant."""
        registered = registered_at or datetime.now(UTC).isoformat()
        async with self._session() as db_session:
            previous = await db_session.get(db_models.ProcessSpawnRegistryEntry, owner)
            previous_copy = (
                db_models.ProcessSpawnRegistryEntry(
                    owner=previous.owner,
                    pid=previous.pid,
                    lease_expires_at=previous.lease_expires_at,
                    registered_at=previous.registered_at,
                )
                if previous is not None
                else None
            )
            row = db_models.ProcessSpawnRegistryEntry(
                owner=owner,
                pid=pid,
                lease_expires_at=lease_expires_at,
                registered_at=registered,
            )
            await db_session.merge(row)
            await db_session.commit()
            return previous_copy

    async def delete_process_spawn_registry_entry(self, owner: str) -> None:
        """Delete a spawn registry row by owner."""
        async with self._session() as db_session:
            await db_session.exec(
                delete(db_models.ProcessSpawnRegistryEntry).where(db_models.ProcessSpawnRegistryEntry.owner == owner)
            )
            await db_session.commit()

    async def list_expired_process_spawn_registry_entries(self, now: str) -> list[db_models.ProcessSpawnRegistryEntry]:
        """Return registry entries whose lease has expired."""
        stmt = select(db_models.ProcessSpawnRegistryEntry).where(
            db_models.ProcessSpawnRegistryEntry.lease_expires_at <= now
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())

    async def list_valid_process_spawn_registry_entries(self, now: str) -> list[db_models.ProcessSpawnRegistryEntry]:
        """Return registry entries whose lease is still valid."""
        stmt = select(db_models.ProcessSpawnRegistryEntry).where(
            db_models.ProcessSpawnRegistryEntry.lease_expires_at > now
        )
        async with self._session() as db_session:
            result = await db_session.exec(stmt)
            return list(result.all())
