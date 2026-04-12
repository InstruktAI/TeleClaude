"""Project catalog service package.

Public exports:
    ProjectNode                  — single registered project (root + slug + config)
    ProjectCatalogService        — lazy, cached view of all registered projects
    get_project_catalog_service  — process-wide singleton factory
    reset_project_catalog_service — clear singleton (test-only helper)
"""

from teleclaude.services.project_catalog.models import ProjectNode
from teleclaude.services.project_catalog.service import (
    ProjectCatalogService,
    get_project_catalog_service,
    reset_project_catalog_service,
)

__all__ = [
    "ProjectCatalogService",
    "ProjectNode",
    "get_project_catalog_service",
    "reset_project_catalog_service",
]
