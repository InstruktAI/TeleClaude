"""Persist exact documentation continuity within the todo creation transaction."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core.next_machine.marker_reconciliation import MarkerReceipt
from teleclaude.core.todos_db._errors import HolderReconciliationRefused
from teleclaude.core.workflow_store.types import DocumentationAdmission, DocumentationTransferRecord
from teleclaude.docs_reconcile import pending_document_carriers
from teleclaude.git import GitCommandError, Repo
from teleclaude.snippet_validation import companion_slug

_HASH_OBJECT_PATH_ARGS = ("--path",)
_INDEX_PATH_ARGS = ("--stage", "--")
_STAGE_ZERO = "0"
_COMMIT_TREE_PATH_TEMPLATE = "{sha}:{path}"
_NO_RECONCILIATION_COMMIT = "cannot group under {slug!r}: source review has no committed reconciliation"
_HASH_UNAVAILABLE = "cannot record grouped documentation evidence for {path!r}: {error}"
_HASH_MISMATCH = "grouped documentation path {path!r} differs from reconciliation commit {commit}"
_EMPTY_TARGET_EVIDENCE = "grouped documentation reconciliation produced no target blob evidence"
_COMPANION_NAME_TEMPLATE = ".{slug}.md"
_SOURCE_SET_CHANGED = "pending documentation carriers for {slug!r} changed after admission; resubmit the create request"
_SOURCE_BLOB_CHANGED = "pending documentation source {path!r} changed after admission; resubmit the create request"
_TARGET_PATH_MISSING = "grouped documentation target path {path!r} is absent after reconciliation"
_TARGET_PATH_NOT_PLANNED = "grouped documentation target path {path!r} was not in the reconciliation plan"


class DocumentationTransferWriter(Protocol):
    def _append_documentation_transfer_in_session(
        self,
        session: SqlAsyncSession,
        record: DocumentationTransferRecord,
    ) -> None: ...


def _target_path(project_root: Path, source_path: str, old_slug: str, new_slug: str) -> str:
    """Resolve a companion's identity-renamed destination, otherwise retain its path."""
    rooted_source = project_root / source_path
    if companion_slug(rooted_source) != old_slug:
        return source_path
    return source_path.replace(
        _COMPANION_NAME_TEMPLATE.format(slug=old_slug),
        _COMPANION_NAME_TEMPLATE.format(slug=new_slug),
    )


def validate_documentation_admission(
    project_root: Path,
    admission: DocumentationAdmission,
) -> None:
    """Revalidate the pinned carrier set and blobs before the split can write."""
    if admission.parent_slug is None:
        raise HolderReconciliationRefused(_SOURCE_SET_CHANGED.format(slug=admission.parent_slug))
    current_paths = tuple(
        sorted(
            path.relative_to(project_root).as_posix()
            for path in pending_document_carriers(project_root, admission.parent_slug)
        )
    )
    expected_paths = tuple(sorted(path for path, _ in admission.carrier_path_blobs))
    if current_paths != expected_paths:
        raise HolderReconciliationRefused(_SOURCE_SET_CHANGED.format(slug=admission.parent_slug))
    repo = Repo(str(project_root))
    for path, expected_blob in admission.carrier_path_blobs:
        current_blob = str(repo.git.hash_object(*_HASH_OBJECT_PATH_ARGS, path, path)).strip()
        if current_blob != expected_blob:
            raise HolderReconciliationRefused(_SOURCE_BLOB_CHANGED.format(path=path))
        if not admission.sources:
            continue
        index_lines = repo.git.ls_files(*_INDEX_PATH_ARGS, path).splitlines()
        fields = index_lines[0].split() if index_lines else []
        if len(index_lines) != 1 or len(fields) < 3 or fields[2] != _STAGE_ZERO or fields[1] != expected_blob:
            raise HolderReconciliationRefused(_SOURCE_BLOB_CHANGED.format(path=path))


def persist_documentation_transfers(
    host: DocumentationTransferWriter,
    session: SqlAsyncSession,
    admission: DocumentationAdmission,
    receipt: MarkerReceipt,
    target_slug: str,
    project_root: Path,
) -> None:
    """Persist exact source and projected blob evidence before grouping commits."""
    if admission.parent_slug is None or admission.parent_id is None:
        raise HolderReconciliationRefused(_NO_RECONCILIATION_COMMIT.format(slug=admission.parent_slug))
    if receipt.plan is None or receipt.commit is None:
        raise HolderReconciliationRefused(_NO_RECONCILIATION_COMMIT.format(slug=admission.parent_slug))
    repo = Repo(str(project_root))
    sources_by_sha: dict[str | None, list[tuple[str, str, str, str]]] = {}
    for source in admission.sources:
        sources_by_sha.setdefault(source.source_sha, []).append(
            (source.relative_path, source.blob_id, source.carrier_path, source.carrier_blob_id)
        )
    if not sources_by_sha:
        source_refs = dict(admission.source_commit_by_path)
        for path, blob_id in admission.carrier_path_blobs:
            source_sha = source_refs.get(path)
            sources_by_sha.setdefault(source_sha, []).append((path, blob_id, path, blob_id))
    for source_sha, source_paths in sources_by_sha.items():
        target_path_blobs: list[tuple[str, str, str, str, str]] = []
        for source_path, _source_blob, carrier_path, carrier_blob in source_paths:
            relative_path = _target_path(project_root, carrier_path, admission.parent_slug, target_slug)
            if not (project_root / relative_path).exists():
                raise HolderReconciliationRefused(_TARGET_PATH_MISSING.format(path=relative_path))
            if not any(write.relative_path == relative_path for write in receipt.plan.writes):
                raise HolderReconciliationRefused(_TARGET_PATH_NOT_PLANNED.format(path=relative_path))
            try:
                target_blob = str(repo.git.hash_object(*_HASH_OBJECT_PATH_ARGS, relative_path, relative_path)).strip()
                committed_blob = str(
                    repo.git.rev_parse(_COMMIT_TREE_PATH_TEMPLATE.format(sha=receipt.commit, path=relative_path))
                ).strip()
            except GitCommandError as exc:
                raise HolderReconciliationRefused(_HASH_UNAVAILABLE.format(path=relative_path, error=exc)) from exc
            if target_blob != committed_blob:
                raise HolderReconciliationRefused(_HASH_MISMATCH.format(path=relative_path, commit=receipt.commit))
            target_path_blobs.append((source_path, carrier_path, carrier_blob, relative_path, target_blob))
        if not target_path_blobs:
            raise HolderReconciliationRefused(_EMPTY_TARGET_EVIDENCE)
        host._append_documentation_transfer_in_session(
            session,
            DocumentationTransferRecord(
                source_slug=admission.parent_slug,
                target_slug=target_slug,
                parent_id=admission.parent_id,
                source_sha=source_sha,
                source_path_blobs=tuple((source_path, source_blob) for source_path, source_blob, _, _ in source_paths),
                target_path_blobs=tuple(target_path_blobs),
                transition_id=receipt.transition_id,
                reconciliation_commit=receipt.commit,
            ),
        )
