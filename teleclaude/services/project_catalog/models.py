"""Data models for the project catalog service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.config.schema import ProjectConfig


@dataclass(frozen=True)
class ProjectNode:
    """A single registered project as seen by the catalog."""

    root: Path
    slug: str
    config: ProjectConfig

    @property
    def name(self) -> str:
        """Human-readable project name; falls back to slug when unset."""
        return self.config.project_name or self.slug

    @property
    def docs_index_path(self) -> Path:
        """Canonical docs index location for this project."""
        return self.root / "docs" / "project" / "index.yaml"
