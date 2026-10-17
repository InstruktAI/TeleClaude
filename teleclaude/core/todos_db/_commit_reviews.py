"""Repository-scoped durable commit-review evidence."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core.todos_db._models import CommitReview, DocumentationTransfer, Todo
from teleclaude.core.workflow_store.types import CommitReviewRecord, DocumentationTransferRecord
from teleclaude.types.todos import CommitReviewVerdict

_BEGIN_IMMEDIATE_SQL = "BEGIN IMMEDIATE"


class TodosDbCommitReviewsMixin:
    def slug_recorded_sync(self, slug: str) -> bool:
        """Return recorded existence across active and historical todo rows."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            result = session.exec(select(Todo.id).where(cast(InstrumentedAttribute[str], Todo.slug) == slug)).first()
        return result is not None

    async def documentation_transfers(self, target_slug: str) -> tuple[DocumentationTransferRecord, ...]:
        """Read the exact continuity evidence created by first-child grouping."""
        async with self._session() as session:  # type: ignore[attr-defined]
            return await self.documentation_transfers_in_session(session, target_slug)

    async def documentation_transfers_in_session(
        self,
        session: SqlAsyncSession,
        target_slug: str,
    ) -> tuple[DocumentationTransferRecord, ...]:
        """Read continuity evidence inside a caller-owned workflow transaction."""
        target_attr = cast(InstrumentedAttribute[str], DocumentationTransfer.target_slug)
        id_attr = cast(InstrumentedAttribute[int | None], DocumentationTransfer.id)
        rows = (
            await session.exec(select(DocumentationTransfer).where(target_attr == target_slug).order_by(id_attr))
        ).all()
        return _transfer_records_from_rows(rows)

    async def begin_commit_review_evidence_snapshot_in_session(self, session: SqlAsyncSession) -> None:
        """Reserve SQLite's writer transaction before evidence reads in a caller-owned session."""
        connection = await session.connection()
        await connection.exec_driver_sql(_BEGIN_IMMEDIATE_SQL)

    def _append_documentation_transfer_in_session(
        self,
        session: SqlAsyncSession,
        record: DocumentationTransferRecord,
    ) -> None:
        """Append transfer continuity within the caller's todo transaction."""
        session.add(
            DocumentationTransfer(
                source_slug=record.source_slug,
                target_slug=record.target_slug,
                parent_id=record.parent_id,
                source_sha=record.source_sha,
                source_path_blobs=json.dumps(record.source_path_blobs),
                target_path_blobs=json.dumps(record.target_path_blobs),
                transition_id=record.transition_id,
                reconciliation_commit=record.reconciliation_commit,
            )
        )

    async def append_commit_reviews(self, records: tuple[CommitReviewRecord, ...]) -> None:
        """Append a validated batch as one durable transaction."""
        async with self._session() as session:  # type: ignore[attr-defined]
            async with session.begin():
                for record in records:
                    producers = None if record.producer_session_ids is None else json.dumps(record.producer_session_ids)
                    session.add(
                        CommitReview(
                            sha=record.sha,
                            verdict=record.verdict.value,
                            reviewer_session_id=record.reviewer_session_id,
                            producer_session_ids=producers,
                            stamped_at=record.stamped_at,
                            reason=record.reason,
                            migration_source=record.migration_source,
                        )
                    )

    async def commit_review_records(self, shas: tuple[str, ...]) -> tuple[CommitReviewRecord, ...]:
        """Read append-only review evidence for the requested full SHAs."""
        if not shas:
            return ()
        async with self._session() as session:  # type: ignore[attr-defined]
            return await self.commit_review_records_in_session(session, shas)

    async def commit_review_records_in_session(
        self,
        session: SqlAsyncSession,
        shas: tuple[str, ...],
    ) -> tuple[CommitReviewRecord, ...]:
        """Read review evidence inside a caller-owned workflow transaction."""
        if not shas:
            return ()
        id_attr = cast(InstrumentedAttribute[int | None], CommitReview.id)
        rows = (
            await session.exec(
                select(CommitReview)
                .where(cast(InstrumentedAttribute[str], CommitReview.sha).in_(shas))
                .order_by(CommitReview.stamped_at, id_attr)
            )
        ).all()
        return _records_from_rows(rows)

    def commit_review_records_sync(self, shas: tuple[str, ...]) -> tuple[CommitReviewRecord, ...]:
        """Synchronous review-evidence query for lifecycle projections."""
        if not shas:
            return ()
        async_attr = cast(InstrumentedAttribute[str], CommitReview.sha)
        id_attr = cast(InstrumentedAttribute[int | None], CommitReview.id)
        with self._sync_session() as session:  # type: ignore[attr-defined]
            rows = session.exec(
                select(CommitReview).where(async_attr.in_(shas)).order_by(CommitReview.stamped_at, id_attr)
            ).all()
        return _records_from_rows(rows)


def _records_from_rows(rows: Sequence[CommitReview]) -> tuple[CommitReviewRecord, ...]:
    records: list[CommitReviewRecord] = []
    for row in rows:
        producers = None
        if row.producer_session_ids is not None:
            try:
                decoded = json.loads(row.producer_session_ids)
            except (TypeError, ValueError):
                decoded = []
            if isinstance(decoded, list) and all(isinstance(value, str) for value in decoded):
                producers = tuple(decoded)
        records.append(
            CommitReviewRecord(
                sha=row.sha,
                verdict=CommitReviewVerdict(row.verdict),
                reviewer_session_id=row.reviewer_session_id,
                producer_session_ids=producers,
                stamped_at=row.stamped_at,
                reason=row.reason,
                migration_source=row.migration_source,
            )
        )
    return tuple(records)


def _transfer_records_from_rows(rows: Sequence[DocumentationTransfer]) -> tuple[DocumentationTransferRecord, ...]:
    records: list[DocumentationTransferRecord] = []
    for row in rows:
        try:
            source_pairs = json.loads(row.source_path_blobs)
            target_pairs = json.loads(row.target_path_blobs)
        except (TypeError, ValueError):
            continue
        if not _valid_path_blob_pairs(source_pairs) or not _valid_transfer_path_blob_rows(target_pairs):
            continue
        source_paths = {item[0] for item in source_pairs}
        if any(item[0] not in source_paths for item in target_pairs):
            continue
        records.append(
            DocumentationTransferRecord(
                source_slug=row.source_slug,
                target_slug=row.target_slug,
                parent_id=row.parent_id,
                source_sha=row.source_sha,
                source_path_blobs=tuple((item[0], item[1]) for item in source_pairs),
                target_path_blobs=tuple((item[0], item[1], item[2], item[3], item[4]) for item in target_pairs),
                transition_id=row.transition_id,
                reconciliation_commit=row.reconciliation_commit,
            )
        )
    return tuple(records)


def _valid_path_blob_pairs(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, list) and len(item) == 2 and all(isinstance(part, str) and part for part in item)
        for item in value
    )


def _valid_transfer_path_blob_rows(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, list) and len(item) == 5 and all(isinstance(part, str) and part for part in item)
        for item in value
    )
