"""Facade service for the project catalog."""

from __future__ import annotations

from pathlib import Path

from teleclaude.config.loader import load_global_config
from teleclaude.core.reconciliation.platform_repository import is_platform_repository
from teleclaude.paths import PROJECTS_MANIFEST_PATH
from teleclaude.project_manifest import load_roots
from teleclaude.project_manifest_runtime import load_registered_entries
from teleclaude.services.project_catalog.loaders import load_catalog_entry, load_project_node
from teleclaude.services.project_catalog.models import ProjectCatalogEntry, ProjectNode


class ProjectCatalogService:
    """Lazy, cached view of all registered projects.

    The service loads the root-only manifest once, then hydrates each entry
    into a :class:`ProjectNode`. Results are cached until :meth:`refresh` is
    called.
    """

    def __init__(self, *, manifest_path: Path | None = None) -> None:
        self._manifest_path = manifest_path or PROJECTS_MANIFEST_PATH
        self._projects: list[ProjectNode] | None = None
        self._entries: list[ProjectCatalogEntry] | None = None
        self._unresolved_roots: list[Path] | None = None
        self._generation = 0

    # -- Loading ----------------------------------------------------------

    def _load(self) -> list[ProjectNode]:
        roots = load_roots(self._manifest_path)
        nodes: list[ProjectNode] = []
        seen_roots: set[Path] = set()
        for root in roots:
            if root in seen_roots:
                continue
            seen_roots.add(root)
            node = load_project_node(root)
            if node is None:
                continue
            nodes.append(node)
        return nodes

    def refresh(self) -> None:
        """Invalidate the cached project list; next access reloads from disk."""
        self._generation += 1
        self._projects = None
        self._entries = None
        self._unresolved_roots = None

    @property
    def generation(self) -> int:
        """Advances on every refresh, so a view derived from the catalog knows when to derive it again."""
        return self._generation

    # -- Queries ----------------------------------------------------------

    def list_projects(self) -> list[ProjectNode]:
        """Return all registered projects with loadable configs (cached)."""
        if self._projects is None:
            self._projects = self._load()
        return list(self._projects)

    def list_entries(self, *, include_in_transit: bool = True) -> list[ProjectCatalogEntry]:
        """Return present registry entries in adoption order."""
        if not include_in_transit:
            return self._load_entries(include_in_transit=False)[0]
        return list(self._load_cached_entries()[0])

    def list_entries_with_unresolved_roots(self) -> tuple[list[ProjectCatalogEntry], list[Path]]:
        """Return entries and the present registry folders that yield no entry, from one observation."""
        entries, unresolved_roots = self._load_cached_entries()
        return list(entries), list(unresolved_roots)

    def _load_cached_entries(self) -> tuple[list[ProjectCatalogEntry], list[Path]]:
        """Return the cached transit-inclusive entries and the present folders that failed to hydrate."""
        if self._entries is None or self._unresolved_roots is None:
            self._entries, self._unresolved_roots = self._load_entries(include_in_transit=True)
        return self._entries, self._unresolved_roots

    def _load_entries(self, *, include_in_transit: bool) -> tuple[list[ProjectCatalogEntry], list[Path]]:
        """Hydrate registry entries with an explicit transit-document read policy."""
        people_by_slug = {person.slug: person for person in load_global_config().people if person.slug is not None}
        entries: list[ProjectCatalogEntry] = []
        unresolved_roots: list[Path] = []
        for registry_entry in load_registered_entries(
            self._manifest_path,
            include_in_transit=include_in_transit,
        ):
            entry = load_catalog_entry(registry_entry, people_by_slug=people_by_slug)
            if entry is not None:
                entries.append(entry)
            elif registry_entry.is_present:
                unresolved_roots.append(registry_entry.path)
        return entries, unresolved_roots

    def get_by_slug(self, slug: str) -> ProjectNode | None:
        """Return the project registered under ``slug``, or ``None``."""
        for node in self.list_projects():
            if node.slug == slug:
                return node
        return None

    def get_by_root(self, root: Path) -> ProjectNode | None:
        """Return the project whose root matches ``root``, or ``None``."""
        resolved = root.expanduser().resolve()
        for node in self.list_projects():
            if node.root == resolved:
                return node
        return None

    def get_platform_project(self) -> ProjectNode | None:
        """Return the registered project that is the platform's own repository, or ``None``.

        The running code sits in a release of the installation, never in a registered project, so the
        platform's own project is found through the registry.
        """
        for node in self.list_projects():
            if is_platform_repository(node.root):
                return node
        return None


# -- Singleton factory -------------------------------------------------------

# Single-slot dict so the module-level cache has a stable, mutable container
_INSTANCE_SLOT: dict[str, ProjectCatalogService] = {}


def registered_project_paths() -> list[str]:
    """This computer's registered project roots, in registry order, from a refreshed catalog."""
    catalog = get_project_catalog_service()
    catalog.refresh()
    return [str(entry.root) for entry in catalog.list_entries()]


def get_project_catalog_service() -> ProjectCatalogService:
    """Return the process-wide :class:`ProjectCatalogService` singleton."""
    service = _INSTANCE_SLOT.get("default")
    if service is None:
        service = ProjectCatalogService()
        _INSTANCE_SLOT["default"] = service
    return service


def reset_project_catalog_service() -> None:
    """Clear the cached singleton (primarily for tests)."""
    _INSTANCE_SLOT.clear()
