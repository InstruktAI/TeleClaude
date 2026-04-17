"""Todo artifact persistence mixin."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core.todos_db._models import (
    ROADMAP_TABLE,
    TODO_ARTIFACT_TABLE,
    TODO_ARTIFACT_VERSION_TABLE,
    TodoArtifact,
    TodoArtifactVersion,
    TodoRoadmap,
)
from teleclaude.core.todos_db._rows import ArtifactVersionRow


def _sha256(content: str) -> str:
    """Return a stable content digest."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class TodosDbArtifactsMixin:
    """Read, write, and version todo artifacts."""

    _on_mutation: Callable[[], None]

    async def _resolve_artifact_id(self, slug: str, session: SqlAsyncSession) -> str:
        """Resolve slug to roadmap id for artifact reads. Prefers active/icebox, falls back to delivered."""
        result = await session.exec(
            select(TodoRoadmap.id)
            .where(ROADMAP_TABLE.c.slug == slug)
            .order_by(
                # active/icebox first, delivered last
                (ROADMAP_TABLE.c.status == "delivered").asc()
            )
            .limit(1)
        )
        roadmap_id = result.first()
        if roadmap_id is None:
            msg = f"No roadmap entry for slug {slug!r}"
            raise ValueError(msg)
        return str(roadmap_id)

    async def _ensure_artifact_id(self, slug: str, session: SqlAsyncSession) -> str:
        """Resolve slug to roadmap id for artifact writes. Raises if slug has no active roadmap entry."""
        result = await session.exec(
            select(TodoRoadmap)
            .where(ROADMAP_TABLE.c.slug == slug)
            .where(ROADMAP_TABLE.c.status != "delivered")
            .limit(1)
        )
        entry = result.first()
        if entry is not None:
            return entry.id

        msg = f"Cannot write artifact: no active roadmap entry for slug {slug!r}"
        raise ValueError(msg)

    async def read_artifact(self, slug: str, name: str) -> str:
        """Read artifact content. Returns empty string if not found."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            artifact = await session.get(TodoArtifact, (row_id, name))
            return artifact.content if artifact is not None else ""

    def _resolve_artifact_id_sync(self, slug: str) -> str:
        """Resolve slug to roadmap id for synchronous artifact operations."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            roadmap_id = session.exec(
                select(TodoRoadmap.id)
                .where(ROADMAP_TABLE.c.slug == slug)
                .order_by((ROADMAP_TABLE.c.status == "delivered").asc())
                .limit(1)
            ).first()
            if roadmap_id is None:
                msg = f"No roadmap entry for slug {slug!r}"
                raise ValueError(msg)
            return str(roadmap_id)

    def read_artifact_sync(self, slug: str, name: str) -> str:
        """Read artifact content synchronously. Returns empty string if not found."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            roadmap_id = session.exec(
                select(TodoRoadmap.id)
                .where(ROADMAP_TABLE.c.slug == slug)
                .order_by((ROADMAP_TABLE.c.status == "delivered").asc())
                .limit(1)
            ).first()
            if roadmap_id is None:
                msg = f"No roadmap entry for slug {slug!r}"
                raise ValueError(msg)
            artifact = session.get(TodoArtifact, (str(roadmap_id), name))
            return artifact.content if artifact is not None else ""

    async def write_artifact(  # pylint: disable=too-many-arguments
        self,
        slug: str,
        name: str,
        content: str,
        *,
        updated_by: str | None = None,
        session: SqlAsyncSession | None = None,
    ) -> None:
        """Upsert artifact content and append to version history."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            now = datetime.now(UTC).isoformat()
            digest = _sha256(content)
            row_id = await self._ensure_artifact_id(slug, db_session)

            db_session.add(
                TodoArtifactVersion(
                    id=row_id,
                    slug=slug,
                    name=name,
                    content=content,
                    digest=digest,
                    updated_by=updated_by,
                    created_at=now,
                )
            )

            artifact = await db_session.get(TodoArtifact, (row_id, name))
            if artifact is None:
                artifact = TodoArtifact(
                    id=row_id,
                    slug=slug,
                    name=name,
                    content=content,
                    digest=digest,
                    updated_by=updated_by,
                    updated_at=now,
                )
            else:
                artifact.slug = slug
                artifact.content = content
                artifact.digest = digest
                artifact.updated_by = updated_by
                artifact.updated_at = now
            db_session.add(artifact)

            if owns_session:
                await db_session.commit()
                self._on_mutation()
        finally:
            if owns_session:
                await db_session.close()

    def write_artifact_sync(
        self,
        slug: str,
        name: str,
        content: str,
        *,
        updated_by: str | None = None,
    ) -> None:
        """Upsert artifact content synchronously and append to version history."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            result = session.exec(
                select(TodoRoadmap)
                .where(ROADMAP_TABLE.c.slug == slug)
                .where(ROADMAP_TABLE.c.status != "delivered")
                .limit(1)
            )
            entry = result.first()
            if entry is None:
                msg = f"Cannot write artifact: no active roadmap entry for slug {slug!r}"
                raise ValueError(msg)

            now = datetime.now(UTC).isoformat()
            digest = _sha256(content)
            session.add(
                TodoArtifactVersion(
                    id=entry.id,
                    slug=slug,
                    name=name,
                    content=content,
                    digest=digest,
                    updated_by=updated_by,
                    created_at=now,
                )
            )

            artifact = session.get(TodoArtifact, (entry.id, name))
            if artifact is None:
                artifact = TodoArtifact(
                    id=entry.id,
                    slug=slug,
                    name=name,
                    content=content,
                    digest=digest,
                    updated_by=updated_by,
                    updated_at=now,
                )
            else:
                artifact.slug = slug
                artifact.content = content
                artifact.digest = digest
                artifact.updated_by = updated_by
                artifact.updated_at = now
            session.add(artifact)
            session.commit()
        self._on_mutation()

    async def artifact_digest(self, slug: str, name: str) -> str:
        """Return SHA-256 digest of current artifact content. Empty string if not found."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            artifact = await session.get(TodoArtifact, (row_id, name))
            return artifact.digest if artifact is not None else ""

    async def artifact_exists(self, slug: str, name: str) -> bool:
        """Check if an artifact exists for a slug."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            artifact = await session.get(TodoArtifact, (row_id, name))
            return artifact is not None

    async def list_artifacts(self, slug: str) -> list[str]:
        """Return artifact names for a slug."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            result = await session.exec(
                select(TodoArtifact.name).where(TODO_ARTIFACT_TABLE.c.id == row_id).order_by(TODO_ARTIFACT_TABLE.c.name)
            )
            return [str(name) for name in result.all()]

    async def artifact_versions(self, slug: str, name: str, *, limit: int = 50) -> list[ArtifactVersionRow]:
        """Return version history for an artifact, newest first."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            result = await session.exec(
                select(TodoArtifactVersion)
                .where(TODO_ARTIFACT_VERSION_TABLE.c.id == row_id)
                .where(TODO_ARTIFACT_VERSION_TABLE.c.name == name)
                .order_by(TODO_ARTIFACT_VERSION_TABLE.c.created_at.desc())
                .limit(limit)
            )
            return [
                ArtifactVersionRow(
                    content=version.content,
                    digest=version.digest,
                    updated_by=version.updated_by or "",
                    created_at=version.created_at,
                )
                for version in result.all()
            ]

    async def list_artifact_versions(self, slug: str, name: str, *, limit: int = 50) -> list[ArtifactVersionRow]:
        """Compatibility wrapper used by the SQLAlchemy migration spec."""
        return await self.artifact_versions(slug, name, limit=limit)

    async def delete_artifacts(self, slug: str, *, session: SqlAsyncSession | None = None) -> None:
        """Delete all artifacts and version history for a slug.

        No-op when the slug has no roadmap entry (already removed or never created).
        """
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            try:
                row_id = await self._resolve_artifact_id(slug, db_session)
            except ValueError:
                return  # no roadmap entry → nothing to delete

            artifacts = await db_session.exec(select(TodoArtifact).where(TodoArtifact.id == row_id))
            for artifact in artifacts.all():
                await db_session.delete(artifact)

            versions = await db_session.exec(select(TodoArtifactVersion).where(TodoArtifactVersion.id == row_id))
            for version in versions.all():
                await db_session.delete(version)

            if owns_session:
                await db_session.commit()
                self._on_mutation()
        finally:
            if owns_session:
                await db_session.close()
