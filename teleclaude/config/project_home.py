"""Resolve which person or company home contains a project, and whose project it must be.

A project inside a person's or a company's home belongs to that home's owner
(`local/projects/teleclaude/spec/feature/config/project-ownership`). This module
owns the one answer to "which home holds this path" and the one check that a
project's declared owner is that home's; configuration load and write call it so
no consumer re-derives it. Outside every home a declaration is free.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.config_roster import ProjectOwnerKind, load_people_roster
from teleclaude.paths import COMPANIES_ROOT, PEOPLE_DIR, ConfigFileName

_NO_OWNER = "no owner"
_HOME_OWNER_REFUSAL = (
    "A project inside the {kind} home '{slug}' must declare {kind} '{slug}' as its owner; "
    "its declaration names {declared}: {project_root}"
)
_DECLARED_OWNER = "{kind} '{slug}'"


@dataclass(frozen=True)
class HomeOwner:
    """The person or company whose home contains a path."""

    kind: ProjectOwnerKind
    slug: str
    home: Path

    def declaration(self) -> dict[str, str]:
        """Return the project-declaration field that names this owner."""
        return {self.kind.value: self.slug}


def _slug_under(path: Path, root: Path) -> str | None:
    """Return the first folder name under ``root`` that strictly contains ``path``."""
    try:
        parts = path.relative_to(root.resolve()).parts
    except ValueError:
        return None
    return parts[0] if len(parts) > 1 else None


def owning_home_owner(path: Path) -> HomeOwner | None:
    """Return the owner of the person or company home containing ``path``, if any.

    A person home is ``PEOPLE_DIR/<slug>`` for a slug in the people roster; a
    company home is ``COMPANIES_ROOT/<slug>`` for a company whose declaration
    exists. The home folder itself is not a project, so only a path strictly
    inside one matches.
    """
    resolved = path.expanduser().resolve()
    person_slug = _slug_under(resolved, PEOPLE_DIR)
    if person_slug is not None and person_slug in {entry.slug for entry in load_people_roster()}:
        return HomeOwner(ProjectOwnerKind.PERSON, person_slug, PEOPLE_DIR.resolve() / person_slug)
    company_slug = _slug_under(resolved, COMPANIES_ROOT)
    if company_slug is not None and (COMPANIES_ROOT / company_slug / ConfigFileName.OVERLAY).is_file():
        return HomeOwner(ProjectOwnerKind.COMPANY, company_slug, COMPANIES_ROOT.resolve() / company_slug)
    return None


def require_home_owner(project_root: Path, *, company: str | None, person: str | None) -> None:
    """Refuse a project inside a home whose declared owner is not that home's.

    Inside a home any other owner, or none, is refused. Outside every home any
    declaration is accepted.
    """
    home = owning_home_owner(project_root)
    if home is None:
        return
    declared_slug = company if home.kind is ProjectOwnerKind.COMPANY else person
    other_slug = person if home.kind is ProjectOwnerKind.COMPANY else company
    if declared_slug == home.slug and other_slug is None:
        return
    if company is not None:
        declared = _DECLARED_OWNER.format(kind=ProjectOwnerKind.COMPANY.value, slug=company)
    elif person is not None:
        declared = _DECLARED_OWNER.format(kind=ProjectOwnerKind.PERSON.value, slug=person)
    else:
        declared = _NO_OWNER
    raise ValueError(
        _HOME_OWNER_REFUSAL.format(
            kind=home.kind.value,
            slug=home.slug,
            declared=declared,
            project_root=project_root,
        )
    )


def adoptable_home_owner(project_root: Path, *, company: str | None, person: str | None) -> HomeOwner | None:
    """Return the home owner an adopted project inside a home must record, or ``None`` outside every home.

    A declaration that names no owner, or the home's own, is adoptable and takes
    the home's owner; any other declared owner is refused.
    """
    home = owning_home_owner(project_root)
    if home is None:
        return None
    if company is None and person is None:
        return home
    require_home_owner(project_root, company=company, person=person)
    return home
