"""Admission evidence for declared pending documentation."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.commit_identity import PLANNED_TODO_TRAILER_KEY, TODO_TRAILER_KEY
from teleclaude.core.workflow_store.types import (
    CommitReviewRecord,
    DocumentationEvidenceSnapshot,
    DocumentationTransferRecord,
    ReviewedDocumentationSource,
)
from teleclaude.docs_reconcile import pending_document_carriers
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.types.todos import CommitReviewVerdict

_MAIN_REF = "main"
_NO_DOCUMENTATION_REVISION = ""
_FIELD_SEPARATOR = "\x1f"
_LINE_SEPARATOR = "\n"
_TRAILER_LOG_FORMAT = (
    "--format=%H%x1f%(trailers:key={todo},valueonly,unfold)%x1f%(trailers:key={planned},valueonly,unfold)"
)
_DIFF_TREE_ARGS = ("--no-commit-id", "--name-only", "-r")
_INDEX_ARGS = ("--stage", "--")
_HASH_ARGS = ("--path",)
_TRAILER_VALUE_SEPARATOR = ","
_STAGE_ZERO = "0"
_ANCESTOR_ARGUMENT = "--is-ancestor"
_COMMIT_TREE_PATH_TEMPLATE = "{sha}:{path}"
_PARENT_COMMIT_TREE_PATH_TEMPLATE = "{sha}^1:{path}"
_INDEX_DIVERGENCE_REASON = "the worktree and index do not contain one identical stage-zero blob"
_UNREVIEWED_TRANSFER_REASON = "the inherited source has no independent review identity"
_REFUSAL_TEMPLATE = "documentation admission refused for {path}: {reason}"
_NO_ASSOCIATED_COMMIT = (
    "no associated canonical-main commit changes this declared document; commit it with --todo {slug}"
)
_NO_REVIEW = "associated commit {sha} has no independent approve stamp; complete commit review"
_STALE_CONTENT = "current worktree/index content does not match the associated reviewed revision {sha}"
_UNREADABLE = "pending documentation inventory or Git evidence could not be read: {detail}"
_SNAPSHOT_ERROR = "pending documentation source snapshot could not be read: {detail}"
_MAIN_REVISION_CHANGED = "canonical main changed during documentation admission; submit a fresh request"
_SNAPSHOT_CHANGED = "documentation evidence changed before lifecycle admission; submit a fresh request"


class _EvidenceReader(Protocol):
    async def commit_review_records(self, shas: tuple[str, ...]) -> tuple[CommitReviewRecord, ...]: ...

    async def documentation_transfers(self, target_slug: str) -> tuple[DocumentationTransferRecord, ...]: ...


class _TransactionalEvidenceReader(_EvidenceReader, Protocol):
    async def begin_commit_review_evidence_snapshot_in_session(self, session: SqlAsyncSession) -> None: ...

    async def commit_review_records_in_session(
        self,
        session: SqlAsyncSession,
        shas: tuple[str, ...],
    ) -> tuple[CommitReviewRecord, ...]: ...

    async def documentation_transfers_in_session(
        self,
        session: SqlAsyncSession,
        target_slug: str,
    ) -> tuple[DocumentationTransferRecord, ...]: ...


class DocumentationEvidenceRefused(ValueError):
    """A pending documentation declaration lacks current independent evidence."""


def snapshot_pending_carrier_blobs(project_root: Path, slug: str) -> tuple[tuple[str, str], ...]:
    """Capture canonical blobs for a parked first-child source without judging its review state."""
    try:
        repo = Repo(str(project_root))
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        raise DocumentationEvidenceRefused(_SNAPSHOT_ERROR.format(detail=exc)) from exc
    snapshots = []
    for path in pending_document_carriers(project_root, slug):
        relative_path = path.relative_to(project_root).as_posix()
        try:
            blob_id = cast(str, repo.git.hash_object(*_HASH_ARGS, relative_path, relative_path)).strip()
        except (GitCommandError, OSError, ValueError, RuntimeError) as exc:
            raise DocumentationEvidenceRefused(_SNAPSHOT_ERROR.format(detail=exc)) from exc
        snapshots.append((relative_path, blob_id))
    return tuple(snapshots)


def source_commit_refs(project_root: Path, slug: str) -> tuple[tuple[str, str | None], ...]:
    """Preserve the latest known source association without claiming review approval."""
    repo = Repo(str(project_root))
    paths = tuple(path.relative_to(project_root).as_posix() for path in pending_document_carriers(project_root, slug))
    if not paths:
        return ()
    commits = _associated_commits(repo, slug)
    changed = {sha: _changed_paths(repo, sha) for sha in commits}
    return tuple((path, next((sha for sha in commits if path in changed[sha]), None)) for path in paths)


def _associated_commits(repo: Repo, slug: str) -> tuple[str, ...]:
    raw = repo.git.log(
        _MAIN_REF,
        _TRAILER_LOG_FORMAT.format(todo=TODO_TRAILER_KEY, planned=PLANNED_TODO_TRAILER_KEY),
    )
    matches: list[str] = []
    for line in raw.split(_LINE_SEPARATOR):
        fields = line.split(_FIELD_SEPARATOR)
        if len(fields) != 3:
            continue
        sha, todo_values, planned_values = fields
        values = {
            value.strip()
            for value in (todo_values + _TRAILER_VALUE_SEPARATOR + planned_values).split(_TRAILER_VALUE_SEPARATOR)
            if value.strip()
        }
        if slug in values:
            matches.append(sha)
    return tuple(matches)


def _changed_paths(repo: Repo, sha: str) -> frozenset[str]:
    output = repo.git.diff_tree(*_DIFF_TREE_ARGS, sha)
    return frozenset(line for line in output.split(_LINE_SEPARATOR) if line)


def _latest_independent_records(records: tuple[CommitReviewRecord, ...]) -> dict[str, CommitReviewRecord]:
    latest: dict[str, CommitReviewRecord] = {}
    for record in records:
        if not record.independent:
            continue
        latest[record.sha] = record
    return latest


async def require_reviewed_pending_documentation(
    project_root: Path,
    store: object,
    slugs: tuple[str, ...],
    *,
    session: SqlAsyncSession | None = None,
) -> DocumentationEvidenceSnapshot:
    """Require independently approved associated revisions for every declared carrier."""
    try:
        repo = Repo(str(project_root))
        carriers = tuple(
            (path.relative_to(project_root).as_posix(), owner)
            for owner in slugs
            for path in pending_document_carriers(project_root, owner)
        )
        if not carriers:
            return DocumentationEvidenceSnapshot(
                main_revision=_NO_DOCUMENTATION_REVISION,
                checked_slugs=slugs,
                carrier_blobs=(),
                sources=(),
                review_records=(),
                transfer_records=(),
            )
        main_revision = repo.git.rev_parse(_MAIN_REF).strip()
        associated_by_slug = {slug: _associated_commits(repo, slug) for slug in slugs}
        associated = tuple(dict.fromkeys(sha for shas in associated_by_slug.values() for sha in shas))
        paths_by_sha = {sha: _changed_paths(repo, sha) for sha in associated}
        if session is not None:
            transactional_transfer_reader = cast(_TransactionalEvidenceReader, store)
            await transactional_transfer_reader.begin_commit_review_evidence_snapshot_in_session(session)
            transfers_by_slug = {
                slug: await transactional_transfer_reader.documentation_transfers_in_session(session, slug)
                for slug in slugs
            }
        else:
            transfer_reader = cast(_EvidenceReader, store)
            transfers_by_slug = {slug: await transfer_reader.documentation_transfers(slug) for slug in slugs}
        relevant: dict[
            tuple[str, str],
            tuple[str, DocumentationTransferRecord | None],
        ] = {}
        for path, owner in carriers:
            candidates = [sha for sha in associated_by_slug[owner] if path in paths_by_sha[sha]]
            if candidates:
                relevant[(path, owner)] = (candidates[0], None)
                continue
            transfer = next(
                (
                    item
                    for item in reversed(transfers_by_slug[owner])
                    if item.source_sha is not None
                    and any(target_path == path for _, _, _, target_path, _ in item.target_path_blobs)
                ),
                None,
            )
            if transfer is None or transfer.source_sha is None:
                raise DocumentationEvidenceRefused(
                    _REFUSAL_TEMPLATE.format(path=path, reason=_NO_ASSOCIATED_COMMIT.format(slug=owner))
                )
            relevant[(path, owner)] = (transfer.source_sha, transfer)
        required_shas = tuple(dict.fromkeys(sha for sha, _ in relevant.values()))
        if session is not None:
            transactional_review_reader = cast(_TransactionalEvidenceReader, store)
            records = await transactional_review_reader.commit_review_records_in_session(session, required_shas)
        else:
            review_reader = cast(_EvidenceReader, store)
            records = await review_reader.commit_review_records(required_shas)
        latest = _latest_independent_records(records)
        proven_sources: list[ReviewedDocumentationSource] = []
        carrier_blobs: list[tuple[str, str, str]] = []
        used_transfers: list[DocumentationTransferRecord] = []
        for (path, owner), (sha, transfer) in relevant.items():
            record = latest.get(sha)
            if record is None or record.verdict is not CommitReviewVerdict.APPROVE:
                raise DocumentationEvidenceRefused(
                    _REFUSAL_TEMPLATE.format(path=path, reason=_NO_REVIEW.format(sha=sha))
                )
            if transfer is None:
                reviewed_blob = repo.git.rev_parse(_COMMIT_TREE_PATH_TEMPLATE.format(sha=sha, path=path)).strip()
                current_blob = _current_indexed_blob(repo, path)
                if reviewed_blob != current_blob:
                    raise DocumentationEvidenceRefused(
                        _REFUSAL_TEMPLATE.format(path=path, reason=_STALE_CONTENT.format(sha=sha))
                    )
                proven_sources.append(ReviewedDocumentationSource(owner, sha, path, reviewed_blob, path, current_blob))
                carrier_blobs.append((owner, path, current_blob))
                continue
            _verify_transfer(repo, transfer)
            used_transfers.append(transfer)
            source_blobs = dict(transfer.source_path_blobs)
            for source_path, _parent_path, _parent_blob, target_path, _target_blob in transfer.target_path_blobs:
                if target_path == path:
                    carrier_blob = _current_indexed_blob(repo, path)
                    carrier_blobs.append((owner, path, carrier_blob))
                    proven_sources.append(
                        ReviewedDocumentationSource(
                            owner,
                            sha,
                            source_path,
                            source_blobs[source_path],
                            path,
                            carrier_blob,
                        )
                    )
        current_main_revision = repo.git.rev_parse(_MAIN_REF).strip()
        if current_main_revision != main_revision:
            raise DocumentationEvidenceRefused(_MAIN_REVISION_CHANGED)
        return DocumentationEvidenceSnapshot(
            main_revision=main_revision,
            checked_slugs=slugs,
            carrier_blobs=tuple(sorted(carrier_blobs)),
            sources=tuple(proven_sources),
            review_records=tuple(sorted(latest.values(), key=lambda item: item.sha)),
            transfer_records=tuple(dict.fromkeys(used_transfers)),
        )
    except DocumentationEvidenceRefused:
        raise
    except (
        GitCommandError,
        InvalidGitRepositoryError,
        NoSuchPathError,
        OSError,
        SQLAlchemyError,
        ValueError,
        RuntimeError,
    ) as exc:
        raise DocumentationEvidenceRefused(_UNREADABLE.format(detail=exc)) from exc


def _current_indexed_blob(repo: Repo, path: str) -> str:
    """Return canonical worktree blob only when it exactly matches a stage-zero index entry."""
    worktree_blob = cast(str, repo.git.hash_object(*_HASH_ARGS, path, path)).strip()
    index_lines = repo.git.ls_files(*_INDEX_ARGS, path).split(_LINE_SEPARATOR)
    index_fields = index_lines[0].split() if index_lines and index_lines[0] else []
    if (
        len(index_lines) != 1
        or len(index_fields) < 3
        or index_fields[2] != _STAGE_ZERO
        or index_fields[1] != worktree_blob
    ):
        raise DocumentationEvidenceRefused(_REFUSAL_TEMPLATE.format(path=path, reason=_INDEX_DIVERGENCE_REASON))
    return worktree_blob


def _verify_transfer(repo: Repo, transfer: DocumentationTransferRecord) -> None:
    """Verify the recorded reconciliation commit and every projected path blob."""
    if transfer.source_sha is None:
        raise DocumentationEvidenceRefused(
            _REFUSAL_TEMPLATE.format(path=transfer.target_slug, reason=_UNREVIEWED_TRANSFER_REASON)
        )
    repo.git.merge_base(_ANCESTOR_ARGUMENT, transfer.reconciliation_commit, _MAIN_REF)
    source_blobs = dict(transfer.source_path_blobs)
    for source_path, parent_path, parent_blob, path, blob_id in transfer.target_path_blobs:
        source_blob = repo.git.rev_parse(
            _COMMIT_TREE_PATH_TEMPLATE.format(sha=transfer.source_sha, path=source_path)
        ).strip()
        prior_blob = repo.git.rev_parse(
            _PARENT_COMMIT_TREE_PATH_TEMPLATE.format(sha=transfer.reconciliation_commit, path=parent_path)
        ).strip()
        committed_blob = repo.git.rev_parse(
            _COMMIT_TREE_PATH_TEMPLATE.format(sha=transfer.reconciliation_commit, path=path)
        ).strip()
        current_blob = _current_indexed_blob(repo, path)
        if (
            source_blob != source_blobs[source_path]
            or prior_blob != parent_blob
            or committed_blob != blob_id
            or current_blob != blob_id
        ):
            raise DocumentationEvidenceRefused(
                _REFUSAL_TEMPLATE.format(
                    path=path,
                    reason=_STALE_CONTENT.format(sha=transfer.reconciliation_commit),
                )
            )
