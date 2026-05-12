"""Todo artifact persistence mixin."""

from __future__ import annotations

import difflib
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger
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

logger = get_logger(__name__)


def _sha256(content: str) -> str:
    """Return a stable content digest."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class TodosDbArtifactsMixin:
    """Read, write, and version todo artifacts."""

    _on_mutation: Callable[[str], None]

    async def _resolve_artifact_id(self, slug: str, session: SqlAsyncSession) -> str | None:
        """Resolve slug to roadmap id for artifact reads. Returns None for unknown slugs.

        Prefers active/icebox, falls back to delivered. Read callers treat None as
        the absent case — mirroring the existing unknown-artifact-name convention
        of returning empty content / empty list / False. Write callers go through
        :meth:`_ensure_artifact_id` which raises instead.
        """
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
        return str(roadmap_id) if roadmap_id is not None else None

    async def _ensure_artifact_id(self, slug: str, session: SqlAsyncSession) -> str:
        """Resolve slug to roadmap id for artifact writes. Raises for unknown or delivered slugs.

        Distinguishes the two failure modes in the error message so the caller can tell
        whether the slug is unrecognized or merely frozen as ``delivered``.
        """
        result = await session.exec(
            select(TodoRoadmap)
            .where(ROADMAP_TABLE.c.slug == slug)
            .where(ROADMAP_TABLE.c.status != "delivered")
            .limit(1)
        )
        entry = result.first()
        if entry is not None:
            return entry.id

        delivered = await session.exec(select(TodoRoadmap.id).where(ROADMAP_TABLE.c.slug == slug).limit(1))
        if delivered.first() is not None:
            raise ValueError(f"Cannot write artifact: todo {slug!r} is delivered (read-only)")
        raise ValueError(f"Cannot write artifact: unknown todo {slug!r}")

    async def read_artifact(self, slug: str, name: str) -> str:
        """Read artifact content. Returns empty string for unknown slug or unknown name."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            if row_id is None:
                return ""
            artifact = await session.get(TodoArtifact, (row_id, name))
            return artifact.content if artifact is not None else ""

    def _resolve_artifact_id_sync(self, slug: str) -> str | None:
        """Sync counterpart of :meth:`_resolve_artifact_id`. Returns None for unknown slugs."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            roadmap_id = session.exec(
                select(TodoRoadmap.id)
                .where(ROADMAP_TABLE.c.slug == slug)
                .order_by((ROADMAP_TABLE.c.status == "delivered").asc())
                .limit(1)
            ).first()
            return str(roadmap_id) if roadmap_id is not None else None

    def read_artifact_sync(self, slug: str, name: str) -> str:
        """Read artifact content synchronously. Returns empty string for unknown slug or name."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            roadmap_id = session.exec(
                select(TodoRoadmap.id)
                .where(ROADMAP_TABLE.c.slug == slug)
                .order_by((ROADMAP_TABLE.c.status == "delivered").asc())
                .limit(1)
            ).first()
            if roadmap_id is None:
                return ""
            artifact = session.get(TodoArtifact, (str(roadmap_id), name))
            return artifact.content if artifact is not None else ""

    async def write_artifact(
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
                logger.info(
                    "todo artifact written",
                    slug=slug,
                    artifact=name,
                    updated_by=updated_by or "",
                    digest=digest,
                    mode="async",
                )
                self._on_mutation("todo_updated")
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
                delivered = session.exec(select(TodoRoadmap.id).where(ROADMAP_TABLE.c.slug == slug).limit(1)).first()
                if delivered is not None:
                    raise ValueError(f"Cannot write artifact: todo {slug!r} is delivered (read-only)")
                raise ValueError(f"Cannot write artifact: unknown todo {slug!r}")

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
        logger.info(
            "todo artifact written",
            slug=slug,
            artifact=name,
            updated_by=updated_by or "",
            digest=digest,
            mode="sync",
        )
        self._on_mutation("todo_updated")

    async def artifact_digest(self, slug: str, name: str) -> str:
        """Return SHA-256 digest of current artifact content. Empty string for unknown slug or name."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            if row_id is None:
                return ""
            artifact = await session.get(TodoArtifact, (row_id, name))
            return artifact.digest if artifact is not None else ""

    async def artifact_exists(self, slug: str, name: str) -> bool:
        """Check if an artifact exists for a slug. False for unknown slug or name."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            if row_id is None:
                return False
            artifact = await session.get(TodoArtifact, (row_id, name))
            return artifact is not None

    async def list_artifacts(self, slug: str) -> list[str]:
        """Return artifact names for a slug. Empty list for unknown slug."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            if row_id is None:
                return []
            result = await session.exec(
                select(TodoArtifact.name).where(TODO_ARTIFACT_TABLE.c.id == row_id).order_by(TODO_ARTIFACT_TABLE.c.name)
            )
            return [str(name) for name in result.all()]

    async def artifact_versions(self, slug: str, name: str, *, limit: int = 50) -> list[ArtifactVersionRow]:
        """Return version history for an artifact, newest first. Empty list for unknown slug."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            if row_id is None:
                return []
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

    async def artifacts_diff(self, slug: str, name: str, old_digest: str, new_digest: str) -> str:
        """Return a unified diff between two artifact versions identified by digest.

        Returns an empty string when both digests refer to the same content. Raises
        ``ValueError`` when the slug is unknown or when either digest does not match
        a stored version — even when both digests are identical, the digest must
        still exist for the artifact, otherwise the caller is asking about a
        version we never had.
        """
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            if row_id is None:
                raise ValueError(f"Unknown todo: {slug!r}")
            target_digests = list({old_digest, new_digest})
            result = await session.exec(
                select(TodoArtifactVersion)
                .where(TODO_ARTIFACT_VERSION_TABLE.c.id == row_id)
                .where(TODO_ARTIFACT_VERSION_TABLE.c.name == name)
                .where(TODO_ARTIFACT_VERSION_TABLE.c.digest.in_(target_digests))
            )
            by_digest = {version.digest: version.content for version in result.all()}

        if old_digest not in by_digest:
            msg = f"no version with digest {old_digest!r} for artifact {name!r} of slug {slug!r}"
            raise ValueError(msg)
        if new_digest not in by_digest:
            msg = f"no version with digest {new_digest!r} for artifact {name!r} of slug {slug!r}"
            raise ValueError(msg)

        if old_digest == new_digest:
            return ""

        old_lines = by_digest[old_digest].splitlines(keepends=True)
        new_lines = by_digest[new_digest].splitlines(keepends=True)
        diff_lines = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"{name}@{old_digest[:12]}",
            tofile=f"{name}@{new_digest[:12]}",
        )
        return "".join(diff_lines)

    async def delete_artifacts(self, slug: str, *, session: SqlAsyncSession | None = None) -> None:
        """Delete all artifacts and version history for a slug.

        No-op when the slug is unknown (already removed or never created).
        """
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            row_id = await self._resolve_artifact_id(slug, db_session)
            if row_id is None:
                return  # unknown slug → nothing to delete

            artifacts = await db_session.exec(select(TodoArtifact).where(TodoArtifact.id == row_id))
            for artifact in artifacts.all():
                await db_session.delete(artifact)

            versions = await db_session.exec(select(TodoArtifactVersion).where(TodoArtifactVersion.id == row_id))
            for version in versions.all():
                await db_session.delete(version)

            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated")
        finally:
            if owns_session:
                await db_session.close()
