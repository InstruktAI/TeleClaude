"""Resolve the capability declaration for a TeleClaude project."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.config._environment import (
    expand_environment_references,
    find_environment_references,
    read_environment_file,
)
from teleclaude.config.context_root import load_declared_config_kind, load_raw_declaration
from teleclaude.config.loader import load_declared_project_config
from teleclaude.config.schema import CapabilityConfig, ConfigKind, ProjectConfig
from teleclaude.paths import ConfigFileName

logger = get_logger(__name__)


class CapabilityName(StrEnum):
    """Closed vocabulary for project capability declarations."""

    CODE = "code"
    DOCS = "docs"
    AGENTS = "agents"


class PermissionSurface(StrEnum):
    """Closed vocabulary for tier-material participation answers."""

    DOCUMENTATION = "documentation"


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


@dataclass(frozen=True)
class TierPermissions:
    """The three independent permission answers for one declared tier."""

    invocation_context: bool
    surfaces: frozenset[PermissionSurface]
    project_subscriptions: Capabilities

    def participates_in(self, surface: PermissionSurface) -> bool:
        """Return whether this tier's material participates in one surface."""
        return surface in self.surfaces


NOT_A_TARGET = Capabilities(is_target=False, code=False, docs=False, agents=False)
ALL_CAPABILITIES = Capabilities(is_target=True, code=True, docs=True, agents=True)
_DOCUMENTATION_SURFACE = frozenset({PermissionSurface.DOCUMENTATION})
_GLOBAL_TIER_PERMISSIONS = TierPermissions(
    invocation_context=True,
    surfaces=_DOCUMENTATION_SURFACE,
    project_subscriptions=NOT_A_TARGET,
)
_PERSON_TIER_PERMISSIONS = TierPermissions(
    invocation_context=True,
    surfaces=_DOCUMENTATION_SURFACE,
    project_subscriptions=NOT_A_TARGET,
)
_COMPANY_TIER_PERMISSIONS = TierPermissions(
    invocation_context=False,
    surfaces=_DOCUMENTATION_SURFACE,
    project_subscriptions=NOT_A_TARGET,
)
_NON_PROJECT_TIER_PERMISSIONS = {
    ConfigKind.GLOBAL: _GLOBAL_TIER_PERMISSIONS,
    ConfigKind.PERSON: _PERSON_TIER_PERMISSIONS,
    ConfigKind.COMPANY: _COMPANY_TIER_PERMISSIONS,
}


def capabilities_from_project_config(config: ProjectConfig) -> Capabilities:
    """Project capability subscriptions from an already-parsed overlay."""
    return _capabilities_from_sections(config.code, config.docs, config.agents)


def _capabilities_from_sections(
    code: CapabilityConfig,
    docs: CapabilityConfig,
    agents: CapabilityConfig,
) -> Capabilities:
    """Build the public capability result from validated subscription sections."""
    return Capabilities(
        is_target=True,
        code=code.enabled,
        docs=docs.enabled,
        agents=agents.enabled,
    )


def resolve_capabilities(project_root: Path) -> Capabilities:
    """Resolve capability sections without validating unrelated project-overlay sections."""
    marker = project_root / ConfigFileName.OVERLAY
    if not marker.is_file() or load_declared_config_kind(marker) is not ConfigKind.PROJECT:
        return NOT_A_TARGET
    return _resolve_project_capabilities(marker)


def resolve_tier_permissions(root: Path) -> TierPermissions:
    """Resolve tier permissions from the declaration's tier and capability sections only."""
    manifest_path = root / ConfigFileName.OVERLAY
    kind = load_declared_config_kind(manifest_path)
    if kind is not ConfigKind.PROJECT:
        return _NON_PROJECT_TIER_PERMISSIONS[kind]
    capabilities = _resolve_project_capabilities(manifest_path)
    surfaces = _DOCUMENTATION_SURFACE if capabilities.docs else frozenset()
    return TierPermissions(
        invocation_context=True,
        surfaces=surfaces,
        project_subscriptions=capabilities,
    )


def _resolve_project_capabilities(manifest_path: Path) -> Capabilities:
    """Validate only the tier's capability sections, independent of other overlay fields."""
    payload = load_raw_declaration(manifest_path, subject="capability")
    section_names = (CapabilityName.CODE, CapabilityName.DOCS, CapabilityName.AGENTS)
    sections = {name: payload.get(name, {}) for name in section_names}
    references = find_environment_references(sections)
    environment = read_environment_file(manifest_path.with_name(ConfigFileName.ENV)) if references else {}
    expanded = cast(
        dict[CapabilityName, object],
        expand_environment_references(sections, environment, config_path=manifest_path),
    )
    try:
        validated = {name: CapabilityConfig.model_validate(expanded[name]) for name in section_names}
    except ValidationError as exc:
        raise ValueError(f"Failed to validate config file {manifest_path}: {exc}") from exc
    return _capabilities_from_sections(
        validated[CapabilityName.CODE],
        validated[CapabilityName.DOCS],
        validated[CapabilityName.AGENTS],
    )


def resolve_project_capability_state(project_root: Path) -> ProjectCapabilityState:
    """Resolve capabilities and retain the fully parsed overlay for downstream consumers."""
    config = load_declared_project_config(project_root)
    if config is None:
        return ProjectCapabilityState(capabilities=NOT_A_TARGET, config=None)
    return ProjectCapabilityState(capabilities=capabilities_from_project_config(config), config=config)
