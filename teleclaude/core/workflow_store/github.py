"""GitHub workflow-store adapter and native target projection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.core.workflow_store.types import StoreAddress, WorkItemId
from teleclaude.types.github_binding import GitHubWorkTarget

_INVALID_GITHUB_WORK_ITEM_ID = "GitHub work item ID must be a canonical positive ASCII decimal issue number"
_ZERO_PREFIX = "0"


@dataclass(frozen=True)
class GitHubRepositoryIdentity:
    """Repository identity selected for a project's GitHub workflow store."""

    project_path: Path
    repository_id: int
    repository: str


class InvalidGitHubWorkItemId(ValueError):
    """A workflow item ID does not encode a canonical GitHub issue number."""


def project_github_work_target(
    repository_identity: GitHubRepositoryIdentity,
    work_item_id: WorkItemId,
    store_address: StoreAddress,
) -> GitHubWorkTarget:
    """Project a selected repository and item identity to its native GitHub target.

    The opaque store address is intentionally projected away. Its correspondence
    with the work item ID is guaranteed by the selected adapter's identity
    invariant; this pure projection performs no lookup or provider call.
    """
    work_item = str(work_item_id)
    if not work_item.isascii() or not work_item.isdecimal() or work_item.startswith(_ZERO_PREFIX):
        raise InvalidGitHubWorkItemId(_INVALID_GITHUB_WORK_ITEM_ID)

    try:
        issue_number = int(work_item)
    except ValueError as exc:
        raise InvalidGitHubWorkItemId(_INVALID_GITHUB_WORK_ITEM_ID) from exc

    return GitHubWorkTarget(
        repository_id=repository_identity.repository_id,
        repository=repository_identity.repository,
        issue_number=issue_number,
        work_item=work_item,
        project_path=repository_identity.project_path,
    )
