"""Todo soft-delete and purge persistence mixin."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from sqlalchemy import delete, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.todos_db._exceptions import RemoveRefused
from teleclaude.core.todos_db._models import (
    TODO_DEPS_TABLE,
    TODO_TABLE,
    Todo,
    TodoDep,
    TodoStateModel,
)
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

    Tests assert on ``.reason``/``.todo_id``/``.slug`` — never on the
    rendered message text.
    """

    def __init__(
        self,
        reason: str,
        todo_id: str,
        slug: str | None = None,
    ) -> None:
        self.reason = reason
        self.todo_id = todo_id
        self.slug = slug
        super().__init__(f"reactivate refused for {todo_id} ({slug}): {reason}")


class ExpiredRemovedRow(TypedDict):
    """Removed todo row eligible for purge planning."""

    id: str
    slug: str
    removed_at: str
    pending_purge_paths: list[str] | None


class PurgedRemovedRow(TypedDict):
    """Removed todo row that was hard-deleted."""

    id: str
    slug: str
    removed_at: str


class TodosDbTodoSoftDeleteMixin:
    """Persistence logic for soft-removed todo entries and their retention lifecycle."""

    async def soft_remove_from_todo(
        self,
        slug: str,
        *,
        cwd: str,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Soft-remove the live (active/icebox) entry for a slug.

        The durable record survives: status flips to ``removed``, ``removed_at``
        is stamped, and the entry's outgoing dependency slugs are snapshotted into
        ``removed_deps`` keyed by the row's stable id. Live ``todo_deps`` rows
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
        async with _soft_remove_lock(cast(Any, self).db_path):
            try:
                if owns_session:
                    connection = await db_session.connection()
                    await connection.exec_driver_sql("BEGIN IMMEDIATE")

                entry = await cast(Any, self)._active_entry(db_session, slug)
                if entry is None:
                    if owns_session:
                        await db_session.rollback()
                    return False

                todo_status_map = await cast(Any, self)._todo_status_map(db_session)
                blocking_snippets = scan_remove_orphans(Path(cwd), slug, todo_status_map)
                if blocking_snippets:
                    raise RemoveRefused(slug=slug, blocking_snippets=blocking_snippets)

                outgoing_deps = await db_session.exec(
                    select(TodoDep.depends_on).where(TODO_DEPS_TABLE.c.slug == slug).order_by(TodoDep.depends_on)
                )
                outgoing = [str(dep) for dep in outgoing_deps.all()]

                state_model = await db_session.get(TodoStateModel, entry.id)
                if state_model is not None:
                    try:
                        state = json.loads(state_model.state)
                        if not isinstance(state, dict):
                            raise TypeError
                        is_draft = state.get("kind") == "draft"
                    except (ValueError, TypeError):
                        is_draft = False
                    else:
                        state.pop("active_runner", None)
                        state["manually_started"] = False
                        state_model.state = json.dumps(canonicalize_state_for_storage(state))
                        state_model.updated_at = datetime.now(UTC).isoformat()
                        db_session.add(state_model)

                now = datetime.now(UTC).isoformat()
                entry.prev_status = entry.status
                entry.status = "removed"
                entry.removed_at = now
                entry.removed_deps = json.dumps(outgoing) if outgoing else None
                entry.updated_at = now
                db_session.add(entry)

                await db_session.exec(delete(TodoDep).where(TODO_DEPS_TABLE.c.slug == slug))
                await db_session.exec(delete(TodoDep).where(TODO_DEPS_TABLE.c.depends_on == slug))

                if owns_session:
                    await db_session.commit()
                    cast(Any, self)._on_mutation("todo_removed", None)
            except Exception:
                if owns_session:
                    await db_session.rollback()
                raise
            finally:
                if owns_session:
                    await db_session.close()

        if owns_session and not is_draft:
            await asyncio.to_thread(cleanup_delivered_slug, cwd, slug)
        return True

    async def reactivate_removed(
        self,
        todo_id: str,
        *,
        session: SqlAsyncSession | None = None,
    ) -> str:
        """Restore a soft-removed todo row addressed by its durable row id.

        The input is a ``todo.id`` — never a bare slug — because repeated
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
        deserialized and replayed as outgoing ``todo_deps``, and all
        tombstone fields are cleared. Inbound third-party edges are NOT
        resurrected — only the entry's own footprint is restored. State,
        artifacts, and version history were retained at soft-remove and
        become addressable again through the default resolvers.

        Returns the restored slug.
        """
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            entry = await db_session.get(Todo, todo_id)
            if entry is None or entry.status != "removed":
                raise ReactivateRefused(
                    reason="not_removed",
                    todo_id=todo_id,
                    slug=entry.slug if entry is not None else None,
                )

            live_twin = await cast(Any, self)._active_entry(db_session, entry.slug)
            if live_twin is not None:
                raise ReactivateRefused(
                    reason="live_twin_exists",
                    todo_id=todo_id,
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
                        todo_id=todo_id,
                        slug=entry.slug,
                    ) from exc
                if not isinstance(parsed, list) or not all(isinstance(dep, str) for dep in parsed):
                    raise ReactivateRefused(
                        reason="invalid_removed_deps",
                        todo_id=todo_id,
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
                db_session.add(TodoDep(slug=entry.slug, depends_on=dep))

            slug = entry.slug
            if owns_session:
                await db_session.commit()
                cast(Any, self)._on_mutation("todo_updated", None)
            return slug
        finally:
            if owns_session:
                await db_session.close()

    async def slug_in_todo(self, slug: str) -> bool:
        """Check if an active/icebox slug exists in the todo."""
        async with cast(Any, self)._session() as session:
            return await cast(Any, self)._active_entry(session=session, slug=slug) is not None

    async def slug_conflicts_non_removed(self, slug: str, *, session: SqlAsyncSession | None = None) -> bool:
        """Return whether any non-removed todo row already holds a slug."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            result = await db_session.exec(
                select(Todo.id).where(TODO_TABLE.c.slug == slug).where(TODO_TABLE.c.status != "removed").limit(1)
            )
            return result.first() is not None
        finally:
            if owns_session:
                await db_session.close()

    async def list_expired_removed(self, cutoff_iso: str) -> list[ExpiredRemovedRow]:
        """List removed todo rows whose tombstone predates ``cutoff_iso``.

        Self-heals legacy/partial rows first: any row with ``status='removed'`` and
        a NULL ``removed_at`` gets stamped with the current timestamp so it joins
        the retention window from that point forward instead of being mis-purged.
        """
        expired_rows: list[ExpiredRemovedRow] = []
        async with cast(Any, self)._session() as session:
            now_iso = datetime.now(UTC).isoformat()
            await session.exec(
                update(Todo)
                .where(TODO_TABLE.c.status == "removed")
                .where(TODO_TABLE.c.removed_at.is_(None))
                .values(removed_at=now_iso, updated_at=now_iso)
            )

            expired = await session.exec(
                select(Todo)
                .where(TODO_TABLE.c.status == "removed")
                .where(TODO_TABLE.c.removed_at.is_not(None))
                .where(TODO_TABLE.c.removed_at < cutoff_iso)
            )
            for entry in expired.all():
                expired_rows.append(
                    {
                        "id": str(entry.id),
                        "slug": str(entry.slug),
                        "removed_at": str(entry.removed_at),
                        "pending_purge_paths": _decode_pending_purge_paths(
                            entry.pending_purge_paths,
                            todo_id=str(entry.id),
                        ),
                    }
                )

            await session.commit()
        return expired_rows

    async def set_pending_purge_paths(self, row_id: str, paths: list[str]) -> None:
        """Persist the sweep-owned snippet paths for a removed todo row."""
        encoded_paths = json.dumps(paths)
        async with cast(Any, self)._session() as session:
            await session.exec(
                update(Todo)
                .where(TODO_TABLE.c.id == row_id)
                .values(pending_purge_paths=encoded_paths, updated_at=datetime.now(UTC).isoformat())
            )
            await session.commit()
        cast(Any, self)._on_mutation("todo_updated", None)

    async def clear_pending_purge_paths(self, row_id: str) -> None:
        """Clear the sweep-owned snippet paths for a removed todo row."""
        async with cast(Any, self)._session() as session:
            await session.exec(
                update(Todo)
                .where(TODO_TABLE.c.id == row_id)
                .values(pending_purge_paths=None, updated_at=datetime.now(UTC).isoformat())
            )
            await session.commit()
        cast(Any, self)._on_mutation("todo_updated", None)

    async def purge_one_removed(self, row_id: str) -> PurgedRemovedRow | None:
        """Hard-delete one removed todo row by durable row id.

        The ``ON DELETE CASCADE`` foreign keys clear matching state and artifact
        rows. No slug-keyed cleanup runs here because a same-slug live todo may
        legitimately exist by the time purge runs.
        """
        purged: PurgedRemovedRow | None = None
        async with cast(Any, self)._session() as session:
            entry = await session.get(Todo, row_id)
            if entry is None or entry.status != "removed":
                return None
            purged = {
                "id": str(entry.id),
                "slug": str(entry.slug),
                "removed_at": str(entry.removed_at),
            }
            await session.delete(entry)
            await session.commit()
        cast(Any, self)._on_mutation("todo_removed", None)
        return purged

    async def purge_expired_removed(self, cutoff_iso: str) -> list[PurgedRemovedRow]:
        """Compatibility wrapper that hard-deletes every expired removed row."""
        purged: list[PurgedRemovedRow] = []
        for row in await self.list_expired_removed(cutoff_iso):
            deleted = await self.purge_one_removed(row["id"])
            if deleted is not None:
                purged.append(deleted)
        return purged


def _decode_pending_purge_paths(encoded: str | None, *, todo_id: str) -> list[str] | None:
    if encoded is None:
        return None
    try:
        decoded = json.loads(encoded)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid pending_purge_paths for todo row {todo_id}") from exc
    if not isinstance(decoded, list) or not all(isinstance(p, str) for p in decoded):
        raise ValueError(f"Invalid pending_purge_paths for todo row {todo_id}")
    return decoded
