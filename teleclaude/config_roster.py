"""Lightweight access to the people roster used for caller identity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, field_validator

from teleclaude.closed_model import ClosedModel
from teleclaude.paths import COMPANIES_ROOT, GLOBAL_CONFIG_PATH, ConfigFileName
from teleclaude.project_manifest import load_roots
from teleclaude.slug import derive_project_slug, validate_slug

ProficiencyLevel = Literal["novice", "intermediate", "advanced", "expert"]
_UTF8 = "utf-8"
_MEMBERS_KEY = "members"
_PROJECT_SLUG_KEY = "project_slug"
_PROJECT_NAME_KEY = "project_name"
_COMPANY_KEY = "company"


class CompanyRole(StrEnum):
    """The shared person-role vocabulary applied at company scope."""

    ADMIN = "admin"
    MEMBER = "member"
    CONTRIBUTOR = "contributor"
    NEWCOMER = "newcomer"


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


@dataclass(frozen=True)
class ProjectOwnership:
    """The registered project's canonical slug and declared company owner."""

    project_slug: str
    company: str | None


@dataclass(frozen=True)
class ProjectOwnershipIndex:
    """Snapshot of registered roots and their declared ownership facts."""

    _ownership_by_root: tuple[tuple[Path, ProjectOwnership | None], ...]

    def for_path(self, path: Path) -> ProjectOwnership | None:
        """Resolve the deepest registered root containing a path."""
        resolved_path = path.expanduser().resolve()
        candidates = [
            (root, ownership)
            for root, ownership in self._ownership_by_root
            if resolved_path == root or root in resolved_path.parents
        ]
        if not candidates:
            return None
        _, ownership = max(candidates, key=lambda item: len(item[0].parts))
        return ownership

    def for_slug(self, project_slug: str) -> ProjectOwnership | None:
        """Resolve the first registered project with this canonical slug."""
        for _, ownership in self._ownership_by_root:
            if ownership is not None and ownership.project_slug == project_slug:
                return ownership
        return None


def load_project_ownership_index(
    projects_manifest_path: Path | None = None,
) -> ProjectOwnershipIndex:
    """Load registered roots and their ownership declarations as one snapshot."""
    roots = load_roots() if projects_manifest_path is None else load_roots(projects_manifest_path)
    return ProjectOwnershipIndex(tuple((root, _project_ownership_for_root(root)) for root in roots))


def load_person_memberships(
    person_slug: str,
    companies_root: Path | None = None,
) -> dict[str, CompanyMember]:
    """Read the person's valid membership entries, ignoring unreadable companies."""
    validate_slug(person_slug)
    root = COMPANIES_ROOT if companies_root is None else companies_root
    memberships: dict[str, CompanyMember] = {}
    if not root.exists():
        return memberships

    for config_path in sorted(root.glob(f"*/{ConfigFileName.OVERLAY}")):
        try:
            raw: object = yaml.safe_load(config_path.read_text(encoding=_UTF8))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        if not isinstance(raw, dict):
            continue
        members = raw.get(_MEMBERS_KEY)
        if not isinstance(members, dict) or person_slug not in members:
            continue
        try:
            memberships[config_path.parent.name] = CompanyMember.model_validate(members[person_slug])
        except ValidationError:
            continue
    return memberships


def _project_ownership_for_root(root: Path) -> ProjectOwnership | None:
    config_path = root / ConfigFileName.OVERLAY
    if not config_path.is_file():
        return None
    try:
        raw: object = yaml.safe_load(config_path.read_text(encoding=_UTF8))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict):
        return None
    project_slug = derive_project_slug(raw.get(_PROJECT_SLUG_KEY), raw.get(_PROJECT_NAME_KEY), root)
    if project_slug is None:
        return None
    company = raw.get(_COMPANY_KEY)
    return ProjectOwnership(project_slug, company if isinstance(company, str) and company.strip() else None)


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
            raise ValueError("Person email must be non-empty")
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


def load_people_roster(path: Path | None = None) -> list[PersonEntry]:
    """Read and validate only registered people, tolerating unrelated bad config."""
    source = GLOBAL_CONFIG_PATH if path is None else path
    try:
        loaded = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return []
    if not isinstance(loaded, dict):
        return []
    people = loaded.get("people")
    if not isinstance(people, list):
        return []
    result: list[PersonEntry] = []
    for item in people:
        try:
            result.append(PersonEntry.model_validate(item))
        except ValidationError:
            continue
    return result
