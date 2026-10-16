"""Data models for the project catalog service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.config.checkout_association import CheckoutPurpose
from teleclaude.config.schema import ConfigKind, ProjectConfig


@dataclass(frozen=True)
class ProjectLocation:
    """One selectable physical location for a logical project."""

    path: Path
    purpose: CheckoutPurpose


@dataclass(frozen=True)
class ProjectNode:
    """A single registered project as seen by the catalog."""

    root: Path
    slug: str
    config: ProjectConfig
    development_checkout: Path | None = None

    @property
    def name(self) -> str:
        """Human-readable project name; falls back to slug when unset."""
        return self.config.project_name or self.slug

    @property
    def locations(self) -> tuple[ProjectLocation, ...]:
        """Return the registered physical locations in primary/development order."""
        if self.development_checkout is None:
            return ()
        return (
            ProjectLocation(self.root, CheckoutPurpose.INSTALLED),
            ProjectLocation(self.development_checkout, CheckoutPurpose.DEVELOPMENT),
        )


@dataclass(frozen=True)
class ProjectCatalogEntry:
    """One session-placement entry from the machine's project registry."""

    root: Path
    identity: str | None
    display_name: str
    description: str | None
    kind: ConfigKind
    owner: str | None = None
    development_checkout: Path | None = None
