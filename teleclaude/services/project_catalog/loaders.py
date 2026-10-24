"""Load project metadata from a registered root directory."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from teleclaude.config.identity_schema import PersonEntry, project_owner_identity
from teleclaude.config.loader import load_company_config, load_person_config, load_project_config
from teleclaude.config.schema import CompanyConfig, ConfigKind
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.events.home_owner import EventHomeOwnerMarker
from teleclaude.paths import ConfigFileName
from teleclaude.project_manifest import RegisteredProjectEntry
from teleclaude.services.project_catalog.models import ProjectCatalogEntry, ProjectNode
from teleclaude.slug import derive_project_slug


def load_project_node(root: Path) -> ProjectNode | None:
    """Build a ``ProjectNode`` from a registered project root.

    Returns ``None`` when the project directory exists but does not contain a
    loadable ``teleclaude.yml`` or a derivable canonical slug.
    """
    resolved_root = root.expanduser().resolve()
    config_path = resolved_root / ConfigFileName.OVERLAY
    if not config_path.is_file():
        return None

    try:
        config = load_project_config(config_path)
    except (ValueError, OSError):
        return None

    slug = derive_project_slug(config.project_slug, config.project_name, resolved_root)
    if not slug:
        return None

    return ProjectNode(root=resolved_root, slug=slug, config=config)


def load_catalog_entry(
    entry: RegisteredProjectEntry,
    *,
    people_by_slug: Mapping[str, PersonEntry],
) -> ProjectCatalogEntry | None:
    """Hydrate one present registry folder into a session-placement entry."""
    if not entry.is_present:
        return None
    root = entry.path.expanduser().resolve()
    if entry.former_name is not None:
        return ProjectCatalogEntry(
            root=root,
            identity=None,
            display_name=entry.former_name,
            description=None,
            kind=entry.kind,
        )
    if entry.kind is ConfigKind.PROJECT:
        node = load_project_node(root)
        if node is None:
            return None
        return ProjectCatalogEntry(
            root=node.root,
            identity=node.slug,
            display_name=node.name,
            description=node.config.description,
            kind=ConfigKind.PROJECT,
            owner=_project_owner_token(node.config.company, node.config.person),
            development_checkout=entry.development_checkout,
        )

    config_path = root / ConfigFileName.OVERLAY
    try:
        if entry.kind is ConfigKind.PERSON:
            person_config = load_person_config(config_path, registered_slug=root.name)
            identity = person_config.slug
            person = people_by_slug.get(identity)
            return ProjectCatalogEntry(
                root=root,
                identity=identity,
                display_name=person_config.name or (person.name if person is not None else identity),
                description=person_config.description,
                kind=ConfigKind.PERSON,
            )
        if entry.kind is ConfigKind.COMPANY:
            company_config: CompanyConfig = load_company_config(config_path)
            identity = company_config.slug or root.name
            return ProjectCatalogEntry(
                root=root,
                identity=identity,
                display_name=company_config.name or identity,
                description=company_config.description,
                kind=ConfigKind.COMPANY,
            )
    except (OSError, ValueError):
        return None
    return None


def _project_owner_token(company: str | None, person: str | None) -> str:
    """Encode the declared owner or the explicit ownerless state for a project."""
    owner_identity = project_owner_identity(company, person)
    if owner_identity is None:
        return EventHomeOwnerMarker.OWNERLESS.value
    owner_kind, owner_slug = owner_identity
    return SubjectRef(ConfigSubjectKind(owner_kind.value), owner_slug).to_token()
