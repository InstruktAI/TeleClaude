"""The people and organization vocabulary configuration declares: people, company roles and project owners."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from teleclaude.closed_model import ClosedModel
from teleclaude.slug import validate_slug

ProficiencyLevel = Literal["novice", "intermediate", "advanced", "expert"]
_EMPTY_PERSON_EMAIL = "Person email must be non-empty"


class CompanyRole(StrEnum):
    """The shared person-role vocabulary applied at company scope."""

    ADMIN = "admin"
    MEMBER = "member"
    CONTRIBUTOR = "contributor"
    NEWCOMER = "newcomer"


class ProjectOwnerKind(StrEnum):
    """Owner categories declared by a registered project."""

    COMPANY = "company"
    PERSON = "person"


def project_owner_identity(company: str | None, person: str | None) -> tuple[ProjectOwnerKind, str] | None:
    """Resolve one project's declared owner identity, preferring company."""
    if company is not None:
        return ProjectOwnerKind.COMPANY, company
    if person is not None:
        return ProjectOwnerKind.PERSON, person
    return None


class CompanyMember(ClosedModel):
    """One person's role and explicit project assignments in a company roster."""

    role: CompanyRole
    projects: list[str] = Field(default_factory=list)

    @field_validator("projects")
    @classmethod
    def validate_projects(cls, value: list[str]) -> list[str]:
        """Validate and de-duplicate project assignments by slug."""
        projects: list[str] = []
        seen: set[str] = set()
        for project_slug in value:
            validate_slug(project_slug)
            if project_slug not in seen:
                seen.add(project_slug)
                projects.append(project_slug)
        return projects


class PersonEntry(ClosedModel):
    """Person identity and role configuration."""

    name: str
    email: str = Field(min_length=1)
    slug: str | None = None
    username: str | None = None
    role: Literal["admin", "member", "contributor", "newcomer"] | None = None
    preferences: str | None = None
    expertise: dict[str, ProficiencyLevel] | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Normalize and reject empty person email values."""
        normalized = value.strip()
        if not normalized:
            raise ValueError(_EMPTY_PERSON_EMAIL)
        return normalized

    @field_validator("slug")
    @classmethod
    def validate_person_slug(cls, value: str | None) -> str | None:
        """Normalize optional slugs and validate non-empty values."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        validate_slug(normalized)
        return normalized
