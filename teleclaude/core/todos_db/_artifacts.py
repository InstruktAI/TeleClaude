"""Todo artifact persistence mixin."""

from __future__ import annotations

import difflib
import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger
from sqlalchemy import update
from sqlmodel import Session as SqlSession
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import TodoStatus
from teleclaude.core.next_machine.lifecycle import coerce_lifecycle_phase, is_work_lifecycle_phase
from teleclaude.core.todos_db._errors import ContractUnderExecutionRefused, HolderWriteRefused
from teleclaude.core.todos_db._identity_pin import apply_todo_identity_pin
from teleclaude.core.todos_db._models import (
    TODO_ARTIFACT_TABLE,
    TODO_ARTIFACT_VERSION_TABLE,
    TODO_TABLE,
    Todo,
    TodoArtifact,
    TodoArtifactVersion,
)
from teleclaude.core.todos_db._rows import (
    ArtifactMetadataRow,
    ArtifactRemovalResult,
    ArtifactVersionRow,
    ArtifactWritersRow,
)
from teleclaude.utils.transcript_discovery import as_session_id

logger = get_logger(__name__)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_PARAMETER_NAMES = ("old", "new")
_MALFORMED_DIGEST_DETAIL = (
    "Invalid {0} digest: expected 64 lowercase hexadecimal characters; received {1!r} (length {2})."
)


def malformed_digest_detail(old: str, new: str) -> str | None:
    """Describe the first malformed artifact-version digest, if any."""
    for parameter, digest in zip(_DIGEST_PARAMETER_NAMES, (old, new), strict=True):
        if not _DIGEST_RE.fullmatch(digest):
            return _MALFORMED_DIGEST_DETAIL.format(parameter, digest, len(digest))
    return None


def _sha256(content: str) -> str:
    """Return a stable content digest."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class TodosDbArtifactsMixin:
    """Read, write, and version todo artifacts."""

    _on_mutation: Callable[[str, Mapping[str, object] | None], None]
    db_path: str

    async def _resolve_artifact_id(
        self,
        slug: str,
        session: SqlAsyncSession,
        *,
        include_removed: bool = False,
    ) -> str | None:
        """Resolve slug to todo id for artifact reads. Returns None for unknown slugs.

        Prefers active/icebox, falls back to delivered. Read callers treat None as
        the absent case — mirroring the existing unknown-artifact-name convention
        of returning empty content / empty list / False. When ``include_removed``
        is true, the most recently removed entry is the final fallback. Write
        callers go through :meth:`_ensure_artifact_id` which raises instead.
        """
        result = await session.exec(
            apply_todo_identity_pin(
                select(Todo.id).where(TODO_TABLE.c.slug == slug),
                self,
                slug,
            )
            .where(TODO_TABLE.c.status != "removed")
            .order_by(
                # active/icebox first, delivered last
                (TODO_TABLE.c.status == "delivered").asc()
            )
            .limit(1)
        )
        todo_id = result.first()
        if todo_id is None and include_removed:
            removed_result = await session.exec(
                apply_todo_identity_pin(
                    select(Todo.id).where(TODO_TABLE.c.slug == slug),
                    self,
                    slug,
                )
                .where(TODO_TABLE.c.status == TodoStatus.REMOVED.value)
                .order_by(TODO_TABLE.c.removed_at.desc())
                .limit(1)
            )
            todo_id = removed_result.first()
        return str(todo_id) if todo_id is not None else None

    async def _is_artifact_holder_slug(self, session: SqlAsyncSession, slug: str) -> bool:
        """Return whether ``slug``'s live row has status ``holder``."""
        result = await session.exec(
            apply_todo_identity_pin(
                select(Todo.id).where(TODO_TABLE.c.slug == slug),
                self,
                slug,
            )
            .where(TODO_TABLE.c.status == TodoStatus.HOLDER.value)
            .limit(1)
        )
        return result.first() is not None

    async def _ensure_artifact_id(self, slug: str, session: SqlAsyncSession) -> str:
        """Resolve slug to todo id for artifact writes. Raises for unknown or delivered slugs.

        Distinguishes the two failure modes in the error message so the caller can tell
        whether the slug is unrecognized or merely frozen as ``delivered``.
        """
        result = await session.exec(
            apply_todo_identity_pin(
                select(Todo).where(TODO_TABLE.c.slug == slug),
                self,
                slug,
            )
            .where(TODO_TABLE.c.status.in_(("active", "icebox")))
            .limit(1)
        )
        entry = result.first()
        if entry is not None:
            return entry.id

        if await self._is_artifact_holder_slug(session, slug):
            raise HolderWriteRefused(f"Cannot write artifact: holder todo {slug!r} has frozen artifacts")

        delivered = await session.exec(
            apply_todo_identity_pin(
                select(Todo.id).where(TODO_TABLE.c.slug == slug),
                self,
                slug,
            )
            .where(TODO_TABLE.c.status == "delivered")
            .limit(1)
        )
        if delivered.first() is not None:
            raise ValueError(f"Cannot write artifact: todo {slug!r} is delivered (read-only)")
        raise ValueError(f"Cannot write artifact: unknown todo {slug!r}")

    async def _read_artifact_by_id(self, todo_id: str, name: str, session: SqlAsyncSession) -> str:
        artifact = await session.get(TodoArtifact, (todo_id, name))
        return artifact.content if artifact is not None else ""

    async def read_artifact_by_id(self, todo_id: str, name: str) -> str:
        """Read artifact content by the owning todo's durable id."""
        async with self._session() as session:  # type: ignore[attr-defined]
            return await self._read_artifact_by_id(todo_id, name, session)

    async def read_artifact(self, slug: str, name: str, *, include_removed: bool = False) -> str:
        """Read artifact content. Returns empty string for unknown slug or unknown name."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session, include_removed=include_removed)
            if row_id is None:
                return ""
            return await self._read_artifact_by_id(row_id, name, session)

    def _resolve_artifact_id_sync(self, slug: str) -> str | None:
        """Sync counterpart of :meth:`_resolve_artifact_id`. Returns None for unknown slugs."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            todo_id = session.exec(
                apply_todo_identity_pin(
                    select(Todo.id).where(TODO_TABLE.c.slug == slug),
                    self,
                    slug,
                )
                .where(TODO_TABLE.c.status != "removed")
                .order_by((TODO_TABLE.c.status == "delivered").asc())
                .limit(1)
            ).first()
            return str(todo_id) if todo_id is not None else None

    def read_artifact_sync(self, slug: str, name: str) -> str:
        """Read artifact content synchronously. Returns empty string for unknown slug or name."""
        todo_id = self._resolve_artifact_id_sync(slug)
        if todo_id is None:
            return ""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            return self._read_artifact_sync_by_id(todo_id, name, session)

    @staticmethod
    def _read_artifact_sync_by_id(todo_id: str, name: str, session: SqlSession) -> str:
        artifact = session.get(TodoArtifact, (todo_id, name))
        return artifact.content if artifact is not None else ""

    def read_artifact_sync_by_id(self, todo_id: str, name: str) -> str:
        """Read artifact content synchronously by the owning todo's durable id."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            return self._read_artifact_sync_by_id(todo_id, name, session)

    async def write_artifact(
        self,
        slug: str,
        name: str,
        content: str,
        *,
        updated_by: str | None = None,
        session: SqlAsyncSession | None = None,
        refuse_executing_contract: bool = False,
    ) -> None:
        """Upsert artifact content and append to version history.

        ``refuse_executing_contract`` refuses the write while the todo's stored lifecycle phase is a
        work-lane phase. A store-owned transaction takes the writer before it reads the phase, so a
        concurrent work entry either commits before the read and the write is refused, or commits
        after the write. A caller-owned session decides when its transaction takes the writer.
        """
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        updated_by = as_session_id(updated_by)
        try:
            now = datetime.now(UTC).isoformat()
            digest = _sha256(content)
            if refuse_executing_contract:
                if owns_session:
                    connection = await db_session.connection()
                    await connection.exec_driver_sql("BEGIN IMMEDIATE")
                state = await self.read_state_in_session(slug, db_session)  # type: ignore[attr-defined]
                phase = coerce_lifecycle_phase((state or {}).get("lifecycle_phase"))
                if phase is not None and is_work_lifecycle_phase(phase):
                    raise ContractUnderExecutionRefused(slug, phase.value)
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
                self._on_mutation("todo_updated", None)
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
        updated_by = as_session_id(updated_by)
        with self._sync_session() as session:  # type: ignore[attr-defined]
            result = session.exec(
                apply_todo_identity_pin(
                    select(Todo).where(TODO_TABLE.c.slug == slug),
                    self,
                    slug,
                )
                .where(TODO_TABLE.c.status.in_(("active", "icebox")))
                .limit(1)
            )
            entry = result.first()
            if entry is None:
                holder = session.exec(
                    apply_todo_identity_pin(
                        select(Todo.id).where(TODO_TABLE.c.slug == slug),
                        self,
                        slug,
                    )
                    .where(TODO_TABLE.c.status == TodoStatus.HOLDER.value)
                    .limit(1)
                ).first()
                if holder is not None:
                    raise HolderWriteRefused(f"Cannot write artifact: holder todo {slug!r} has frozen artifacts")
                delivered = session.exec(
                    apply_todo_identity_pin(
                        select(Todo.id).where(TODO_TABLE.c.slug == slug),
                        self,
                        slug,
                    )
                    .where(TODO_TABLE.c.status == "delivered")
                    .limit(1)
                ).first()
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
        self._on_mutation("todo_updated", None)

    async def artifact_digest(self, slug: str, name: str) -> str:
        """Return SHA-256 digest of current artifact content. Empty string for unknown slug or name."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            if row_id is None:
                return ""
            artifact = await session.get(TodoArtifact, (row_id, name))
            return artifact.digest if artifact is not None else ""

    def artifact_digest_sync(self, slug: str, name: str) -> str:
        """Synchronous current artifact digest read for worker-thread callers."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            digest = session.exec(
                select(TodoArtifact.digest)
                .where(TODO_ARTIFACT_TABLE.c.slug == slug, TODO_ARTIFACT_TABLE.c.name == name)
                .limit(1)
            ).first()
        return str(digest) if isinstance(digest, str) else ""

    def artifact_exists_sync(self, slug: str, name: str) -> bool:
        """Synchronous current artifact existence read."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            row = session.exec(
                select(TodoArtifact.id)
                .where(TODO_ARTIFACT_TABLE.c.slug == slug, TODO_ARTIFACT_TABLE.c.name == name)
                .limit(1)
            ).first()
        return row is not None

    async def artifact_digest_in_session(self, slug: str, name: str, session: SqlAsyncSession) -> str:
        """Read an artifact digest through a caller-owned transaction."""
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

    async def list_artifacts_with_writers(
        self, slug: str, *, include_removed: bool = False
    ) -> list[ArtifactWritersRow]:
        """Return every stored artifact for a slug with the distinct writers across its versions.

        Writers are ordered by the version that first recorded each, so a session that
        later repaired an artifact never displaces the one that created it. An artifact
        with no version rows is still present, with an empty writer set: the artifact
        table is the authority for which artifacts exist, and version history
        contributes writers only.
        """
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session, include_removed=include_removed)
            if row_id is None:
                return []
            names_result = await session.exec(
                select(TodoArtifact.name).where(TODO_ARTIFACT_TABLE.c.id == row_id).order_by(TODO_ARTIFACT_TABLE.c.name)
            )
            names = [str(name) for name in names_result.all()]

            versions_result = await session.exec(
                select(TodoArtifactVersion.name, TodoArtifactVersion.updated_by)
                .where(TODO_ARTIFACT_VERSION_TABLE.c.id == row_id)
                .order_by(TODO_ARTIFACT_VERSION_TABLE.c.created_at.asc())
            )
            writers_by_name: dict[str, list[str]] = {name: [] for name in names}
            for version_name, updated_by in versions_result.all():
                bucket = writers_by_name.get(str(version_name))
                if bucket is None:
                    continue
                writer = as_session_id(updated_by)
                if not writer or writer in bucket:
                    continue
                bucket.append(writer)

            return [ArtifactWritersRow(name=name, writers=writers_by_name[name]) for name in names]

    async def _artifact_metadata_by_id(self, todo_id: str, session: SqlAsyncSession) -> list[ArtifactMetadataRow]:
        result = await session.exec(
            select(TodoArtifact).where(TODO_ARTIFACT_TABLE.c.id == todo_id).order_by(TODO_ARTIFACT_TABLE.c.name)
        )
        return [
            ArtifactMetadataRow(
                name=artifact.name,
                digest=artifact.digest,
                updated_by=as_session_id(artifact.updated_by) or "",
                updated_at=artifact.updated_at or "",
            )
            for artifact in result.all()
        ]

    async def artifact_metadata_by_id(self, todo_id: str) -> list[ArtifactMetadataRow]:
        """Return current artifact metadata for a todo's durable id."""
        async with self._session() as session:  # type: ignore[attr-defined]
            return await self._artifact_metadata_by_id(todo_id, session)

    async def artifact_metadata(self, slug: str) -> list[ArtifactMetadataRow]:
        """Return current artifact metadata for a slug, ordered by artifact name."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session)
            if row_id is None:
                return []
            return await self._artifact_metadata_by_id(row_id, session)

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
                    updated_by=as_session_id(version.updated_by) or "",
                    created_at=version.created_at,
                )
                for version in result.all()
            ]

    async def list_artifact_versions(self, slug: str, name: str, *, limit: int = 50) -> list[ArtifactVersionRow]:
        """Compatibility wrapper used by the SQLAlchemy migration spec."""
        return await self.artifact_versions(slug, name, limit=limit)

    async def rename_artifacts_slug(
        self,
        old_slug: str,
        new_slug: str,
        *,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Re-key current artifact rows and version history for the live todo row."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            result = await db_session.exec(
                apply_todo_identity_pin(
                    select(Todo.id).where(TODO_TABLE.c.slug == old_slug),
                    self,
                    old_slug,
                )
                .where(TODO_TABLE.c.status.notin_(("delivered", "removed")))
                .limit(1)
            )
            row_id = result.one_or_none()
            if row_id is None:
                return False

            now = datetime.now(UTC).isoformat()
            await db_session.exec(
                update(TodoArtifact)
                .where(TODO_ARTIFACT_TABLE.c.id == str(row_id))
                .where(TODO_ARTIFACT_TABLE.c.slug == old_slug)
                .values(slug=new_slug, updated_at=now)
            )
            await db_session.exec(
                update(TodoArtifactVersion)
                .where(TODO_ARTIFACT_VERSION_TABLE.c.id == str(row_id))
                .where(TODO_ARTIFACT_VERSION_TABLE.c.slug == old_slug)
                .values(slug=new_slug)
            )

            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
            return True
        finally:
            if owns_session:
                await db_session.close()

    async def delete_artifact(
        self,
        slug: str,
        name: str,
        *,
        session: SqlAsyncSession | None = None,
    ) -> ArtifactRemovalResult:
        """Delete one named artifact and its version history for an active todo."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            if await self._is_artifact_holder_slug(db_session, slug):
                raise HolderWriteRefused(f"Cannot delete artifact: holder todo {slug!r} has frozen artifacts")
            row_id = await self._ensure_artifact_id(slug, db_session)

            artifact = await db_session.get(TodoArtifact, (row_id, name))
            versions = await db_session.exec(
                select(TodoArtifactVersion)
                .where(TODO_ARTIFACT_VERSION_TABLE.c.id == row_id)
                .where(TODO_ARTIFACT_VERSION_TABLE.c.name == name)
            )
            version_rows = list(versions.all())

            if artifact is None and not version_rows:
                return ArtifactRemovalResult(removed=False, versions_deleted=0)

            if artifact is not None:
                await db_session.delete(artifact)
            for version in version_rows:
                await db_session.delete(version)

            removed = artifact is not None or bool(version_rows)
            if owns_session:
                await db_session.commit()
                logger.info(
                    "todo artifact removed",
                    slug=slug,
                    artifact=name,
                    versions_deleted=len(version_rows),
                    mode="async",
                )
                self._on_mutation("todo_updated", None)
            return ArtifactRemovalResult(removed=removed, versions_deleted=len(version_rows))
        finally:
            if owns_session:
                await db_session.close()

    async def artifacts_diff(
        self,
        slug: str,
        name: str,
        old_digest: str,
        new_digest: str,
        *,
        include_removed: bool = False,
    ) -> str:
        """Return a unified diff between two artifact versions identified by digest.

        Returns an empty string when both digests refer to the same content. Raises
        ``ValueError`` when the slug is unknown or when either digest does not match
        a stored version — even when both digests are identical, the digest must
        still exist for the artifact, otherwise the caller is asking about a
        version we never had.
        """
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_artifact_id(slug, session, include_removed=include_removed)
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
            if await self._is_artifact_holder_slug(db_session, slug):
                raise HolderWriteRefused(f"Cannot delete artifacts: holder todo {slug!r} has frozen artifacts")
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
                self._on_mutation("todo_updated", None)
        finally:
            if owns_session:
                await db_session.close()
