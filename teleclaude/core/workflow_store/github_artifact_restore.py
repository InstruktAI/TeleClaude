"""Restore an item's committed artifact content from its native issue artifacts."""

from __future__ import annotations

from collections.abc import Mapping

from teleclaude.core.todos_db._working_copy import WorkingCopyItemSnapshot
from teleclaude.core.workflow_store.github_artifact_values import current_version_content, served_version_content
from teleclaude.core.workflow_store.github_io import GitHubArtifact, GitHubWorkflowIO
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.core.workflow_store.github_record import ArtifactRecord, ItemRevision, WorkflowField

__all__ = ["ArtifactContentUnavailable", "snapshot_from_revision"]

_EMPTY = ""
_STATE_INCOMPLETE = "state is incomplete"
_CONTENT_INCOMPLETE = "content is incomplete"


class ArtifactContentUnavailable(RuntimeError):
    """A committed version the record names cannot be recovered as a version the platform saved."""


async def snapshot_from_revision(
    io: GitHubWorkflowIO,
    bot_id: int,
    issue_number: int,
    revision: ItemRevision,
    names: frozenset[str] | None = None,
    *,
    native: bool = True,
) -> WorkingCopyItemSnapshot:
    """The working-copy rows a committed revision names: its current content, read from the issue's artifacts.

    One list call downloads every artifact's current body. A committed version that is not the artifact's current
    one, or whose current version a person saved, takes one single-artifact read of the versions GitHub serves.
    Earlier versions the record lists are not read; they come on first use. `names` limits which artifacts the
    snapshot restores from what the list returned, not what the list downloads. A record that
    predates native artifacts names no content: its item is restored without the state it kept in comments.
    """
    todo = dict(revision.todo)
    slug = str(todo.get(WorkflowField.SLUG, _EMPTY))
    named = [
        (name, record)
        for name, record in revision.artifacts.items()
        if record.present and (names is None or name in names)
    ]
    pointer = revision.state_content_pointer
    listing: Mapping[int, GitHubArtifact] = {}
    if named or pointer is not None:
        listing = {artifact.number: artifact for artifact in await io.async_list_artifacts(issue_number)}
    state = dict(revision.state) if revision.state is not None else None
    if pointer is not None:
        if state is None:
            raise ArtifactContentUnavailable(_STATE_INCOMPLETE)
        state[WorkflowField.STATE] = await _committed_content(io, bot_id, issue_number, listing, pointer)
    if state is not None and not native and state.get(WorkflowField.STATE) is None:
        state = None
    if state is not None:
        state.setdefault(WorkflowField.ID, revision.item_id)
        state.setdefault(WorkflowField.SLUG, slug)
        if state.get(WorkflowField.STATE) is None:
            raise ArtifactContentUnavailable(_STATE_INCOMPLETE)
    versions: list[Mapping[str, object]] = []
    artifacts: list[Mapping[str, object]] = []
    for name, record in named:
        content = await _committed_content(io, bot_id, issue_number, listing, record)
        entry = record.entries[-1]
        versions.append(
            {
                WorkflowField.ID: revision.item_id,
                WorkflowField.SLUG: slug,
                WorkflowField.NAME: name,
                WorkflowField.CONTENT: content,
                WorkflowField.DIGEST: entry.digest,
                WorkflowField.UPDATED_BY: entry.updated_by,
                WorkflowField.CREATED_AT: entry.created_at,
            }
        )
        artifacts.append(
            {
                WorkflowField.ID: revision.item_id,
                WorkflowField.SLUG: slug,
                WorkflowField.NAME: name,
                WorkflowField.CONTENT: content,
                WorkflowField.DIGEST: entry.digest,
                WorkflowField.UPDATED_BY: entry.updated_by,
                WorkflowField.UPDATED_AT: entry.created_at,
            }
        )
    return WorkingCopyItemSnapshot(
        item_id=revision.item_id,
        todo=todo,
        state=state,
        dependencies=tuple(dict(edge) for edge in revision.dependencies),
        artifacts=tuple(artifacts),
        versions=tuple(versions),
    )


async def _committed_content(
    io: GitHubWorkflowIO, bot_id: int, issue_number: int, listing: Mapping[int, GitHubArtifact], record: ArtifactRecord
) -> str:
    if not record.entries:
        raise ArtifactContentUnavailable(_CONTENT_INCOMPLETE)
    digest = record.entries[-1].digest
    artifact = listing.get(record.artifact_number)
    if artifact is None:
        raise ArtifactContentUnavailable(_CONTENT_INCOMPLETE)
    content = current_version_content(artifact, bot_id, digest)
    if content is not None:
        return content
    try:
        history = await io.async_read_artifact(issue_number, record.artifact_number)
    except GitHubIORefused as refused:
        if refused.reason is GitHubIOFailure.NOT_FOUND:
            raise ArtifactContentUnavailable(_CONTENT_INCOMPLETE) from None
        raise
    content = served_version_content(history.versions, bot_id, digest)
    if content is None:
        raise ArtifactContentUnavailable("content is unverifiable")
    return content
