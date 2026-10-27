"""Todo soft-delete and purge persistence mixin."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import delete, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.config.project_models import TodoStoreBackend
from teleclaude.constants import TodoStatus
from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.next_machine.marker_reconciliation import (
    MarkerMoment,
    reconcile_lifecycle_markers,
    restore_lifecycle_markers,
)
from teleclaude.core.todos_db._errors import HolderWriteRefused
from teleclaude.core.todos_db._identity_pin import apply_todo_identity_pin
from teleclaude.core.todos_db._models import (
    TODO_DEPS_TABLE,
    TODO_TABLE,
    Todo,
    TodoDep,
    TodoStateModel,
)
from teleclaude.core.todos_db._upcycle import canonicalize_state_for_storage
from teleclaude.core.workflow_store.selection import selected_workflow_store_backend
from teleclaude.core.workflow_store.types import (
    ExpiredRemovedItem as ExpiredRemovedRow,
)
from teleclaude.core.workflow_store.types import (
    IdentityResolution as TodoIdentityResolution,
)
from teleclaude.core.workflow_store.types import (
    PurgedItem as PurgedRemovedRow,
)
from teleclaude.core.workflow_store.types import (
    RemovalRequest as RemovalContext,
)
from teleclaude.core.workflow_store.types import WorkItemId
from teleclaude.docs_reconcile import (
    ReconciliationCarrier,
    ReconciliationMode,
    ReconciliationPlan,
    ReconciliationWrite,
)

_ACTIVE_RUNNER_FIELD = "active_runner"
_SOFT_REMOVE_LOCKS: dict[str, asyncio.Lock] = {}
_LIVE_SLUG_STATUSES: frozenset[TodoStatus] = frozenset({TodoStatus.ACTIVE, TodoStatus.ICEBOX, TodoStatus.HOLDER})
_REMOVED_IDENTITY_ACTION_REFUSAL = (
    "Todo {todo_id} ({slug}) is removed; reactivate it by identity first with "
    "`telec todo reactivate --id {todo_id}` or press U in Trashed."
)
_DELIVERED_IDENTITY_ACTION_REFUSAL = "Todo {todo_id} ({slug}) is delivered and read-only."
_IDENTITY_ACTION_REFUSAL = "Todo {todo_id} ({slug}) with status {status} does not allow changes."
_IDENTITY_NOT_FOUND = "Todo identity {todo_id} was not found."
_REACTIVATE_NOT_REMOVED_FEEDBACK = "This todo is not removed, so it cannot be reactivated."
_REACTIVATE_LIVE_TWIN_FEEDBACK = "Another live todo already uses this slug; resolve that entry before reactivating."


def _encode_removed_doc_reconciliation(plan: ReconciliationPlan) -> str:
    """Persist the exact pre/post bytes needed to restore a removed todo's docs."""
    writes = [
        {
            "relative_path": write.relative_path,
            "original_content": write.original_content,
            "rendered_content": write.rendered_content,
            "line": write.line,
            "carrier": write.carrier.value,
            "reason": write.reason,
        }
        for write in plan.writes
    ]
    return json.dumps(writes)


def _decode_removed_doc_reconciliation(
    *,
    todo_id: str,
    project_root: Path,
    slug: str,
    encoded: str | None,
) -> ReconciliationPlan | None:
    """Rehydrate the exact abandonment snapshot retained on a removed todo."""
    if encoded is None:
        return None
    try:
        raw_writes = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ReactivateRefused(reason="invalid_doc_reconciliation", todo_id=todo_id, slug=slug) from exc
    if not isinstance(raw_writes, list):
        raise ReactivateRefused(reason="invalid_doc_reconciliation", todo_id=todo_id, slug=slug)
    writes: list[ReconciliationWrite] = []
    for raw_write in raw_writes:
        if not isinstance(raw_write, dict):
            raise ReactivateRefused(reason="invalid_doc_reconciliation", todo_id=todo_id, slug=slug)
        relative_path = raw_write.get("relative_path")
        original_content = raw_write.get("original_content")
        rendered_content = raw_write.get("rendered_content")
        line = raw_write.get("line")
        carrier = raw_write.get("carrier")
        reason = raw_write.get("reason")
        if (
            not isinstance(relative_path, str)
            or (original_content is not None and not isinstance(original_content, str))
            or (rendered_content is not None and not isinstance(rendered_content, str))
            or not isinstance(line, int)
            or not isinstance(carrier, str)
            or not isinstance(reason, str)
        ):
            raise ReactivateRefused(reason="invalid_doc_reconciliation", todo_id=todo_id, slug=slug)
        try:
            carrier_value = ReconciliationCarrier(carrier)
        except ValueError as exc:
            raise ReactivateRefused(reason="invalid_doc_reconciliation", todo_id=todo_id, slug=slug) from exc
        writes.append(
            ReconciliationWrite(
                path=project_root / relative_path,
                relative_path=relative_path,
                original_content=original_content,
                rendered_content=rendered_content,
                line=line,
                carrier=carrier_value,
                reason=reason,
            )
        )
    return ReconciliationPlan(slug=slug, mode=ReconciliationMode.ABANDON, writes=tuple(writes))


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
        work_feedback: str | None = None,
    ) -> None:
        self.reason = reason
        self.todo_id = todo_id
        self.slug = slug
        self.work_feedback = work_feedback
        super().__init__(f"reactivate refused for {todo_id} ({slug}): {reason}")


class TodoIdentityActionRefused(Exception):
    """An identity-addressed action targeted a todo outside its live status band."""

    def __init__(self, *, todo_id: str, slug: str, status: TodoStatus) -> None:
        self.todo_id = todo_id
        self.slug = slug
        self.status = status
        if status == TodoStatus.REMOVED:
            detail = _REMOVED_IDENTITY_ACTION_REFUSAL.format(todo_id=todo_id, slug=slug)
        elif status == TodoStatus.DELIVERED:
            detail = _DELIVERED_IDENTITY_ACTION_REFUSAL.format(todo_id=todo_id, slug=slug)
        else:
            detail = _IDENTITY_ACTION_REFUSAL.format(todo_id=todo_id, slug=slug, status=status.value)
        super().__init__(detail)


class TodoIdentityNotFound(Exception):
    """The supplied durable todo identity does not exist in this project."""

    def __init__(self, *, todo_id: str) -> None:
        self.todo_id = todo_id
        super().__init__(_IDENTITY_NOT_FOUND.format(todo_id=todo_id))


async def _restore_set_aside_claim(db_session: SqlAsyncSession, todo_id: str, removed_claim: str | None) -> None:
    """Put the ``active_runner`` a removal set aside back into the todo's state.

    Removal records the claim it popped from the state. On a GitHub-backed project the driver that claim names
    may still run on another computer, so the claim returns with the todo: the master judges it like any other
    and clears it when its holder ended. A start of a removed todo is refused for want of live state, so this
    write cannot race an admission.
    """
    if removed_claim is None:
        return
    try:
        claim = json.loads(removed_claim)
    except (TypeError, ValueError):
        return
    runner = claim.get(_ACTIVE_RUNNER_FIELD) if isinstance(claim, dict) else None
    if not isinstance(runner, str) or not runner:
        return
    state_model = await db_session.get(TodoStateModel, todo_id)
    if state_model is None:
        return
    state = json.loads(state_model.state)
    if not isinstance(state, dict):
        return
    state[_ACTIVE_RUNNER_FIELD] = runner
    state_model.state = json.dumps(canonicalize_state_for_storage(state))
    state_model.updated_at = datetime.now(UTC).isoformat()
    db_session.add(state_model)


class TodosDbTodoSoftDeleteMixin:
    """Persistence logic for soft-removed todo entries and their retention lifecycle."""

    db_path: str

    async def resolve_live_slug_by_id(self, todo_id: str) -> TodoIdentityResolution:
        """Resolve a durable todo id only while its row is in the live slug band."""
        async with cast(Any, self)._session() as session:
            entry = cast(Todo | None, await session.get(Todo, todo_id))
        if entry is None:
            raise TodoIdentityNotFound(todo_id=todo_id)
        status = TodoStatus(entry.status)
        if status not in _LIVE_SLUG_STATUSES:
            raise TodoIdentityActionRefused(todo_id=todo_id, slug=entry.slug, status=status)
        return TodoIdentityResolution(slug=WorkItemId(entry.slug), status=status)

    async def soft_remove_from_todo(
        self,
        slug: str,
        *,
        cwd: str,
        removal_context: RemovalContext | None = None,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Soft-remove the live (active/icebox) entry for a slug.

        The durable record survives: status flips to ``removed``, ``removed_at``
        is stamped, and the entry's outgoing dependency slugs are snapshotted into
        ``removed_deps`` keyed by the row's stable id. Live ``todo_deps`` rows
        are scrubbed in *both* directions so the slug is free for immediate reuse
        and so no live consumer still points at the tombstoned entry. State,
        artifacts, and artifact version history are intentionally retained.

        Before the DB mutation commits, the owner-session path snapshots and
        applies this slug's pending documentation abandonment: markers fold to
        their undelivered side and a pending document only this slug delivers is
        deleted, both captured for reactivation. After the
        durable removal lands, it conditionally commits that exact-path cleanup
        only when every affected path was pre-clean, then runs slug-keyed
        filesystem teardown through :func:`cleanup_delivered_slug` (worktree +
        local/remote branch + workspace dir). All slug-keyed teardown happens
        *here*, while the slug still unambiguously names this entry — the eventual
        retention purge is strictly row-id-addressed and performs no slug-keyed
        work. Drafts skip the filesystem teardown because they own no working
        resources.

        Returns ``False`` when no live entry exists for ``slug``; otherwise
        ``True`` after the DB mutation lands (and, for caller-owned sessions,
        before the caller's commit — the post-commit cleanup branch only fires
        on the owns-session path).
        """
        is_draft = False
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        reconciliation_plan: ReconciliationPlan | None = None
        db_commit_landed = False
        async with _soft_remove_lock(cast(Any, self).db_path):
            try:
                if owns_session:
                    connection = await db_session.connection()
                    await connection.exec_driver_sql("BEGIN IMMEDIATE")

                entry = await cast(Any, self)._active_entry(db_session, slug)
                if entry is None:
                    if await cast(Any, self)._is_holder_status(db_session, slug):
                        if owns_session:
                            await db_session.rollback()
                        raise HolderWriteRefused(
                            f"todo '{slug}' is a holder outside the todo lifecycle and cannot be removed; "
                            "remove its children instead"
                        )
                    if owns_session:
                        await db_session.rollback()
                    return False

                if owns_session:
                    receipt = reconcile_lifecycle_markers(Path(cwd), slug, MarkerMoment.ABANDON)
                    if not receipt.succeeded or receipt.plan is None:
                        raise RuntimeError(f"marker reconciliation failed for removal of {slug}: {receipt.reason}")
                    reconciliation_plan = receipt.plan

                outgoing_deps = await db_session.exec(
                    select(TodoDep.depends_on).where(TODO_DEPS_TABLE.c.slug == slug).order_by(TodoDep.depends_on)
                )
                outgoing = [str(dep) for dep in outgoing_deps.all()]

                active_runner: str | None = None
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
                        raw_active_runner = state.pop("active_runner", None)
                        if isinstance(raw_active_runner, str):
                            active_runner = raw_active_runner
                        state["manually_started"] = False
                        state_model.state = json.dumps(canonicalize_state_for_storage(state))
                        state_model.updated_at = datetime.now(UTC).isoformat()
                        db_session.add(state_model)

                now = datetime.now(UTC).isoformat()
                entry.prev_status = entry.status
                entry.status = "removed"
                entry.removed_at = now
                entry.removed_deps = json.dumps(outgoing) if outgoing else None
                entry.removed_claim = json.dumps(
                    {
                        "active_runner": active_runner,
                        "force": removal_context["force"] if removal_context is not None else False,
                        "operation_id": removal_context["operation_id"] if removal_context is not None else None,
                        "caller_session_id": (
                            removal_context["caller_session_id"] if removal_context is not None else None
                        ),
                    },
                    sort_keys=True,
                )
                entry.removed_doc_reconciliation = (
                    _encode_removed_doc_reconciliation(reconciliation_plan) if reconciliation_plan is not None else None
                )
                entry.updated_at = now
                db_session.add(entry)

                await db_session.exec(delete(TodoDep).where(TODO_DEPS_TABLE.c.slug == slug))
                await db_session.exec(delete(TodoDep).where(TODO_DEPS_TABLE.c.depends_on == slug))

                if owns_session:
                    await db_session.commit()
                    db_commit_landed = True
                    cast(Any, self)._on_mutation("todo_removed", None)
            except Exception:
                if owns_session and not db_commit_landed:
                    await db_session.rollback()
                    if reconciliation_plan is not None:
                        restore_lifecycle_markers(Path(cwd), slug, reconciliation_plan)
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
        cwd: str,
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
        tombstone fields are cleared. On a project on the GitHub store the
        ``active_runner`` the removal set aside is restored to the todo's state
        first, so a driver still running on another computer stays held. Inbound third-party edges are NOT
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
                    work_feedback=_REACTIVATE_NOT_REMOVED_FEEDBACK,
                )

            live_twin = await cast(Any, self)._active_entry(db_session, entry.slug)
            if live_twin is not None:
                raise ReactivateRefused(
                    reason="live_twin_exists",
                    todo_id=todo_id,
                    slug=entry.slug,
                    work_feedback=_REACTIVATE_LIVE_TWIN_FEEDBACK,
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

            reconciliation_plan = _decode_removed_doc_reconciliation(
                todo_id=todo_id,
                project_root=Path(cwd),
                slug=entry.slug,
                encoded=entry.removed_doc_reconciliation,
            )
            if reconciliation_plan is not None:
                receipt = restore_lifecycle_markers(Path(cwd), entry.slug, reconciliation_plan)
                if not receipt.succeeded:
                    raise ReactivateRefused(
                        reason="doc_reconciliation_failed",
                        todo_id=todo_id,
                        slug=entry.slug,
                    )

            if selected_workflow_store_backend(Path(cwd)) is TodoStoreBackend.GITHUB:
                await _restore_set_aside_claim(db_session, todo_id, entry.removed_claim)

            entry.status = restored_status
            entry.prev_status = None
            entry.removed_at = None
            entry.removed_deps = None
            entry.removed_claim = None
            entry.removed_doc_reconciliation = None
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

    async def has_removed_todo(self, slug: str) -> bool:
        """Return whether retained removed history exists for ``slug``."""
        async with cast(Any, self)._session() as session:
            result = await session.exec(
                apply_todo_identity_pin(
                    select(Todo.id).where(TODO_TABLE.c.slug == slug),
                    self,
                    slug,
                )
                .where(TODO_TABLE.c.status == "removed")
                .limit(1)
            )
            return result.first() is not None

    async def removed_todo_claims_active_runner(self, slug: str, session_id: str) -> bool:
        """Return whether a retained removal claim names this former lifecycle driver."""
        async with cast(Any, self)._session() as session:
            result = await session.exec(
                apply_todo_identity_pin(
                    select(Todo.removed_claim).where(TODO_TABLE.c.slug == slug),
                    self,
                    slug,
                ).where(TODO_TABLE.c.status == "removed")
            )
            for removed_claim in result.all():
                try:
                    claim = json.loads(removed_claim)
                except (TypeError, ValueError):
                    continue
                if isinstance(claim, dict) and claim.get("active_runner") == session_id:
                    return True
        return False

    async def find_live_slug_conflict(self, slug: str, *, session: SqlAsyncSession | None = None) -> str | None:
        """Return the status of a conflicting active/icebox/holder row, or None.

        Mirrors exactly the widened unique-slug index band
        (``active``/``icebox``/``holder``), so creation preflight and the
        storage-level uniqueness guarantee agree on what counts as a live
        conflict — a delivered or removed slug is never reported here and
        stays creatable, per the existing contract.
        """
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            result = await db_session.exec(
                apply_todo_identity_pin(
                    select(Todo.status).where(TODO_TABLE.c.slug == slug),
                    self,
                    slug,
                )
                .where(TODO_TABLE.c.status.in_({status.value for status in _LIVE_SLUG_STATUSES}))
                .limit(1)
            )
            status = result.first()
            return str(status) if status is not None else None
        finally:
            if owns_session:
                await db_session.close()

    async def slug_conflicts_non_removed(self, slug: str, *, session: SqlAsyncSession | None = None) -> bool:
        """Return whether any non-removed todo row already holds a slug."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            result = await db_session.exec(
                apply_todo_identity_pin(
                    select(Todo.id).where(TODO_TABLE.c.slug == slug),
                    self,
                    slug,
                )
                .where(TODO_TABLE.c.status != "removed")
                .limit(1)
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
