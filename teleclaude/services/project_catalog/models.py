"""Data models for the project catalog service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.config.schema import ConfigKind, ProjectConfig


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


@dataclass(frozen=True)
class ProjectCatalogEntry:
    """One session-placement entry from the machine's project registry."""

    root: Path
    identity: str | None
    display_name: str
    description: str | None
    kind: ConfigKind
    owner: str | None = None
