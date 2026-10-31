"""Stable value types returned by the GitHub workflow provider boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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
class GitHubActor:
    """An account as GitHub names it: the numeric id is the identity, the login only a label."""

    actor_id: int
    login: str


class GitHubArtifactType(StrEnum):
    """The kinds of issue artifact; GitHub fixes a type at creation."""

    GENERIC = "generic"
    PLAN = "plan"
    EMBEDDED_HTML = "embedded_html"
    LINK = "link"


@dataclass(frozen=True)
class GitHubArtifact:
    """One issue artifact: its address on the issue, its current body and the accounts that touched it."""

    number: int
    artifact_type: GitHubArtifactType
    name: str
    body: str
    creator: GitHubActor | None
    updated_by: GitHubActor | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class GitHubArtifactVersion:
    """One saved version of an issue artifact and the account that saved it."""

    version: int
    name: str
    body: str
    created_at: datetime | None
    actor: GitHubActor | None


@dataclass(frozen=True)
class GitHubArtifactHistory:
    """An issue artifact with the versions GitHub still serves, newest first."""

    artifact: GitHubArtifact
    versions: tuple[GitHubArtifactVersion, ...]


@dataclass(frozen=True)
class GitHubIssue:
    """Issue facts required by store rebuild and reflection."""

    number: int
    issue_id: int
    node_id: str
    creator: str
    updated_at: datetime | None
    body: str = ""
    closed: bool = False


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


@dataclass(frozen=True)
class GitHubBoardOwner:
    """The repository and the account that owns it, as the board's GraphQL calls address them."""

    repository_id: str
    owner_id: str
    is_organization: bool


@dataclass(frozen=True)
class GitHubBoardProject:
    """An organization project: its node ID and the number the organization shows."""

    project_id: str
    number: int
    title: str


@dataclass(frozen=True)
class GitHubBoardSelectField:
    """A single-select field of a project with its options as (option ID, name) in field order."""

    field_id: str
    name: str
    options: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class GitHubBoardView:
    """A saved view of a project."""

    view_id: str
    name: str
    layout: str
    filter: str


@dataclass(frozen=True)
class GitHubBoardState:
    """Everything setup compares against its target: README, fields, views, built-in workflows and links."""

    project: GitHubBoardProject
    readme: str
    closed: bool
    fields: tuple[GitHubBoardSelectField, ...]
    views: tuple[GitHubBoardView, ...]
    workflow_ids: tuple[str, ...]
    linked_repository_ids: frozenset[str]
