"""Resolve the capability declaration for a TeleClaude project."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.context_root import load_declared_config_kind
from teleclaude.config.loader import load_declared_project_config
from teleclaude.config.schema import ConfigKind, ProjectConfig
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
    return Capabilities(
        is_target=True,
        code=config.code.enabled,
        docs=config.docs.enabled,
        agents=config.agents.enabled,
    )


def resolve_capabilities(project_root: Path) -> Capabilities:
    """Read a project's declaration without treating an unadopted repo as subscribed."""
    return resolve_project_capability_state(project_root).capabilities


def resolve_tier_permissions(root: Path) -> TierPermissions:
    """Resolve the three permission axes from a root's declared tier."""
    manifest_path = root / ConfigFileName.OVERLAY
    kind = load_declared_config_kind(manifest_path)
    if kind is not ConfigKind.PROJECT:
        return _NON_PROJECT_TIER_PERMISSIONS[kind]
    capability_state = resolve_project_capability_state(root)
    surfaces = _DOCUMENTATION_SURFACE if capability_state.capabilities.docs else frozenset()
    return TierPermissions(
        invocation_context=True,
        surfaces=surfaces,
        project_subscriptions=capability_state.capabilities,
    )


def resolve_project_capability_state(project_root: Path) -> ProjectCapabilityState:
    """Resolve capabilities and retain the parsed overlay for downstream consumers."""
    config = load_declared_project_config(project_root)
    if config is None:
        return ProjectCapabilityState(capabilities=NOT_A_TARGET, config=None)
    return ProjectCapabilityState(capabilities=capabilities_from_project_config(config), config=config)
