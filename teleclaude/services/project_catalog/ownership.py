"""Which registered project holds a path, and whose project it is, read from the project catalog.

The catalog loads every registered project through the configuration loader, so ownership is
answered from the same validated declarations every other consumer reads. A registered root
whose declaration does not load as a project answers no ownership and still shadows any root
that contains it.

The index is kept per process and rebuilt when the catalog it is read from is refreshed: every
caller-role lookup asks for it, and building it reads the registry and every registered root. A
process that holds the index for long refreshes the catalog when the registry or a declaration
changes, as the daemon's watchers do.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.config.identity_schema import ProjectOwnerKind, project_owner_identity
from teleclaude.project_manifest import load_roots
from teleclaude.services.project_catalog.service import ProjectCatalogService, get_project_catalog_service


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


@dataclass(frozen=True)
class _CachedIndex:
    catalog: ProjectCatalogService
    generation: int
    index: ProjectOwnershipIndex


_cached_index: _CachedIndex | None = None


def load_project_ownership_index() -> ProjectOwnershipIndex:
    """Snapshot every registered root with the ownership its catalog project declares, reused until a refresh."""
    global _cached_index
    catalog = get_project_catalog_service()
    generation = catalog.generation
    cached = _cached_index
    if cached is not None and cached.catalog is catalog and cached.generation == generation:
        return cached.index
    index = _build_project_ownership_index(catalog)
    _cached_index = _CachedIndex(catalog, generation, index)
    return index


def _build_project_ownership_index(catalog: ProjectCatalogService) -> ProjectOwnershipIndex:
    ownership_by_root: list[tuple[Path, ProjectOwnership | None]] = []
    for root in load_roots():
        node = catalog.get_by_root(root)
        ownership = None if node is None else ProjectOwnership(node.slug, node.config.company, node.config.person)
        ownership_by_root.append((root.expanduser().resolve(), ownership))
    return ProjectOwnershipIndex(tuple(ownership_by_root))
