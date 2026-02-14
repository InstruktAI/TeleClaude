"""Shared config read/write/validate layer for interactive config UI.

Provides operations for user-facing configs:
- Global: ~/.teleclaude/teleclaude.yml
- Per-person: ~/.teleclaude/people/{name}/teleclaude.yml

Both the interactive menu and onboarding wizard consume this layer.
"""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML

from teleclaude.config.loader import load_global_config, load_person_config
from teleclaude.config.schema import (
    CredsConfig,
    GlobalConfig,
    PersonConfig,
    PersonEntry,
)

logger = get_logger(__name__)

_TELECLAUDE_DIR = Path("~/.teleclaude").expanduser()
_GLOBAL_CONFIG_PATH = _TELECLAUDE_DIR / "teleclaude.yml"
_PEOPLE_DIR = _TELECLAUDE_DIR / "people"


# --- Data classes ---


@dataclass
class ConfigArea:
    """A discoverable config section for the interactive menu."""

    name: str  # e.g. "adapters.telegram"
    label: str  # e.g. "Telegram"
    category: str  # "adapter" | "people" | "notifications" | "environment"
    configured: bool
    model_class: type[BaseModel]


@dataclass
class EnvVarInfo:
    """Metadata for a required environment variable."""

    name: str
    adapter: str
    description: str
    example: str


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


# --- Adapter env var registry ---

_ADAPTER_ENV_VARS: dict[str, list[EnvVarInfo]] = {
    "telegram": [
        EnvVarInfo(
            "TELEGRAM_BOT_TOKEN",
            "telegram",
            "Telegram Bot API token",
            "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        ),
    ],
}


# --- Reading ---


def get_global_config(path: Path | None = None) -> GlobalConfig:
    """Load global config from ~/.teleclaude/teleclaude.yml."""
    return load_global_config(path or _GLOBAL_CONFIG_PATH)


def get_person_config(name: str) -> PersonConfig:
    """Load per-person config from ~/.teleclaude/people/{name}/teleclaude.yml."""
    person_path = _PEOPLE_DIR / name / "teleclaude.yml"
    return load_person_config(person_path)


def list_people(config: GlobalConfig | None = None) -> list[PersonEntry]:
    """Return all people from global config."""
    if config is None:
        config = get_global_config()
    return list(config.people)


def list_person_dirs() -> list[str]:
    """Scan ~/.teleclaude/people/ for person directories."""
    if not _PEOPLE_DIR.exists():
        return []
    return sorted(d.name for d in _PEOPLE_DIR.iterdir() if d.is_dir() and (d / "teleclaude.yml").exists())


# --- Writing (atomic) ---


def _atomic_yaml_write(path: Path, data: dict[str, Any]) -> None:  # guard: loose-dict - YAML serialization boundary
    """Atomic YAML write using tmp file + os.replace.

    Preserves existing formatting when possible by using ruamel.yaml
    round-trip mode. Falls back to fresh write if file doesn't exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    tmp_path = path.with_suffix(".tmp")

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.default_flow_style = False

    with open(lock_path, "w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass


def _model_to_dict(model: BaseModel) -> dict[str, Any]:  # guard: loose-dict - Pydantic model_dump output
    """Convert a Pydantic model to a dict suitable for YAML serialization."""
    return model.model_dump(mode="python", exclude_defaults=True)


def save_global_config(config: GlobalConfig, path: Path | None = None) -> None:
    """Atomic write of global config."""
    target = path or _GLOBAL_CONFIG_PATH
    data = _model_to_dict(config)
    _atomic_yaml_write(target, data)
    logger.info("Saved global config to %s", target)


def save_person_config(name: str, config: PersonConfig) -> None:
    """Atomic write of per-person config. Creates directory if needed."""
    person_dir = _PEOPLE_DIR / name
    person_dir.mkdir(parents=True, exist_ok=True)
    target = person_dir / "teleclaude.yml"
    data = _model_to_dict(config)
    _atomic_yaml_write(target, data)
    logger.info("Saved person config for %s to %s", name, target)


def add_person(entry: PersonEntry) -> None:
    """Add person to global people list and create per-person directory."""
    config = get_global_config()

    if any(p.name == entry.name for p in config.people):
        raise ValueError(f"Person '{entry.name}' already exists")

    config.people.append(entry)
    save_global_config(config)

    person_config = PersonConfig()
    save_person_config(entry.name, person_config)
    logger.info("Added person '%s' with role '%s'", entry.name, entry.role)


def remove_person(name: str, delete_directory: bool = False) -> None:
    """Remove person from global list. Optionally remove their config directory."""
    config = get_global_config()
    original_count = len(config.people)
    config.people = [p for p in config.people if p.name != name]

    if len(config.people) == original_count:
        raise ValueError(f"Person '{name}' not found")

    save_global_config(config)

    if delete_directory:
        person_dir = _PEOPLE_DIR / name
        if person_dir.exists():
            import shutil

            shutil.rmtree(person_dir)
            logger.info("Removed person directory for '%s'", name)

    logger.info("Removed person '%s' from global config", name)


# --- Validation ---


def validate_all() -> list[ValidationResult]:
    """Run full-system validation: schema + cross-reference + env vars."""
    results: list[ValidationResult] = []

    # Validate global config
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

    # Validate each person config
    for person in config.people:
        person_path = _PEOPLE_DIR / person.name / "teleclaude.yml"
        if not person_path.exists():
            results.append(
                ValidationResult(
                    area=f"person:{person.name}",
                    passed=False,
                    errors=[f"Config file missing: {person_path}"],
                    suggestions=[f"Run: telec config to create config for {person.name}"],
                )
            )
            continue
        try:
            get_person_config(person.name)
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

    # Validate environment variables
    env_status = check_env_vars()
    missing = [s for s in env_status if not s.is_set]
    if missing:
        results.append(
            ValidationResult(
                area="environment",
                passed=False,
                errors=[f"Missing: {s.info.name} ({s.info.description})" for s in missing],
                suggestions=[f"Set {s.info.name}={s.info.example}" for s in missing],
            )
        )
    elif env_status:
        results.append(ValidationResult(area="environment", passed=True))

    return results


# --- Environment ---


def get_required_env_vars() -> dict[str, list[EnvVarInfo]]:
    """Aggregate required env vars for adapters that are actually in use.

    An adapter is "in use" if any person has credentials configured for it.
    """
    config = get_global_config()
    result: dict[str, list[EnvVarInfo]] = {}

    # Check which adapters have creds configured for any person
    for person in config.people:
        try:
            pc = get_person_config(person.name)
        except (ValueError, ValidationError):
            continue
        for adapter_name in _get_adapter_names():
            if adapter_name in result:
                continue
            if getattr(pc.creds, adapter_name, None) is not None:
                if adapter_name in _ADAPTER_ENV_VARS:
                    result[adapter_name] = _ADAPTER_ENV_VARS[adapter_name]

    return result


def check_env_vars() -> list[EnvVarStatus]:
    """Check which required env vars are set."""
    all_vars = get_required_env_vars()
    results: list[EnvVarStatus] = []
    for _adapter, vars_list in sorted(all_vars.items()):
        for info in vars_list:
            results.append(EnvVarStatus(info=info, is_set=bool(os.environ.get(info.name))))
    return results


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
        config = GlobalConfig()

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
            model_class = next((a for a in model_class.__args__ if a is not type(None)), model_class)

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
            if pc.notifications.telegram:
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
            model_class=type(None),
        )
    )

    return areas
