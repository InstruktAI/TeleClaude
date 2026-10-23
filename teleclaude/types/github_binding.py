"""Infrastructure-owned GitHub session assignment, without credentials or workflow policy."""

from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from teleclaude.closed_model import ClosedModel
from teleclaude.core.roles import RoleName
from teleclaude.types.github_account import GitHubAccount, GitHubAccountKind

_BOT_REQUIRED = "A platform GitHub assignment requires a Bot account"
REPOSITORY_PATTERN = r"^[^/\s]+/[^/\s]+$"
_ABSOLUTE_PROJECT_REQUIRED = "A GitHub work target requires an absolute project path"


class GitHubWorkTarget(BaseModel):
    """Exact repository/item/work binding supplied by its trusted owner."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository_id: int = Field(gt=0, strict=True)
    repository: str = Field(pattern=REPOSITORY_PATTERN)
    issue_number: int = Field(gt=0, strict=True)
    work_item: str = Field(min_length=1)
    project_path: Path
    branch: str | None = None
    base: str | None = None

    @field_validator("project_path")
    @classmethod
    def require_absolute_project(cls, value: Path) -> Path:
        """Keep stored work identity independent of an invocation's current directory."""
        if not value.is_absolute():
            raise ValueError(_ABSOLUTE_PROJECT_REQUIRED)
        return value


class GitHubActorAssignment(ClosedModel):
    """Public App/account facts fixed for one bound session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    app_id: int = Field(gt=0, strict=True)
    actor: GitHubAccount

    @model_validator(mode="after")
    def require_bot(self) -> Self:
        """Separate platform actors from human and organization accounts."""
        if self.actor.type is not GitHubAccountKind.BOT:
            raise ValueError(_BOT_REQUIRED)
        return self


class AdmittedWorkflowParent(BaseModel):
    """Qualified parent fact issued by the child owner after its existing ChildPlan admission."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    computer: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


class GitHubSessionBinding(BaseModel):
    """Persisted assignment stamped with the actual session's catalog role."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(min_length=1)
    role: RoleName
    assignment: GitHubActorAssignment
    workflow_parent: AdmittedWorkflowParent | None = None
