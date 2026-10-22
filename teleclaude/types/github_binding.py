"""Infrastructure-owned GitHub session assignment, without credentials or workflow policy."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from teleclaude.closed_model import ClosedModel
from teleclaude.core.roles import RoleName
from teleclaude.types.github_account import GitHubAccount, GitHubAccountKind

_BOT_REQUIRED = "A platform GitHub assignment requires a Bot account"
_REPOSITORY_PATTERN = r"^[^/\s]+/[^/\s]+$"
_ABSOLUTE_PROJECT_REQUIRED = "A GitHub work target requires an absolute project path"
GITHUB_POSTING_RELATED_FIELD = "github_posting"
_ORIGIN_READ_INVALID = "An origin binding read contains facts or a refusal, never both"


class GitHubWorkTarget(BaseModel):
    """Exact repository/item/work binding supplied by its trusted owner."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository_id: int = Field(gt=0, strict=True)
    repository: str = Field(pattern=_REPOSITORY_PATTERN)
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


class GitHubSessionBinding(BaseModel):
    """Persisted assignment stamped with the actual session's catalog role."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(min_length=1)
    role: RoleName
    assignment: GitHubActorAssignment


class GitHubOriginBindingRefusal(StrEnum):
    """Safe owner-read failures; none grants a fallback actor or posting authority."""

    SESSION_UNAVAILABLE = "session_unavailable"
    PRINCIPAL_UNRESOLVED = "principal_unresolved"
    PRINCIPAL_MISMATCH = "principal_mismatch"
    BINDING_UNAVAILABLE = "binding_unavailable"
    BINDING_MISMATCH = "binding_mismatch"
    RECORD_CHANGED = "record_changed"


class GitHubOriginBindingFacts(BaseModel):
    """Public facts freshly joined by the session's own computer, with origin-local paths."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    computer: str = Field(min_length=1)
    principal: str = Field(min_length=1)
    binding: GitHubSessionBinding
    target: GitHubWorkTarget


class GitHubOriginBindingRead(BaseModel):
    """Related reached-read result, separate from a diagnostic session record."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    value: GitHubOriginBindingFacts | None = None
    refusal: GitHubOriginBindingRefusal | None = None

    @model_validator(mode="after")
    def require_result(self) -> Self:
        """A refusal never retains usable posting facts."""
        if (self.value is None) == (self.refusal is None):
            raise ValueError(_ORIGIN_READ_INVALID)
        return self
