"""Resolve the capability declaration for a TeleClaude project."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

import yaml
from instrukt_ai_logging import get_logger
from pydantic import ValidationError
from ruamel.yaml.error import YAMLError as RoundTripYAMLError

from teleclaude.config._environment import find_environment_references
from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.context_root import load_declared_config_kind, load_raw_declaration
from teleclaude.config.loader import expanded_overlay_input, load_declared_project_config
from teleclaude.config.migrations._chain import document_version
from teleclaude.config.project_models import CapabilityConfig
from teleclaude.config.schema import CURRENT_SCHEMA_VERSION, ConfigKind, ProjectConfig
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.paths import PROJECTS_MANIFEST_PATH, ConfigFileName

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


@dataclass(frozen=True)
class DeclarationDependency:
    """Pre-read file state used to validate a kept declaration answer."""

    path: Path
    exists: bool
    mtime_ns: int = 0
    size: int = 0
    inode: int = 0


@dataclass(frozen=True)
class DeclarationView:
    """A declaration answer and the files whose contents formed it."""

    kind: ConfigKind | None
    capabilities: Capabilities
    dependencies: tuple[DeclarationDependency, ...]
    environment_read: bool


class DeclarationUnreadable(ValueError):
    """A declaration could not produce a trustworthy runtime answer."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Could not resolve declaration {path}: {reason}")


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
    return _resolve_project_capabilities_with_environment(manifest_path)[0]


def _resolve_project_capabilities_with_environment(manifest_path: Path) -> tuple[Capabilities, Path | None]:
    """Resolve capability sections and report the sibling environment file read."""
    payload = load_raw_declaration(manifest_path, subject="capability")
    section_names = (CapabilityName.CODE, CapabilityName.DOCS, CapabilityName.AGENTS)
    sections = {name: payload.get(name, {}) for name in section_names}
    expanded_input = expanded_overlay_input(manifest_path, sections, ConfigKind.PROJECT)
    expanded = cast(dict[CapabilityName, object], expanded_input.value)
    try:
        validated = {name: CapabilityConfig.model_validate(expanded[name]) for name in section_names}
    except ValidationError as exc:
        raise ValueError(f"Failed to validate config file {manifest_path}: {exc}") from exc
    return (
        _capabilities_from_sections(
            validated[CapabilityName.CODE],
            validated[CapabilityName.DOCS],
            validated[CapabilityName.AGENTS],
        ),
        expanded_input.environment_path,
    )


def read_declaration_view(root: Path) -> DeclarationView:
    """Resolve a root's declared tier and project capabilities with their dependencies."""
    resolved_root = root.expanduser().resolve()
    marker = resolved_root / ConfigFileName.OVERLAY
    dependencies: list[DeclarationDependency] = [_dependency_stat(marker)]
    try:
        if not marker.is_file():
            return DeclarationView(None, NOT_A_TARGET, tuple(dependencies), environment_read=False)
        stored: object = round_trip_yaml().load(marker.read_text(encoding="utf-8")) or {}
        if not isinstance(stored, dict):
            raise DeclarationUnreadable(marker, "declaration must be a mapping")
        version = document_version(stored)
        if version < CURRENT_SCHEMA_VERSION:
            git_marker = resolved_root / ".git"
            if git_marker.is_file():
                dependencies.append(_dependency_stat(git_marker))
                owner = resolve_project_state_root(resolved_root).resolve()
                if owner != resolved_root:
                    dependencies.append(_dependency_stat(owner / ConfigFileName.OVERLAY))
            dependencies.append(_dependency_stat(PROJECTS_MANIFEST_PATH))
        kind = load_declared_config_kind(marker)
        if kind is not ConfigKind.PROJECT:
            return DeclarationView(kind, NOT_A_TARGET, tuple(dependencies), environment_read=False)
        raw = load_raw_declaration(marker, subject="capability")
        sections = {name.value: raw.get(name.value, {}) for name in CapabilityName}
        environment_path = marker.with_name(ConfigFileName.ENV) if find_environment_references(sections) else None
        if environment_path is not None:
            dependencies.append(_dependency_stat(environment_path))
        capabilities, environment_read = _resolve_project_capabilities_with_environment(marker)
        return DeclarationView(kind, capabilities, tuple(dependencies), environment_read is not None)
    except DeclarationUnreadable:
        raise
    except (OSError, ValueError, yaml.YAMLError, RoundTripYAMLError) as exc:
        raise DeclarationUnreadable(marker, _declaration_failure_reason(exc)) from exc


def _dependency_stat(path: Path) -> DeclarationDependency:
    """Capture a dependency's identity and content stat before resolving it."""
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return DeclarationDependency(path=path, exists=False)
    except OSError as exc:
        raise DeclarationUnreadable(path, _declaration_failure_reason(exc)) from exc
    return DeclarationDependency(
        path=path,
        exists=True,
        mtime_ns=stat_result.st_mtime_ns,
        size=stat_result.st_size,
        inode=stat_result.st_ino,
    )


def _declaration_failure_reason(error: BaseException) -> str:
    """Return a short, value-free name for the failed declaration input."""
    if isinstance(error, ValidationError):
        locations = error.errors()
        if locations and locations[0].get("loc"):
            return str(locations[0]["loc"][0])
    message = str(error)
    for name in CapabilityName:
        if name.value in message:
            return name.value
    return "declaration"


def resolve_project_capability_state(project_root: Path) -> ProjectCapabilityState:
    """Resolve capabilities and retain the fully parsed overlay for downstream consumers."""
    config = load_declared_project_config(project_root)
    if config is None:
        return ProjectCapabilityState(capabilities=NOT_A_TARGET, config=None)
    return ProjectCapabilityState(capabilities=capabilities_from_project_config(config), config=config)
