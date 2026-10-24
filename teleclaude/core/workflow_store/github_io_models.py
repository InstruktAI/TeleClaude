"""Stable value types returned by the GitHub workflow provider boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class GitHubRepositoryScope:
    """Repository-only scope used before a workflow item exists."""

    repository_id: int
    repository: str


@dataclass(frozen=True)
class GitHubComment:
    """Comment body and editor history needed to establish platform authorship."""

    node_id: str
    database_id: int
    body: str
    author: str | None
    editor: str | None
    edit_history: tuple[Mapping[str, object], ...]
    history_complete: bool


@dataclass(frozen=True)
class GitHubIssue:
    """Issue facts required by store rebuild and reflection."""

    number: int
    issue_id: int
    node_id: str
    creator: str
    updated_at: datetime | None
