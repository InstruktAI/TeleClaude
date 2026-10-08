"""Shared config read/write/validate layer for interactive config UI.

Provides operations for user-facing configs:
- Global: ~/.teleclaude/teleclaude.yml
- Per-person: ~/.teleclaude/people/{name}/teleclaude.yml

Both the interactive menu and onboarding wizard consume this layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ValidationError

import teleclaude.config as _tc_config_module
from teleclaude.config._environment import write_environment_value
from teleclaude.config.declaration import write_yaml_document as _atomic_yaml_write
from teleclaude.config.loader import (
    find_person_config_path,
    list_company_config_paths,
    load_company_config,
    load_declared_project_config,
    load_global_config,
    load_person_config,
)
from teleclaude.config.loader import save_global_config as save_global_config
from teleclaude.config.loader import save_person_config as save_person_config
from teleclaude.config.machine_config_mutation import inspect_machine_config
from teleclaude.config.person_secrets import (
    PersonMcpSecretStatus,
    clear_person_mcp_secret,
    list_person_mcp_secret_statuses,
    replace_person_mcp_secret,
)
from teleclaude.config.schema import ConfigKind, CredsConfig, GlobalConfig, PersonConfig, PersonEntry
from teleclaude.config.surface import machine_config_surface
from teleclaude.config.validation import missing_enabled_service_fields, missing_required_fields
from teleclaude.mcp.registry import load_effective_registry
from teleclaude.paths import GLOBAL_CONFIG_PATH, PROJECT_ENV_PATH, REPO_ROOT, TELECLAUDE_HOME, ConfigFileName
from teleclaude.project_manifest import load_registered_roots

logger = get_logger(__name__)

_PEOPLE_DIR = TELECLAUDE_HOME / "people"
_PERSON_MCP_SECRET_MANAGEMENT_FAILED = "Personal MCP secret management failed"
_ADOPT_UNDECLARED_PROJECT = "Run from {path}: telec config project adopt"


class PersonMcpSecretManagementError(ValueError):
    """Stable operator-facing failure for personal MCP secret mutations."""


# --- Data classes ---


@dataclass
class ConfigArea:
    """A discoverable config section for the interactive menu."""

    name: str  # e.g. "adapters.telegram"
    label: str  # e.g. "Telegram"
    category: Literal["adapter", "people", "notifications", "environment"]  # e.g. "adapter"
    configured: bool
    model_class: type[BaseModel] | None


@dataclass
class EnvVarInfo:
    """Metadata for a required environment variable."""

    name: str
    adapter: str
    description: str
    example: str = ""


@dataclass
class EnvVarStatus:
    """Environment variable presence status."""

    info: EnvVarInfo
    is_set: bool


@dataclass
class ValidationResult:
    """Result of validating one config area."""

    area: str
    passed: bool
    errors: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


# --- Reading ---


def get_global_config(path: Path | None = None) -> GlobalConfig:
    """Load global config from ~/.teleclaude/teleclaude.yml."""
    return load_global_config(path or GLOBAL_CONFIG_PATH)


def get_person_config(slug: str) -> PersonConfig:
    """Load per-person config from ~/.teleclaude/people/{slug}/teleclaude.yml."""
    person_path = _PEOPLE_DIR / slug / ConfigFileName.OVERLAY
    return load_person_config(person_path, registered_slug=slug)


def list_people(config: GlobalConfig | None = None) -> list[PersonEntry]:
    """Return all people from global config."""
    if config is None:
        config = get_global_config()
    return list(config.people)


# --- Writing (atomic) ---
#
# The global/person config writers and their YAML helpers live in
# teleclaude.config.loader (the config domain). They are re-exported above so
# every existing importer of config_handlers is unaffected.


def save_raw_machine_config(
    raw_config: dict[str, Any],  # guard: loose-dict - on-disk YAML config tree
    path: Path | None = None,
) -> None:
    """Atomic write of the raw config.yml tree as-is (sparse; defaults not materialized)."""
    target = path or _tc_config_module.config_path
    _atomic_yaml_write(target, raw_config)
    logger.info("Saved machine config to %s", target)


# --- Validation ---


def validate_all() -> list[ValidationResult]:
    """Run full-system validation: schema + cross-reference + env vars."""
    results: list[ValidationResult] = []

    # Validate global config (people, subscriptions, env_allow_list)
    try:
        config = get_global_config()
        results.append(ValidationResult(area="global", passed=True))
    except (ValueError, ValidationError) as e:
        results.append(
            ValidationResult(
                area="global",
                passed=False,
                errors=[str(e)],
                suggestions=["Check ~/.teleclaude/teleclaude.yml for syntax errors"],
            )
        )
        return results

    # Validate the current-schema inspection projection without reloading the
    # runtime singleton, so an invalid committed document remains repairable.
    app_config: _tc_config_module.TeleclaudeConfig | None = None
    try:
        inspection = inspect_machine_config()
        app_config = _tc_config_module.build_config_from_raw(
            inspection.raw,
            _tc_config_module.config_path.parent,
            config_source=_tc_config_module.config_path,
        )
        results.append(ValidationResult(area=ConfigFileName.MACHINE, passed=True))
    except Exception as e:
        results.append(
            ValidationResult(
                area=ConfigFileName.MACHINE,
                passed=False,
                errors=[str(e)],
                suggestions=["Check ~/.teleclaude/config.yml for schema errors"],
            )
        )

    # Validate each person config. Resolve the on-disk path by slug (the canonical
    # person-overlay location, people/{slug}/teleclaude.yml), with the resolver's
    # legacy name/username fallback for folders not yet renamed.
    for person in config.people:
        person_path = find_person_config_path(person, _PEOPLE_DIR)
        if person_path is None:
            expected_path = _PEOPLE_DIR / (person.slug or person.name) / ConfigFileName.OVERLAY
            results.append(
                ValidationResult(
                    area=f"person:{person.name}",
                    passed=False,
                    errors=[f"Config file missing: {expected_path}"],
                    suggestions=[f"Run: telec config to create config for {person.name}"],
                )
            )
            continue
        try:
            load_person_config(person_path)
            results.append(ValidationResult(area=f"person:{person.name}", passed=True))
        except (ValueError, ValidationError) as e:
            results.append(
                ValidationResult(
                    area=f"person:{person.name}",
                    passed=False,
                    errors=[str(e)],
                    suggestions=[f"Check {person_path} for errors"],
                )
            )

    # Validate each folder-discovered company. Discovery is decoupled from loading
    # so one malformed overlay cannot hide its siblings from the report.
    for company_path in list_company_config_paths():
        company_area = f"company:{company_path.parent.name}"
        try:
            load_company_config(company_path)
            results.append(ValidationResult(area=company_area, passed=True))
        except (ValueError, ValidationError) as e:
            results.append(
                ValidationResult(
                    area=company_area,
                    passed=False,
                    errors=[str(e)],
                    suggestions=[f"Check {company_path} for errors"],
                )
            )

    # Validate each registered project root. An unavailable root is a stale
    # manifest entry — reported like a missing person overlay, never skipped.
    for root in load_registered_roots():
        project_area = f"project:{root.path.name}"
        if not root.is_present:
            results.append(
                ValidationResult(
                    area=project_area,
                    passed=False,
                    errors=[f"Registered project directory missing: {root.path}"],
                    suggestions=[f"Restore {root.path}, or remove it from the project manifest"],
                )
            )
            continue
        try:
            declared = load_declared_project_config(root.path)
        except (ValueError, ValidationError) as e:
            results.append(
                ValidationResult(
                    area=project_area,
                    passed=False,
                    errors=[str(e)],
                    suggestions=[f"Check {root.path / ConfigFileName.OVERLAY} for errors"],
                )
            )
            continue
        if declared is None:
            results.append(
                ValidationResult(
                    area=project_area,
                    passed=False,
                    errors=[f"No project configuration declared at {root.path}"],
                    suggestions=[_ADOPT_UNDECLARED_PROJECT.format(path=root.path)],
                )
            )
        else:
            results.append(ValidationResult(area=project_area, passed=True))

    missing_sections: dict[str, list[str]] = {}
    if app_config is not None:
        for section_name in ("telegram", "discord", "whatsapp", "email"):
            section = getattr(app_config, section_name)
            if section.enabled:
                missing = missing_required_fields(section_name, section)
                if missing:
                    missing_sections[section_name] = missing
        missing_sections.update(missing_enabled_service_fields(app_config))
    if missing_sections:
        results.append(
            ValidationResult(
                area="config credentials",
                passed=False,
                errors=[f"{section}: {', '.join(fields)}" for section, fields in missing_sections.items()],
                suggestions=["Set the missing values through config.yml or the configuration TUI."],
            )
        )
    else:
        results.append(ValidationResult(area="config credentials", passed=True))

    return results


# --- Environment ---


def get_adapter_env_vars(adapter_name: str) -> list[EnvVarInfo]:
    """Return schema-declared sensitive variables for one owning config section."""
    return [info for info in _schema_environment_vars() if info.adapter == adapter_name]


def get_all_env_vars() -> dict[str, list[EnvVarInfo]]:
    """Return sensitive schema descriptors grouped by their owning section."""
    groups: dict[str, list[EnvVarInfo]] = {}
    for info in _schema_environment_vars():
        groups.setdefault(info.adapter, []).append(info)
    return groups


def _schema_environment_vars() -> list[EnvVarInfo]:
    """Project the schema-owned sensitive leaves into environment inventory rows."""
    return [
        EnvVarInfo(
            name=descriptor.environment_name or "",
            adapter=descriptor.path[0],
            description=descriptor.dotted_path.replace(".", " "),
        )
        for descriptor in machine_config_surface()
        if descriptor.sensitive and descriptor.environment_name is not None
    ]


def get_required_env_vars() -> dict[str, list[EnvVarInfo]]:
    """Return all registered env vars. Alias for get_all_env_vars."""
    return get_all_env_vars()


def check_env_vars() -> list[EnvVarStatus]:
    """Check which required env vars are set."""
    all_vars = get_required_env_vars()
    results: list[EnvVarStatus] = []
    for vars_list in all_vars.values():
        for info in vars_list:
            results.append(EnvVarStatus(info=info, is_set=bool(os.environ.get(info.name))))  # fmt: skip  # guard: direct-env-read - allowed: environment-file management
    return results


def resolve_env_file_path(env_path: Path | None = None) -> Path:
    """Resolve the target env file path for config writes."""
    if env_path is not None:
        return env_path.expanduser()
    return PROJECT_ENV_PATH


def set_env_var(name: str, value: str, env_path: Path | None = None) -> Path:
    """Set or update an env var in the resolved env file and os.environ."""
    if not name or any(char in name for char in "\r\n="):
        raise ValueError("Invalid env var name")
    if any(char in value for char in "\r\n"):
        raise ValueError("Env var value cannot contain newlines")

    target = resolve_env_file_path(env_path)
    write_environment_value(target, name, value)

    os.environ[name] = value  # fmt: skip  # guard: direct-env-read - allowed: environment-file management
    logger.info("Updated env var %s in %s", name, target)
    return target


def get_person_mcp_secret_statuses(person_slug: str) -> list[PersonMcpSecretStatus]:
    """Return registry-derived, write-only MCP secret status for one person."""
    requirements = load_effective_registry(REPO_ROOT).person_secret_requirements()
    return list_person_mcp_secret_statuses(person_slug, requirements)


def replace_person_mcp_secret_value(person_slug: str, name: str, value: str) -> None:
    """Replace one personal MCP secret without returning its stored value."""
    try:
        replace_person_mcp_secret(person_slug, name, value)
    except (OSError, ValueError) as exc:
        raise PersonMcpSecretManagementError(_PERSON_MCP_SECRET_MANAGEMENT_FAILED) from exc


def clear_person_mcp_secret_value(person_slug: str, name: str) -> None:
    """Clear one personal MCP secret without touching unrelated stored values."""
    try:
        clear_person_mcp_secret(person_slug, name)
    except (OSError, ValueError) as exc:
        raise PersonMcpSecretManagementError(_PERSON_MCP_SECRET_MANAGEMENT_FAILED) from exc


# --- Schema discovery ---


def _get_adapter_names() -> list[str]:
    """Discover adapter names from CredsConfig fields."""
    names: list[str] = []
    for field_name, field_info in CredsConfig.model_fields.items():
        if field_info.annotation is not None:
            names.append(field_name)
    return sorted(names)


def discover_config_areas() -> list[ConfigArea]:
    """Inspect schema models to find available config areas.

    Returns areas for: adapters (from CredsConfig), people, notifications, environment.
    """
    areas: list[ConfigArea] = []

    try:
        config = get_global_config()
    except (ValueError, ValidationError):
        config = GlobalConfig(kind=ConfigKind.GLOBAL)

    # Adapter areas from CredsConfig fields
    for adapter_name in _get_adapter_names():
        configured = False
        for person in config.people:
            try:
                pc = get_person_config(person.name)
                if getattr(pc.creds, adapter_name, None) is not None:
                    configured = True
                    break
            except (ValueError, ValidationError):
                continue

        field_info = CredsConfig.model_fields[adapter_name]
        model_class = field_info.annotation
        # Unwrap Optional
        if hasattr(model_class, "__args__"):
            model_class = next(
                (a for a in model_class.__args__ if a is not type(None)),
                model_class,
            )

        areas.append(
            ConfigArea(
                name=f"adapters.{adapter_name}",
                label=adapter_name.capitalize(),
                category="adapter",
                configured=configured,
                model_class=model_class,
            )
        )

    # People area
    areas.append(
        ConfigArea(
            name="people",
            label="People",
            category="people",
            configured=len(config.people) > 0,
            model_class=PersonEntry,
        )
    )

    # Notifications area
    has_notifications = False
    for person in config.people:
        try:
            pc = get_person_config(person.name)
            if pc.subscriptions:
                has_notifications = True
                break
        except (ValueError, ValidationError):
            continue

    areas.append(
        ConfigArea(
            name="notifications",
            label="Notifications",
            category="notifications",
            configured=has_notifications,
            model_class=PersonConfig,
        )
    )

    # Environment area
    env_status = check_env_vars()
    all_set = all(s.is_set for s in env_status) if env_status else True
    areas.append(
        ConfigArea(
            name="environment",
            label="Environment",
            category="environment",
            configured=all_set,
            model_class=None,
        )
    )

    return areas
