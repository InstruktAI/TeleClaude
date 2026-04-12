"""Facade service for the project catalog."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from teleclaude.paths import PROJECTS_MANIFEST_PATH
from teleclaude.project_manifest import load_roots
from teleclaude.services.project_catalog.loaders import load_project_node
from teleclaude.services.project_catalog.models import ProjectNode


class ProjectCatalogService:
    """Lazy, cached view of all registered projects.

    The service loads the root-only manifest once, then hydrates each entry
    into a :class:`ProjectNode`. Results are cached until :meth:`refresh` is
    called.
    """

    def __init__(self, *, manifest_path: Path | None = None) -> None:
        self._manifest_path = manifest_path or PROJECTS_MANIFEST_PATH
        self._projects: list[ProjectNode] | None = None

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
        self._projects = None

    # -- Queries ----------------------------------------------------------

    def list_projects(self) -> list[ProjectNode]:
        """Return all registered projects with loadable configs (cached)."""
        if self._projects is None:
            self._projects = self._load()
        return list(self._projects)

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

    def iter_projects_with_job(self, job_slug: str) -> Iterator[ProjectNode]:
        """Yield projects whose ``config.jobs`` dict contains ``job_slug``."""
        for node in self.list_projects():
            if job_slug in node.config.jobs:
                yield node


# -- Singleton factory -------------------------------------------------------

# Single-slot dict so the module-level cache has a stable, mutable container
# (avoids the ``global`` statement + constant-redefinition friction between
# pylint's naming rules and pyright's constant detection).
_INSTANCE_SLOT: dict[str, ProjectCatalogService] = {}


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
