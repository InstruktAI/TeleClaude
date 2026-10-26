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
    updated_at: datetime | None = None


@dataclass(frozen=True)
class GitHubIssue:
    """Issue facts required by store rebuild and reflection."""

    number: int
    issue_id: int
    node_id: str
    creator: str
    updated_at: datetime | None


@dataclass(frozen=True)
class GitHubPullRequest:
    """Pull request facts needed to identify an item's pull request and decide its next write."""

    number: int
    node_id: str
    author: str
    title: str
    body: str
    draft: bool
    open: bool
    head_branch: str


@dataclass(frozen=True)
class GitHubReview:
    """Submitted pull request review facts needed to recognize an already posted review."""

    review_id: int
    author: str
    commit_id: str
    state: str
    body: str
