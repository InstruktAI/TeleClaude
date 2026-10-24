"""Small project-scoped configuration value models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from teleclaude.closed_model import ClosedModel
from teleclaude.types.github_binding import REPOSITORY_PATTERN


class CapabilityConfig(ClosedModel):
    """Subscription state; an omitted block makes no capability claim."""

    enabled: bool = False


class TodoStoreBackend(StrEnum):
    LOCAL = "local"
    GITHUB = "github"


class GitHubRepositoryDeclaration(ClosedModel):
    """Committed repository facts used by GitHub workflow identity reads."""

    id: int = Field(gt=0, strict=True)
    full_name: str = Field(pattern=REPOSITORY_PATTERN)


class TodoStoreConfig(ClosedModel):
    """Project selection for the workflow store adapter."""

    store: TodoStoreBackend = TodoStoreBackend.LOCAL
    repository: GitHubRepositoryDeclaration | None = None
    app: int | None = Field(default=None, gt=0, strict=True)
