"""Whether a configured person holds authority over a project, so an item may wait on them."""

from __future__ import annotations

from pathlib import Path

from teleclaude.config.identity_schema import CompanyRole, PersonEntry
from teleclaude.config.loader import company_memberships
from teleclaude.core.identity import get_identity_resolver
from teleclaude.services.project_catalog.ownership import load_project_ownership_index

ADMIN_PERSON_ROLE = "admin"


def configured_person(slug: str) -> PersonEntry | None:
    """The one configured person holding the slug."""
    return get_identity_resolver().person_by_slug(slug)


def has_project_authority(person: PersonEntry, project_root: str) -> bool:
    """Whether the person administers the platform or the company that owns the project."""
    if person.role == ADMIN_PERSON_ROLE:
        return True
    if person.slug is None:
        return False
    ownership = load_project_ownership_index().for_path(Path(project_root))
    if ownership is None or ownership.company is None:
        return False
    member = company_memberships(person.slug).get(ownership.company)
    return member is not None and member.role is CompanyRole.ADMIN
