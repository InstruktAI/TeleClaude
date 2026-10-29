"""Pure rules shared by every path that saves or reads workflow artifacts as native issue artifacts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from teleclaude.core.workflow_store.github_io_models import GitHubArtifact, GitHubArtifactVersion
from teleclaude.core.workflow_store.github_record import ArtifactRecord, ArtifactVersionEntry, WorkflowField

__all__ = [
    "ENTRY_WINDOW",
    "append_entry",
    "artifact_type",
    "content_digest",
    "current_version_content",
    "served_version_content",
    "version_entry_from_row",
]

# GitHub serves the 30 newest versions of an artifact; a record names no more than that.
ENTRY_WINDOW = 30
_ENCODING = "utf-8"
_PLAN_ARTIFACTS = frozenset({"implementation-plan", "task-plan"})
_PLAN_TYPE = "plan"
_GENERIC_TYPE = "generic"


def artifact_type(name: str) -> str:
    """The issue-artifact type a workflow artifact is created with; GitHub fixes a type at creation."""
    return _PLAN_TYPE if name in _PLAN_ARTIFACTS else _GENERIC_TYPE


def content_digest(content: str) -> str:
    return hashlib.sha256(content.encode(_ENCODING)).hexdigest()


def version_entry_from_row(ordinal: int, row: Mapping[str, object]) -> ArtifactVersionEntry:
    """The record entry for one local version row, carrying the writer and time GitHub cannot keep."""
    digest = row.get(WorkflowField.DIGEST)
    updated_by = row.get(WorkflowField.UPDATED_BY)
    created_at = row.get(WorkflowField.CREATED_AT)
    return ArtifactVersionEntry(
        ordinal=ordinal,
        digest=digest if isinstance(digest, str) else content_digest(str(row.get(WorkflowField.CONTENT, ""))),
        updated_by=updated_by if isinstance(updated_by, str) else None,
        created_at=created_at if isinstance(created_at, str) else None,
    )


def append_entry(
    record: ArtifactRecord | None, artifact_number: int, entry_row: Mapping[str, object]
) -> ArtifactRecord:
    """The artifact's record after one more saved version: the next ordinal, the window of the newest entries."""
    entries: Sequence[ArtifactVersionEntry] = record.entries if record is not None and record.present else ()
    ordinal = entries[-1].ordinal + 1 if entries else 1
    entry = version_entry_from_row(ordinal, entry_row)
    return ArtifactRecord(artifact_number=artifact_number, entries=[*entries, entry][-ENTRY_WINDOW:])


def current_version_content(artifact: GitHubArtifact, bot_id: int, digest: str) -> str | None:
    """The artifact's current body when the platform bot saved it and it digests to `digest`, else None."""
    if artifact.updated_by is None or artifact.updated_by.actor_id != bot_id:
        return None
    return artifact.body if content_digest(artifact.body) == digest else None


def served_version_content(versions: Sequence[GitHubArtifactVersion], bot_id: int, digest: str) -> str | None:
    """The newest served version the platform bot saved that digests to `digest`, else None."""
    for version in versions:
        if version.actor is not None and version.actor.actor_id == bot_id and content_digest(version.body) == digest:
            return version.body
    return None
