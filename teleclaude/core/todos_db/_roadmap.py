"""Roadmap persistence mixin."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TypedDict, cast

from sqlalchemy import delete, update
from sqlmodel import Session as SqlSession
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import ARTIFACT_INPUT
from teleclaude.core.next_machine.lifecycle import is_ready_band_eligible
from teleclaude.core.todos_db._base import _generate_id
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
from teleclaude.types.todos import DependencyEntry, RoadmapStatusLiteral


def _roadmap_row(model: TodoRoadmap) -> RoadmapRow:
    """Convert a roadmap ORM model to the public typed row shape."""
    children = json.loads(model.children) if model.children else None
    return RoadmapRow(
        id=model.id,
        slug=model.slug,
        ready_since=model.ready_since,
        group_slug=model.group_slug,
        description=model.description,
        status=model.status,
        delivered_at=model.delivered_at,
        delivered_commit=model.delivered_commit,
        removed_at=model.removed_at,
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


def _readiness_state_fields(state_model: TodoStateModel | None) -> tuple[str | None, str | None]:
    if state_model is None:
        return None, None
    try:
        state = json.loads(state_model.state)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(state, dict):
        return None, None
    kind = state.get("kind")
    lifecycle_phase = state.get("lifecycle_phase")
    return (
        kind if isinstance(kind, str) else None,
        lifecycle_phase if isinstance(lifecycle_phase, str) else None,
    )


class TodosDbRoadmapMixin:
    """Roadmap CRUD, ordering, deps, delivery, icebox (replaces roadmap.yaml)."""

    _on_mutation: Callable[[str, Mapping[str, object] | None], None]

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
        include_removed: bool = False,
        removed_only: bool = False,
        session: SqlAsyncSession | None = None,
    ) -> list[TodoRoadmap]:
        """Fetch roadmap ORM rows for the requested visibility filters."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            stmt = select(TodoRoadmap)
            if delivered_only:
                stmt = stmt.where(ROADMAP_TABLE.c.status == "delivered").order_by(ROADMAP_TABLE.c.delivered_at.desc())
            elif removed_only:
                stmt = stmt.where(ROADMAP_TABLE.c.status == "removed").order_by(ROADMAP_TABLE.c.removed_at.desc())
            else:
                allowed = ["active"]
                if include_icebox:
                    allowed.append("icebox")
                if include_delivered:
                    allowed.append("delivered")
                if include_removed:
                    allowed.append("removed")
                stmt = stmt.where(ROADMAP_TABLE.c.status.in_(allowed)).order_by(ROADMAP_TABLE.c.id)
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
        include_removed: bool = False,
        removed_only: bool = False,
    ) -> list[RoadmapRow]:
        """List roadmap entries ordered by stable row id or delivery date."""
        models = await self._list_roadmap_models(
            include_icebox=include_icebox,
            include_delivered=include_delivered,
            delivered_only=delivered_only,
            include_removed=include_removed,
            removed_only=removed_only,
        )
        return [_roadmap_row(model) for model in models]

    async def list_entries(self) -> list[TodoRoadmap]:
        """Return active roadmap entries as ORM models."""
        return await self._list_roadmap_models()

    async def add_entry(self, *, slug: str, description: str | None = None) -> bool:
        """Compatibility wrapper used by the SQLAlchemy migration spec."""
        return await self.add_to_roadmap(slug, description=description)

    async def add_to_roadmap(
        self,
        slug: str,
        *,
        group_slug: str | None = None,
        after: list[str] | None = None,
        description: str | None = None,
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
            db_session.add(
                TodoRoadmap(
                    id=new_id,
                    slug=slug,
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
            entry.ready_since = None
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

            delivered_result = await db_session.exec(
                select(TodoRoadmap.slug).where(ROADMAP_TABLE.c.status == "delivered")
            )
            delivered_slugs = {str(delivered_slug) for delivered_slug in delivered_result.all()}
            delivered_slugs.add(slug)
            dependent_result = await db_session.exec(
                select(RoadmapDep.slug).where(ROADMAP_DEPS_TABLE.c.depends_on == slug).order_by(RoadmapDep.slug)
            )
            for dependent_slug in [str(dependent) for dependent in dependent_result.all()]:
                await self._stamp_ready_since_for_slug_if_eligible(
                    db_session,
                    dependent_slug,
                    delivered_slugs=delivered_slugs,
                )

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

    async def _stamp_ready_since_for_slug_if_eligible(
        self,
        session: SqlAsyncSession,
        slug: str,
        *,
        delivered_slugs: set[str],
    ) -> None:
        entry = await self._active_entry(session, slug)
        if entry is None:
            return
        state_model = await session.get(TodoStateModel, entry.id)
        kind, lifecycle_phase = _readiness_state_fields(state_model)
        deps_result = await session.exec(select(RoadmapDep.depends_on).where(ROADMAP_DEPS_TABLE.c.slug == slug))
        after_deps = [str(dep) for dep in deps_result.all()]
        if is_ready_band_eligible(
            kind=kind,
            lifecycle_phase=lifecycle_phase,
            after_deps=after_deps,
            delivered_slugs=delivered_slugs,
        ):
            await self.stamp_ready_since_if_null(slug, session=session)

    def _stamp_ready_since_for_slug_if_eligible_sync(
        self,
        session: SqlSession,
        slug: str,
        *,
        delivered_slugs: set[str],
    ) -> None:
        entry = session.exec(
            select(TodoRoadmap)
            .where(ROADMAP_TABLE.c.slug == slug)
            .where(ROADMAP_TABLE.c.status.in_(("active", "icebox")))
            .limit(1)
        ).first()
        if entry is None:
            return
        state_model = session.get(TodoStateModel, entry.id)
        kind, lifecycle_phase = _readiness_state_fields(state_model)
        deps_result = session.exec(select(RoadmapDep.depends_on).where(ROADMAP_DEPS_TABLE.c.slug == slug))
        after_deps = [str(dep) for dep in deps_result.all()]
        if is_ready_band_eligible(
            kind=kind,
            lifecycle_phase=lifecycle_phase,
            after_deps=after_deps,
            delivered_slugs=delivered_slugs,
        ):
            self.stamp_ready_since_if_null_sync(slug, session=session)

    async def stamp_ready_since_if_null(
        self,
        slug: str,
        when: str | None = None,
        *,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Stamp the ready-band entry timestamp once."""
        timestamp = when or datetime.now(UTC).isoformat()
        if session is None:
            async with self._session() as owned_session:  # type: ignore[attr-defined]
                changed = await self.stamp_ready_since_if_null(slug, timestamp, session=owned_session)
                await owned_session.commit()
            if changed:
                self._on_mutation("todo_updated", None)
            return changed

        result = await session.exec(
            select(TodoRoadmap)
            .where(ROADMAP_TABLE.c.slug == slug)
            .where(ROADMAP_TABLE.c.status.in_(("active", "icebox")))
            .limit(1)
        )
        entry = result.first()
        if entry is None or entry.ready_since is not None:
            return False
        entry.ready_since = timestamp
        session.add(entry)
        return True

    def stamp_ready_since_if_null_sync(
        self,
        slug: str,
        when: str | None = None,
        *,
        session: SqlSession | None = None,
    ) -> bool:
        """Sync sibling for stamping the ready-band entry timestamp once."""
        timestamp = when or datetime.now(UTC).isoformat()
        if session is None:
            with self._sync_session() as owned_session:  # type: ignore[attr-defined]
                changed = self.stamp_ready_since_if_null_sync(slug, timestamp, session=owned_session)
                owned_session.commit()
            if changed:
                self._on_mutation("todo_updated", None)
            return changed

        result = session.exec(
            select(TodoRoadmap)
            .where(ROADMAP_TABLE.c.slug == slug)
            .where(ROADMAP_TABLE.c.status.in_(("active", "icebox")))
            .limit(1)
        )
        entry = result.first()
        if entry is None or entry.ready_since is not None:
            return False
        entry.ready_since = timestamp
        session.add(entry)
        return True

    async def clear_ready_since(
        self,
        slug: str,
        *,
        session: SqlAsyncSession | None = None,
    ) -> None:
        """Clear the ready-band entry timestamp."""
        if session is None:
            async with self._session() as owned_session:  # type: ignore[attr-defined]
                await self.clear_ready_since(slug, session=owned_session)
                await owned_session.commit()
            self._on_mutation("todo_updated", None)
            return

        result = await session.exec(
            select(TodoRoadmap)
            .where(ROADMAP_TABLE.c.slug == slug)
            .where(ROADMAP_TABLE.c.status.in_(("active", "icebox")))
            .limit(1)
        )
        entry = result.first()
        if entry is None:
            return
        entry.ready_since = None
        session.add(entry)

    def clear_ready_since_sync(
        self,
        slug: str,
        *,
        session: SqlSession | None = None,
    ) -> None:
        """Sync sibling for clearing the ready-band entry timestamp."""
        if session is None:
            with self._sync_session() as owned_session:  # type: ignore[attr-defined]
                self.clear_ready_since_sync(slug, session=owned_session)
                owned_session.commit()
            self._on_mutation("todo_updated", None)
            return

        entry = session.exec(
            select(TodoRoadmap)
            .where(ROADMAP_TABLE.c.slug == slug)
            .where(ROADMAP_TABLE.c.status.in_(("active", "icebox")))
            .limit(1)
        ).first()
        if entry is None:
            return
        entry.ready_since = None
        session.add(entry)

    async def freeze(self, slug: str) -> bool:
        """Move a slug to icebox. Returns False if not found."""
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await self._active_entry(session, slug)
            if entry is None:
                return False
            entry.status = "icebox"
            entry.ready_since = None
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
            delivered_result = await session.exec(select(TodoRoadmap.slug).where(ROADMAP_TABLE.c.status == "delivered"))
            delivered_slugs = {str(delivered_slug) for delivered_slug in delivered_result.all()}
            await self._stamp_ready_since_for_slug_if_eligible(session, slug, delivered_slugs=delivered_slugs)
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
                raise ValueError(f"no active/icebox todo for slug: {slug}")
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

    async def get_deps_with_status(self, slug: str) -> list[DependencyEntry]:
        """Return immediate dependency slugs with each direct dep's current roadmap status."""
        child_roadmap = ROADMAP_TABLE.alias("child_roadmap")
        dep_roadmap = ROADMAP_TABLE.alias("dep_roadmap")
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(ROADMAP_DEPS_TABLE.c.depends_on, dep_roadmap.c.status)
                .join(child_roadmap, child_roadmap.c.slug == ROADMAP_DEPS_TABLE.c.slug)
                .join(dep_roadmap, dep_roadmap.c.slug == ROADMAP_DEPS_TABLE.c.depends_on)
                .where(ROADMAP_DEPS_TABLE.c.slug == slug)
                .where(child_roadmap.c.status.in_(("active", "icebox")))
                .where(dep_roadmap.c.status.in_(("active", "icebox", "delivered")))
                .order_by(ROADMAP_DEPS_TABLE.c.depends_on, dep_roadmap.c.status)
            )
            status_by_slug: dict[str, str] = {}
            for dep_slug, roadmap_status in result.all():
                if not isinstance(dep_slug, str) or not isinstance(roadmap_status, str):
                    continue
                current = status_by_slug.get(dep_slug)
                if current is None or (current == "delivered" and roadmap_status != "delivered"):
                    status_by_slug[dep_slug] = roadmap_status
            return [
                DependencyEntry(dep_slug=dep_slug, roadmap_status=cast(RoadmapStatusLiteral, roadmap_status))
                for dep_slug, roadmap_status in sorted(status_by_slug.items())
            ]

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
            entry.ready_since = None
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

            delivered_result = session.exec(select(TodoRoadmap.slug).where(ROADMAP_TABLE.c.status == "delivered"))
            delivered_slugs = {str(delivered_slug) for delivered_slug in delivered_result.all()}
            delivered_slugs.add(slug)
            dependent_result = session.exec(
                select(RoadmapDep.slug).where(ROADMAP_DEPS_TABLE.c.depends_on == slug).order_by(RoadmapDep.slug)
            )
            for dependent_slug in [str(dependent) for dependent in dependent_result.all()]:
                self._stamp_ready_since_for_slug_if_eligible_sync(
                    session,
                    dependent_slug,
                    delivered_slugs=delivered_slugs,
                )

            session.commit()

        self._on_mutation("todo_updated", None)
        return True
