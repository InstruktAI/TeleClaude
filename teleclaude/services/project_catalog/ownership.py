"""Which registered project holds a path, and whose project it is, read from the project catalog.

The catalog loads every registered project through the configuration loader, so ownership is
answered from the same validated declarations every other consumer reads. A registered root
whose declaration does not load as a project answers no ownership and still shadows any root
that contains it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.config.identity_schema import ProjectOwnerKind, project_owner_identity
from teleclaude.services.project_catalog.service import get_project_catalog_service


@dataclass(frozen=True)
class ProjectOwnership:
    """The registered project's canonical slug and declared owner."""

    project_slug: str
    company: str | None
    person: str | None

    def owner_identity(self) -> tuple[ProjectOwnerKind, str] | None:
        """Return the declared company-first owner identity for this project."""
        return project_owner_identity(self.company, self.person)


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

    def ownerships(self) -> tuple[ProjectOwnership, ...]:
        """Enumerate registered project ownership facts in registration order."""
        return tuple(ownership for _, ownership in self._ownership_by_root if ownership is not None)


def load_project_ownership_index() -> ProjectOwnershipIndex:
    """Snapshot every logical project's physical locations with declared ownership."""
    catalog = get_project_catalog_service()
    ownership_by_root: list[tuple[Path, ProjectOwnership | None]] = []
    for node in catalog.list_projects():
        ownership = ProjectOwnership(node.slug, node.config.company, node.config.person)
        roots = (node.root, node.development_checkout)
        ownership_by_root.extend((root.expanduser().resolve(), ownership) for root in roots if root is not None)
    return ProjectOwnershipIndex(tuple(ownership_by_root))
