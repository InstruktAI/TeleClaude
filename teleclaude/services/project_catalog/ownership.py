"""Which registered project holds a path, and whose project it is, read from the project catalog.

The catalog loads every registered project through the configuration loader, so ownership is
answered from the same validated declarations every other consumer reads. A registered root
whose declaration does not load as a project answers no ownership and still shadows any root
that contains it.

The index is kept per process and rebuilt only when the registry or a registered project's
declaration changes on disk, judged by modification time and size: every caller-role lookup asks
for it, and rebuilding it loads every registered declaration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.config.identity_schema import ProjectOwnerKind, project_owner_identity
from teleclaude.paths import ConfigFileName
from teleclaude.project_manifest import MANIFEST_PATH, load_roots
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


_FileSignature = tuple[int, int] | None


@dataclass(frozen=True)
class _CachedIndex:
    manifest: _FileSignature
    roots: tuple[Path, ...]
    declarations: tuple[_FileSignature, ...]
    index: ProjectOwnershipIndex


_cached_index: _CachedIndex | None = None


def _signature(path: Path) -> _FileSignature:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _declaration_signatures(roots: tuple[Path, ...]) -> tuple[_FileSignature, ...]:
    return tuple(_signature(root / ConfigFileName.OVERLAY) for root in roots)


def load_project_ownership_index() -> ProjectOwnershipIndex:
    """Snapshot every registered root with the ownership its catalog project declares, reused while unchanged."""
    global _cached_index
    manifest = _signature(MANIFEST_PATH)
    cached = _cached_index
    if (
        cached is not None
        and cached.manifest == manifest
        and cached.declarations == _declaration_signatures(cached.roots)
    ):
        return cached.index
    roots = tuple(load_roots())
    index = _build_project_ownership_index(roots)
    _cached_index = _CachedIndex(manifest, roots, _declaration_signatures(roots), index)
    return index


def _build_project_ownership_index(roots: tuple[Path, ...]) -> ProjectOwnershipIndex:
    catalog = get_project_catalog_service()
    ownership_by_root: list[tuple[Path, ProjectOwnership | None]] = []
    for root in roots:
        node = catalog.get_by_root(root)
        ownership = None if node is None else ProjectOwnership(node.slug, node.config.company, node.config.person)
        ownership_by_root.append((root.expanduser().resolve(), ownership))
    return ProjectOwnershipIndex(tuple(ownership_by_root))
