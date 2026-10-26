"""Small project-scoped configuration value models."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import Field, field_validator

from teleclaude.closed_model import ClosedModel
from teleclaude.config._coerce import INT_STRICT, OPT_INT_STRICT
from teleclaude.types.github_binding import REPOSITORY_PATTERN


class CapabilityConfig(ClosedModel):
    """Subscription state; an omitted block makes no capability claim."""

    enabled: bool = False


class TodoStoreBackend(StrEnum):
    LOCAL = "local"
    GITHUB = "github"


class GitHubRepositoryDeclaration(ClosedModel):
    """Committed repository facts used by GitHub workflow identity reads."""

    id: INT_STRICT = Field(gt=0)
    full_name: str = Field(pattern=REPOSITORY_PATTERN)


WORKFLOW_PATH_PREFIX: Final = ".github/workflows/"
_WORKFLOW_PATH_ERROR = "A required check names a workflow file by its repository path, beginning {prefix}"
_BRANCH_PREFIX_ERROR = "A dependency-update branch prefix must not be blank"


class CiConfig(ClosedModel):
    """A project's CI declaration: which workflows are its required checks and which branches are dependency updates."""

    required_checks: list[str] = []
    dependency_update_branches: list[str] = []

    @field_validator("required_checks")
    @classmethod
    def require_workflow_paths(cls, paths: list[str]) -> list[str]:
        """Refuse a workflow name or a bare file name: workflow identity is its repository path."""
        for path in paths:
            if not path.startswith(WORKFLOW_PATH_PREFIX) or path == WORKFLOW_PATH_PREFIX:
                raise ValueError(_WORKFLOW_PATH_ERROR.format(prefix=WORKFLOW_PATH_PREFIX))
        return paths

    @field_validator("dependency_update_branches")
    @classmethod
    def require_nonblank_prefixes(cls, prefixes: list[str]) -> list[str]:
        """Refuse an empty prefix: it would classify every branch as a dependency update."""
        if any(not prefix.strip() for prefix in prefixes):
            raise ValueError(_BRANCH_PREFIX_ERROR)
        return prefixes


class TodoStoreConfig(ClosedModel):
    """Project selection for the workflow store adapter."""

    store: TodoStoreBackend = TodoStoreBackend.LOCAL
    repository: GitHubRepositoryDeclaration | None = None
    app: OPT_INT_STRICT = Field(default=None, gt=0)
