"""Roadmap persistence mixin."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from sqlalchemy import delete, func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import ARTIFACT_INPUT
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.todos_db._base import _generate_id
from teleclaude.core.todos_db._exceptions import RemoveRefused
from teleclaude.core.todos_db._models import (
    ROADMAP_DEPS_TABLE,
    ROADMAP_TABLE,
    TODO_ARTIFACT_TABLE,
    TODO_ARTIFACT_VERSION_TABLE,
    TODO_STATE_TABLE,
    RoadmapDep,
    TodoArtifact,
    TodoArtifactVersion,
    TodoRoadmap,
    TodoStateModel,
)
from teleclaude.core.todos_db._rows import RoadmapRow
from teleclaude.core.todos_db._upcycle import canonicalize_state_for_storage
from teleclaude.docs_reconcile import scan_remove_orphans

_SOFT_REMOVE_LOCKS: dict[str, asyncio.Lock] = {}


def _soft_remove_lock(db_path: str) -> asyncio.Lock:
    lock = _SOFT_REMOVE_LOCKS.get(db_path)
    if lock is None:
        lock = asyncio.Lock()
        _SOFT_REMOVE_LOCKS[db_path] = lock
    return lock


class ReactivateRefused(Exception):
    """Reactivation refused — typed exception with structured fields.

    Reasons:
      - ``not_removed``: the supplied id does not name a row whose status is
        ``removed`` (it may be live, delivered, or absent altogether).
      - ``live_twin_exists``: a live (``active``/``icebox``) row currently
        claims the same slug, so resurrecting the removed entry would collide.
      - ``invalid_removed_deps``: the tombstone dependency snapshot is not the
        expected JSON list of strings.

    Tests assert on ``.reason``/``.roadmap_id``/``.slug`` — never on the
    rendered message text.
    """

    def __init__(self, *, reason: str, roadmap_id: str, slug: str | None = None) -> None:
        self.reason = reason
        self.roadmap_id = roadmap_id
        self.slug = slug
        super().__init__(reason)


def _roadmap_row(model: TodoRoadmap) -> RoadmapRow:
    """Convert a roadmap ORM model to the public typed row shape."""
    children = json.loads(model.children) if model.children else None
    return RoadmapRow(
        id=model.id,
        slug=model.slug,
        position=model.position,
        group_slug=model.group_slug,
        description=model.description,
        status=model.status,
        delivered_at=model.delivered_at,
        delivered_commit=model.delivered_commit,
        children=children if isinstance(children, list) else None,
    )


class _EntryUpdates(TypedDict, total=False):
    """Subset of roadmap fields eligible for idempotent update."""

    group_slug: str
    description: str
    updated_at: str


class ExpiredRemovedRow(TypedDict):
    """Removed roadmap row eligible for purge planning."""

    id: str
    slug: str
    removed_at: str
    pending_purge_paths: list[str] | None


class PurgedRemovedRow(TypedDict):
    """Removed roadmap row that was hard-deleted."""

    id: str
    slug: str
    removed_at: str


def _collect_entry_updates(
    existing: TodoRoadmap,
    *,
    group_slug: str | None,
    description: str | None,
) -> _EntryUpdates:
    """Build a dict of fields that differ from the existing entry."""
    values = _EntryUpdates()
    if group_slug is not None and existing.group_slug != group_slug:
        values["group_slug"] = group_slug
    if description is not None and existing.description != description:
        values["description"] = description
    return values


def _decode_pending_purge_paths(value: str | None, *, roadmap_id: str) -> list[str] | None:
    """Decode the durable purge-retry path list from a roadmap row."""
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid pending_purge_paths for roadmap row {roadmap_id}") from exc
    if not isinstance(decoded, list) or not all(isinstance(path, str) for path in decoded):
        raise ValueError(f"Invalid pending_purge_paths for roadmap row {roadmap_id}")
    return decoded


class TodosDbRoadmapMixin:
    """Roadmap CRUD, ordering, deps, delivery, icebox (replaces roadmap.yaml)."""

    _on_mutation: Callable[[str, Mapping[str, object] | None], None]

    async def _next_position(self, session: SqlAsyncSession) -> int:
        """Return the next available position value."""
        result = await session.exec(select(func.coalesce(func.max(ROADMAP_TABLE.c.position), -1) + 1))
        return int(result.one())

    async def _active_entry(self, session: SqlAsyncSession, slug: str) -> TodoRoadmap | None:
        """Return the live (active or icebox) roadmap entry for a slug.

        Excludes both ``delivered`` and ``removed``: a soft-removed row is
        invisible to every default resolver, mirroring the closed-session model.
        """
        result = await session.exec(
            select(TodoRoadmap)
            .where(ROADMAP_TABLE.c.slug == slug)
            .where(ROADMAP_TABLE.c.status.in_(("active", "icebox")))
            .limit(1)
        )
        return result.first()

    async def _purge_holder_payload(self, session: SqlAsyncSession, holder_slug: str) -> None:
        """Strip a holder row to structure plus its frozen input artifact."""
        if not holder_slug:
            return
        result = await session.exec(
            select(TodoRoadmap.id).where(ROADMAP_TABLE.c.slug == holder_slug).where(ROADMAP_TABLE.c.status != "removed")
        )
        row_ids = [str(row_id) for row_id in result.all()]
        if not row_ids:
            return

        await session.exec(delete(TodoStateModel).where(TODO_STATE_TABLE.c.id.in_(row_ids)))
        await session.exec(
            delete(TodoArtifact)
            .where(TODO_ARTIFACT_TABLE.c.id.in_(row_ids))
            .where(TODO_ARTIFACT_TABLE.c.name != ARTIFACT_INPUT)
        )
        await session.exec(
            delete(TodoArtifactVersion)
            .where(TODO_ARTIFACT_VERSION_TABLE.c.id.in_(row_ids))
            .where(TODO_ARTIFACT_VERSION_TABLE.c.name != ARTIFACT_INPUT)
        )

    async def _roadmap_status_map(self, session: SqlAsyncSession) -> dict[str, str]:
        """Return a slug-status map where any non-removed row outranks removed history."""
        rows = await session.exec(select(ROADMAP_TABLE.c.slug, ROADMAP_TABLE.c.status))
        status_map: dict[str, str] = {}
        for slug, status in rows.all():
            if not isinstance(slug, str) or not isinstance(status, str):
                continue
            current = status_map.get(slug)
            if current is None or (current == "removed" and status != "removed"):
                status_map[slug] = status
        return status_map

    async def _list_roadmap_models(
        self,
        *,
        include_icebox: bool = False,
        include_delivered: bool = False,
        delivered_only: bool = False,
        session: SqlAsyncSession | None = None,
    ) -> list[TodoRoadmap]:
        """Fetch roadmap ORM rows for the requested visibility filters."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            stmt = select(TodoRoadmap)
            if delivered_only:
                stmt = stmt.where(ROADMAP_TABLE.c.status == "delivered").order_by(ROADMAP_TABLE.c.delivered_at.desc())
            else:
                allowed = ["active"]
                if include_icebox:
                    allowed.append("icebox")
                if include_delivered:
                    allowed.append("delivered")
                stmt = stmt.where(ROADMAP_TABLE.c.status.in_(allowed)).order_by(ROADMAP_TABLE.c.position)
            result = await db_session.exec(stmt)
            return list(result.all())
        finally:
            if owns_session:
                await db_session.close()

    async def list_roadmap(
        self,
        *,
        include_icebox: bool = False,
        include_delivered: bool = False,
        delivered_only: bool = False,
    ) -> list[RoadmapRow]:
        """List roadmap entries ordered by position (active) or delivery date (delivered)."""
        models = await self._list_roadmap_models(
            include_icebox=include_icebox,
            include_delivered=include_delivered,
            delivered_only=delivered_only,
        )
        return [_roadmap_row(model) for model in models]

    async def list_entries(self) -> list[TodoRoadmap]:
        """Return active roadmap entries as ORM models."""
        return await self._list_roadmap_models()

    async def add_entry(self, *, slug: str, position: int, description: str | None = None) -> bool:
        """Compatibility wrapper used by the SQLAlchemy migration spec."""
        return await self.add_to_roadmap(slug, description=description, position=position)

    async def add_to_roadmap(
        self,
        slug: str,
        *,
        group_slug: str | None = None,
        after: list[str] | None = None,
        description: str | None = None,
        before: str | None = None,
        position: int | None = None,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Add or update a slug in the roadmap. Idempotent — returns True on success."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            existing = await self._active_entry(db_session, slug)
            if existing is not None:
                values = _collect_entry_updates(existing, group_slug=group_slug, description=description)
                if values:
                    values["updated_at"] = datetime.now(UTC).isoformat()
                    await db_session.exec(
                        update(TodoRoadmap)
                        .where(ROADMAP_TABLE.c.slug == slug, ROADMAP_TABLE.c.status.in_(("active", "icebox")))
                        .values(**values)
                    )
                if group_slug and group_slug != slug:
                    await self._purge_holder_payload(db_session, group_slug)
                if owns_session:
                    await db_session.commit()
                    self._on_mutation("todo_updated", None)
                return True

            now = datetime.now(UTC).isoformat()
            new_id = _generate_id()
            resolved_position = await self._next_position(db_session)
            if before:
                target = await self._active_entry(db_session, before)
                if target is not None:
                    resolved_position = target.position
                    await db_session.exec(
                        update(TodoRoadmap)
                        .where(ROADMAP_TABLE.c.position >= resolved_position)
                        .values(position=ROADMAP_TABLE.c.position + 1)
                    )
            elif position is not None:
                requested_position = max(position - 1, 0)
                next_position = await self._next_position(db_session)
                resolved_position = min(requested_position, next_position)
                if resolved_position < next_position:
                    await db_session.exec(
                        update(TodoRoadmap)
                        .where(ROADMAP_TABLE.c.position >= resolved_position)
                        .values(position=ROADMAP_TABLE.c.position + 1)
                    )

            db_session.add(
                TodoRoadmap(
                    id=new_id,
                    slug=slug,
                    position=resolved_position,
                    group_slug=group_slug,
                    description=description,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )

            for dep in after or []:
                db_session.add(RoadmapDep(slug=slug, depends_on=dep))

            if group_slug and group_slug != slug:
                await self._purge_holder_payload(db_session, group_slug)

            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
            return True
        finally:
            if owns_session:
                await db_session.close()

    async def soft_remove_from_roadmap(
        self,
        slug: str,
        *,
        cwd: str,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Soft-remove the live (active/icebox) entry for a slug.

        The durable record survives: status flips to ``removed``, ``removed_at``
        is stamped, and the entry's outgoing dependency slugs are snapshotted into
        ``removed_deps`` keyed by the row's stable id. Live ``roadmap_deps`` rows
        are scrubbed in *both* directions so the slug is free for immediate reuse
        and so no live consumer still points at the tombstoned entry. State,
        artifacts, and artifact version history are intentionally retained.

        After the DB mutation commits, slug-keyed filesystem teardown runs
        through :func:`cleanup_delivered_slug` (worktree + local/remote branch +
        workspace dir). All slug-keyed teardown happens *here*, while the slug
        still unambiguously names this entry — the eventual retention purge is
        strictly row-id-addressed and performs no slug-keyed work. Drafts skip
        the filesystem teardown because they own no working resources.

        Returns ``False`` when no live entry exists for ``slug``; otherwise
        ``True`` after the DB mutation lands (and, for caller-owned sessions,
        before the caller's commit — the post-commit cleanup branch only fires
        on the owns-session path).
        """
        is_draft = False
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        async with _soft_remove_lock(self.db_path):  # type: ignore[attr-defined]
            try:
                if owns_session:
                    connection = await db_session.connection()
                    await connection.exec_driver_sql("BEGIN IMMEDIATE")

                entry = await self._active_entry(db_session, slug)
                if entry is None:
                    if owns_session:
                        await db_session.rollback()
                    return False

                roadmap_status_map = await self._roadmap_status_map(db_session)
                blocking_snippets = scan_remove_orphans(Path(cwd), slug, roadmap_status_map)
                if blocking_snippets:
                    raise RemoveRefused(slug=slug, blocking_snippets=blocking_snippets)

                outgoing_deps = await db_session.exec(
                    select(RoadmapDep.depends_on)
                    .where(ROADMAP_DEPS_TABLE.c.slug == slug)
                    .order_by(RoadmapDep.depends_on)
                )
                outgoing = [str(dep) for dep in outgoing_deps.all()]

                state_model = await db_session.get(TodoStateModel, entry.id)
                if state_model is not None:
                    try:
                        is_draft = json.loads(state_model.state).get("kind") == "draft"
                    except (ValueError, TypeError):
                        is_draft = False

                now = datetime.now(UTC).isoformat()
                entry.prev_status = entry.status
                entry.status = "removed"
                entry.removed_at = now
                entry.removed_deps = json.dumps(outgoing) if outgoing else None
                entry.updated_at = now
                db_session.add(entry)

                await db_session.exec(delete(RoadmapDep).where(ROADMAP_DEPS_TABLE.c.slug == slug))
                await db_session.exec(delete(RoadmapDep).where(ROADMAP_DEPS_TABLE.c.depends_on == slug))

                if owns_session:
                    await db_session.commit()
                    self._on_mutation("todo_removed", None)
            except Exception:
                if owns_session:
                    await db_session.rollback()
                raise
            finally:
                if owns_session:
                    await db_session.close()

        # Filesystem teardown runs only when this method owned the commit. A
        # caller-managed session has not yet committed at this point, so fs
        # cleanup must remain the caller's post-commit responsibility there.
        if owns_session and not is_draft:
            await asyncio.to_thread(cleanup_delivered_slug, cwd, slug)
        return True

    async def reactivate_removed(
        self,
        roadmap_id: str,
        *,
        session: SqlAsyncSession | None = None,
    ) -> str:
        """Restore a soft-removed roadmap row addressed by its durable row id.

        The input is a ``roadmap.id`` — never a bare slug — because repeated
        remove/recreate cycles can leave several removed rows per slug, and the
        slug alone cannot disambiguate them. The operation is fail-closed:

        * If the id does not name a ``removed`` row, the call raises
          :class:`ReactivateRefused` with ``reason='not_removed'`` and changes
          nothing.
        * If a live (``active``/``icebox``) row currently claims the same slug,
          the call raises :class:`ReactivateRefused` with
          ``reason='live_twin_exists'`` and changes nothing — no overwrite,
          no merge, no silent resurrection.

        On success: status flips back to ``prev_status`` (fallback ``icebox``
        for legacy rows that predate the tombstone fields), ``removed_deps`` is
        deserialized and replayed as outgoing ``roadmap_deps``, and all
        tombstone fields are cleared. Inbound third-party edges are NOT
        resurrected — only the entry's own footprint is restored. State,
        artifacts, and version history were retained at soft-remove and
        become addressable again through the default resolvers.

        Returns the restored slug.
        """
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            entry = await db_session.get(TodoRoadmap, roadmap_id)
            if entry is None or entry.status != "removed":
                raise ReactivateRefused(
                    reason="not_removed",
                    roadmap_id=roadmap_id,
                    slug=entry.slug if entry is not None else None,
                )

            live_twin = await self._active_entry(db_session, entry.slug)
            if live_twin is not None:
                raise ReactivateRefused(
                    reason="live_twin_exists",
                    roadmap_id=roadmap_id,
                    slug=entry.slug,
                )

            restored_status = entry.prev_status or "icebox"
            replay_slugs: list[str] = []
            if entry.removed_deps:
                try:
                    parsed = json.loads(entry.removed_deps)
                except (ValueError, TypeError) as exc:
                    raise ReactivateRefused(
                        reason="invalid_removed_deps",
                        roadmap_id=roadmap_id,
                        slug=entry.slug,
                    ) from exc
                if not isinstance(parsed, list) or not all(isinstance(dep, str) for dep in parsed):
                    raise ReactivateRefused(
                        reason="invalid_removed_deps",
                        roadmap_id=roadmap_id,
                        slug=entry.slug,
                    )
                replay_slugs = parsed

            entry.status = restored_status
            entry.prev_status = None
            entry.removed_at = None
            entry.removed_deps = None
            entry.updated_at = datetime.now(UTC).isoformat()
            db_session.add(entry)

            for dep in replay_slugs:
                db_session.add(RoadmapDep(slug=entry.slug, depends_on=dep))

            slug = entry.slug
            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
            return slug
        finally:
            if owns_session:
                await db_session.close()

    async def slug_in_roadmap(self, slug: str) -> bool:
        """Check if an active/icebox slug exists in the roadmap."""
        async with self._session() as session:  # type: ignore[attr-defined]
            return await self._active_entry(session, slug) is not None

    async def slug_conflicts_non_removed(self, slug: str, *, session: SqlAsyncSession | None = None) -> bool:
        """Return whether any non-removed roadmap row already holds a slug."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            result = await db_session.exec(
                select(TodoRoadmap.id)
                .where(ROADMAP_TABLE.c.slug == slug)
                .where(ROADMAP_TABLE.c.status != "removed")
                .limit(1)
            )
            return result.first() is not None
        finally:
            if owns_session:
                await db_session.close()

    async def list_expired_removed(self, cutoff_iso: str) -> list[ExpiredRemovedRow]:
        """List removed roadmap rows whose tombstone predates ``cutoff_iso``.

        Self-heals legacy/partial rows first: any row with ``status='removed'`` and
        a NULL ``removed_at`` gets stamped with the current timestamp so it joins
        the retention window from that point forward instead of being mis-purged.
        """
        expired_rows: list[ExpiredRemovedRow] = []
        async with self._session() as session:  # type: ignore[attr-defined]
            now_iso = datetime.now(UTC).isoformat()
            await session.exec(
                update(TodoRoadmap)
                .where(ROADMAP_TABLE.c.status == "removed")
                .where(ROADMAP_TABLE.c.removed_at.is_(None))
                .values(removed_at=now_iso, updated_at=now_iso)
            )

            expired = await session.exec(
                select(TodoRoadmap)
                .where(ROADMAP_TABLE.c.status == "removed")
                .where(ROADMAP_TABLE.c.removed_at.is_not(None))
                .where(ROADMAP_TABLE.c.removed_at < cutoff_iso)
            )
            for entry in expired.all():
                expired_rows.append(
                    {
                        "id": str(entry.id),
                        "slug": str(entry.slug),
                        "removed_at": str(entry.removed_at),
                        "pending_purge_paths": _decode_pending_purge_paths(
                            entry.pending_purge_paths,
                            roadmap_id=str(entry.id),
                        ),
                    }
                )

            await session.commit()
        return expired_rows

    async def set_pending_purge_paths(self, row_id: str, paths: list[str]) -> None:
        """Persist the sweep-owned snippet paths for a removed roadmap row."""
        encoded_paths = json.dumps(paths)
        async with self._session() as session:  # type: ignore[attr-defined]
            await session.exec(
                update(TodoRoadmap)
                .where(ROADMAP_TABLE.c.id == row_id)
                .values(pending_purge_paths=encoded_paths, updated_at=datetime.now(UTC).isoformat())
            )
            await session.commit()
        self._on_mutation("todo_updated", None)

    async def clear_pending_purge_paths(self, row_id: str) -> None:
        """Clear the sweep-owned snippet paths for a removed roadmap row."""
        async with self._session() as session:  # type: ignore[attr-defined]
            await session.exec(
                update(TodoRoadmap)
                .where(ROADMAP_TABLE.c.id == row_id)
                .values(pending_purge_paths=None, updated_at=datetime.now(UTC).isoformat())
            )
            await session.commit()
        self._on_mutation("todo_updated", None)

    async def purge_one_removed(self, row_id: str) -> PurgedRemovedRow | None:
        """Hard-delete one removed roadmap row by durable row id.

        The ``ON DELETE CASCADE`` foreign keys clear matching state and artifact
        rows. No slug-keyed cleanup runs here because a same-slug live todo may
        legitimately exist by the time purge runs.
        """
        purged: PurgedRemovedRow | None = None
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await session.get(TodoRoadmap, row_id)
            if entry is None or entry.status != "removed":
                return None
            purged = {
                "id": str(entry.id),
                "slug": str(entry.slug),
                "removed_at": str(entry.removed_at),
            }
            await session.delete(entry)
            await session.commit()
        self._on_mutation("todo_removed", None)
        return purged

    async def purge_expired_removed(self, cutoff_iso: str) -> list[PurgedRemovedRow]:
        """Compatibility wrapper that hard-deletes every expired removed row."""
        purged: list[PurgedRemovedRow] = []
        for row in await self.list_expired_removed(cutoff_iso):
            deleted = await self.purge_one_removed(row["id"])
            if deleted is not None:
                purged.append(deleted)
        return purged

    async def resolve_id(self, slug: str) -> str | None:
        """Resolve an active/icebox slug to its roadmap id. Returns None if not found."""
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await self._active_entry(session, slug)
            return entry.id if entry is not None else None

    def resolve_id_sync(self, slug: str) -> str | None:
        """Sync version of resolve_id. Excludes delivered and removed rows."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            entry_id = session.exec(
                select(TodoRoadmap.id)
                .where(ROADMAP_TABLE.c.slug == slug)
                .where(ROADMAP_TABLE.c.status.in_(("active", "icebox")))
                .limit(1)
            ).first()
            return str(entry_id) if entry_id is not None else None

    async def deliver(
        self,
        slug: str,
        *,
        commit: str | None = None,
        children: list[str] | None = None,
        delivered_at: str | None = None,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Mark a slug as delivered and persist delivered coarse item state."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            entry = await self._active_entry(db_session, slug)
            if entry is None:
                return False

            now = delivered_at or datetime.now(UTC).isoformat()
            entry.status = "delivered"
            entry.delivered_at = now
            entry.delivered_commit = commit
            entry.children = json.dumps(children) if children else None
            entry.updated_at = now
            db_session.add(entry)

            state_model = await db_session.get(TodoStateModel, entry.id)
            if state_model is not None:
                state = json.loads(state_model.state)
                state["phase"] = "delivered"
                state["integration_phase"] = "delivered"
                state_model.state = json.dumps(canonicalize_state_for_storage(state))
                state_model.updated_at = now
                db_session.add(state_model)

            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
            return True
        finally:
            if owns_session:
                await db_session.close()

    async def delivered_slugs(self) -> set[str]:
        """Return set of delivered slugs."""
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(select(TodoRoadmap.slug).where(ROADMAP_TABLE.c.status == "delivered"))
            return {str(slug) for slug in result.all()}

    async def freeze(self, slug: str) -> bool:
        """Move a slug to icebox. Returns False if not found."""
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await self._active_entry(session, slug)
            if entry is None:
                return False
            entry.status = "icebox"
            entry.updated_at = datetime.now(UTC).isoformat()
            session.add(entry)
            await session.commit()
        self._on_mutation("todo_updated", None)
        return True

    async def unfreeze(self, slug: str) -> bool:
        """Restore a slug from icebox to active. Returns False if not found."""
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(TodoRoadmap)
                .where(ROADMAP_TABLE.c.slug == slug)
                .where(ROADMAP_TABLE.c.status == "icebox")
                .limit(1)
            )
            entry = result.first()
            if entry is None:
                return False
            entry.status = "active"
            entry.updated_at = datetime.now(UTC).isoformat()
            session.add(entry)
            await session.commit()
        self._on_mutation("todo_updated", None)
        return True

    async def set_deps(
        self,
        slug: str,
        *,
        after: list[str],
        session: SqlAsyncSession | None = None,
    ) -> None:
        """Replace dependencies for a slug."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            entry = await self._active_entry(db_session, slug)
            if entry is None:
                raise ValueError(f"no active/icebox roadmap entry for slug: {slug}")
            await db_session.exec(delete(RoadmapDep).where(ROADMAP_DEPS_TABLE.c.slug == slug))
            for dep in after:
                db_session.add(RoadmapDep(slug=slug, depends_on=dep))
            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
        finally:
            if owns_session:
                await db_session.close()

    async def get_deps(self, slug: str) -> list[str]:
        """Return dependency slugs for one roadmap entry."""
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await self._active_entry(session, slug)
            if entry is None:
                return []
            result = await session.exec(
                select(RoadmapDep.depends_on)
                .join(TodoRoadmap, ROADMAP_TABLE.c.slug == ROADMAP_DEPS_TABLE.c.depends_on)
                .where(RoadmapDep.slug == slug)
                .where(ROADMAP_TABLE.c.status.in_(("active", "icebox")))
                .order_by(RoadmapDep.depends_on)
            )
            return [str(dep) for dep in result.all()]

    async def load_deps(self) -> dict[str, list[str]]:
        """Return dependency graph: {slug: [depends_on, ...]}."""
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(RoadmapDep)
                .join(TodoRoadmap, ROADMAP_TABLE.c.slug == ROADMAP_DEPS_TABLE.c.slug)
                .where(ROADMAP_TABLE.c.status.in_(("active", "icebox")))
                .order_by(RoadmapDep.slug, RoadmapDep.depends_on)
            )
            deps: dict[str, list[str]] = {}
            for dep in result.all():
                deps.setdefault(dep.slug, []).append(dep.depends_on)
            if not deps:
                return deps

            live_dependency_rows = await session.exec(
                select(TodoRoadmap.slug)
                .where(ROADMAP_TABLE.c.status.in_(("active", "icebox")))
                .where(ROADMAP_TABLE.c.slug.in_({dep for deps_for_slug in deps.values() for dep in deps_for_slug}))
            )
            live_dependency_slugs = {str(slug) for slug in live_dependency_rows.all()}
            for slug in list(deps):
                filtered = [dep for dep in deps[slug] if dep in live_dependency_slugs]
                if filtered:
                    deps[slug] = filtered
                else:
                    deps.pop(slug)
            return deps

    async def clean_dep_references(self, slug: str, *, session: SqlAsyncSession | None = None) -> None:
        """Remove a slug from all dependency lists."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            await db_session.exec(delete(RoadmapDep).where(ROADMAP_DEPS_TABLE.c.depends_on == slug))
            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
        finally:
            if owns_session:
                await db_session.close()

    async def rename_roadmap_slug(
        self,
        old_slug: str,
        new_slug: str,
        *,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Re-key the live roadmap row and structured roadmap slug references."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            entry = await self._active_entry(db_session, old_slug)
            if entry is None:
                return False

            now = datetime.now(UTC).isoformat()
            entry.slug = new_slug
            entry.updated_at = now
            db_session.add(entry)

            await db_session.exec(
                update(TodoRoadmap)
                .where(ROADMAP_TABLE.c.group_slug == old_slug)
                .where(ROADMAP_TABLE.c.status.notin_(("delivered", "removed")))
                .values(group_slug=new_slug, updated_at=now)
            )

            child_rows = await db_session.exec(
                select(TodoRoadmap)
                .where(ROADMAP_TABLE.c.children.is_not(None))
                .where(ROADMAP_TABLE.c.status.notin_(("delivered", "removed")))
            )
            for row in child_rows.all():
                children = json.loads(row.children) if row.children else None
                if not isinstance(children, list) or old_slug not in children:
                    continue
                row.children = json.dumps([new_slug if child == old_slug else child for child in children])
                row.updated_at = now
                db_session.add(row)

            await db_session.exec(update(RoadmapDep).where(ROADMAP_DEPS_TABLE.c.slug == old_slug).values(slug=new_slug))
            await db_session.exec(
                update(RoadmapDep).where(ROADMAP_DEPS_TABLE.c.depends_on == old_slug).values(depends_on=new_slug)
            )

            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
            return True
        finally:
            if owns_session:
                await db_session.close()

    async def move_in_roadmap(
        self,
        slug: str,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> bool:
        """Reorder a slug in the roadmap. Returns False if slug or target not found."""
        target_slug = before or after
        if target_slug is None:
            return False

        async with self._session() as session:  # type: ignore[attr-defined]
            source = await self._active_entry(session, slug)
            target = await self._active_entry(session, target_slug)
            if source is None or target is None:
                return False

            old_position = source.position
            await session.exec(
                update(TodoRoadmap)
                .where(ROADMAP_TABLE.c.position > old_position)
                .values(position=ROADMAP_TABLE.c.position - 1)
            )

            refreshed_target = await self._active_entry(session, target_slug)
            if refreshed_target is None:
                return False
            new_position = refreshed_target.position if before else refreshed_target.position + 1

            await session.exec(
                update(TodoRoadmap)
                .where(ROADMAP_TABLE.c.position >= new_position)
                .where(ROADMAP_TABLE.c.slug != slug)
                .values(position=ROADMAP_TABLE.c.position + 1)
            )

            source.position = new_position
            source.updated_at = datetime.now(UTC).isoformat()
            session.add(source)
            await session.commit()

        self._on_mutation("todo_updated", None)
        return True

    async def move_entry(self, slug: str, *, before: str | None = None, after: str | None = None) -> bool:
        """Compatibility wrapper used by the SQLAlchemy migration spec."""
        return await self.move_in_roadmap(slug, before=before, after=after)

    def delivered_slugs_sync(self) -> set[str]:
        """Sync version of delivered_slugs for use from worker threads."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            result = session.exec(select(TodoRoadmap.slug).where(ROADMAP_TABLE.c.status == "delivered"))
            return {str(slug) for slug in result.all()}

    def deliver_sync(
        self,
        slug: str,
        *,
        commit: str | None = None,
        children: list[str] | None = None,
    ) -> bool:
        """Sync version of deliver for use from worker threads."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            entry = session.exec(
                select(TodoRoadmap)
                .where(ROADMAP_TABLE.c.slug == slug)
                .where(ROADMAP_TABLE.c.status.in_(("active", "icebox")))
                .limit(1)
            ).first()
            if entry is None:
                return False

            now = datetime.now(UTC).isoformat()
            entry.status = "delivered"
            entry.delivered_at = now
            entry.delivered_commit = commit
            entry.children = json.dumps(children) if children else None
            entry.updated_at = now
            session.add(entry)

            state_model = session.get(TodoStateModel, entry.id)
            if state_model is not None:
                state = json.loads(state_model.state)
                state["phase"] = "delivered"
                state["integration_phase"] = "delivered"
                state_model.state = json.dumps(canonicalize_state_for_storage(state))
                state_model.updated_at = now
                session.add(state_model)

            session.commit()

        self._on_mutation("todo_updated", None)
        return True
