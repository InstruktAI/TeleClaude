"""Resolve the capability declaration for a TeleClaude project."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_project_config
from teleclaude.config.schema import ProjectConfig
from teleclaude.paths import ConfigFileName

logger = get_logger(__name__)


class CapabilityName(StrEnum):
    """Closed vocabulary for project capability declarations and markers."""

    CODE = "code"
    DOCS = "docs"
    AGENTS = "agents"


@dataclass(frozen=True)
class Capabilities:
    """Resolved capability subscriptions for one project root."""

    is_target: bool
    code: bool
    docs: bool
    agents: bool

    @property
    def any_enabled(self) -> bool:
        """Return whether any project capability is subscribed."""
        return self.code or self.docs or self.agents

    @property
    def commit_enabled(self) -> bool:
        """Return whether the sealed commit obligation is active."""
        return self.code or self.docs


@dataclass(frozen=True)
class ProjectCapabilityState:
    """A capability resolution plus its already-parsed project overlay."""

    capabilities: Capabilities
    config: ProjectConfig | None


NOT_A_TARGET = Capabilities(is_target=False, code=False, docs=False, agents=False)
ALL_CAPABILITIES = Capabilities(is_target=True, code=True, docs=True, agents=True)


def capabilities_from_project_config(config: ProjectConfig) -> Capabilities:
    """Project capability subscriptions from an already-parsed overlay."""
    return Capabilities(
        is_target=True,
        code=config.code.enabled,
        docs=config.docs.enabled,
        agents=config.agents.enabled,
    )


def resolve_capabilities(project_root: Path) -> Capabilities:
    """Read a project's declaration without treating an unadopted repo as subscribed."""
    return resolve_project_capability_state(project_root).capabilities


def resolve_project_capability_state(project_root: Path) -> ProjectCapabilityState:
    """Resolve capabilities and retain the parsed overlay for downstream consumers."""
    manifest_path = project_root / ConfigFileName.OVERLAY
    if not manifest_path.is_file():
        return ProjectCapabilityState(capabilities=NOT_A_TARGET, config=None)

    config = load_project_config(manifest_path)
    return ProjectCapabilityState(capabilities=capabilities_from_project_config(config), config=config)
