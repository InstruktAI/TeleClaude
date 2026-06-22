"""Configuration file loading and validation."""

import fcntl
import os
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from instrukt_ai_logging import get_logger
from pydantic import BaseModel
from ruamel.yaml import YAML

from teleclaude.config.schema import (
    AppConfig,
    GlobalConfig,
    OutputVisibilitySettings,
    PersonConfig,
    PersonEntry,
    ProjectConfig,
)
from teleclaude.paths import GLOBAL_CONFIG_PATH, PEOPLE_DIR
from teleclaude.utils import expand_env_vars

logger = get_logger(__name__)


def _warn_unknown_keys(model: BaseModel, path: str, config_path: Path) -> None:
    """Recursively warn about unknown keys in a model and its nested models."""
    if hasattr(model, "model_extra") and model.model_extra:
        logger.warning("Unknown keys in %s at %s: %s", path, config_path, list(model.model_extra.keys()))

    # Check nested BaseModel instances
    for field_name, field_value in model.__dict__.items():
        if isinstance(field_value, BaseModel):
            _warn_unknown_keys(field_value, f"{path}.{field_name}", config_path)
        elif isinstance(field_value, dict):
            # Check dict values for nested BaseModels
            for key, value in field_value.items():
                if isinstance(value, BaseModel):
                    _warn_unknown_keys(value, f"{path}.{field_name}.{key}", config_path)
        elif isinstance(field_value, list):
            # Check list items for nested BaseModels
            for idx, item in enumerate(field_value):
                if isinstance(item, BaseModel):
                    _warn_unknown_keys(item, f"{path}.{field_name}[{idx}]", config_path)


def load_config[T: BaseModel](path: Path, model_class: type[T]) -> T:
    """Load YAML config from ``path`` and validate it with ``model_class``.

    Args:
        path: Path to a configuration YAML file.
        model_class: The Pydantic model class to use for validation.

    Returns:
        The validated configuration model.
    """
    if not path.exists():
        return model_class()

    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to read config file %s: %s", path, e)
        raise ValueError(f"Failed to read config file {path}: {e}") from e

    expanded = expand_env_vars(raw)
    model = model_class.model_validate(expanded)
    _warn_unknown_keys(model, "root", path)
    return model


def load_project_config(path: Path) -> ProjectConfig:
    """Load project-level configuration."""
    return load_config(path, ProjectConfig)


def save_project_config(path: Path, config: ProjectConfig) -> None:
    """Save project config to disk using atomic write (temp + rename)."""
    data = config.model_dump(mode="json", exclude_defaults=True)
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _represent_enum(representer: Any, data: Enum) -> Any:
    """Serialize any Enum (incl. StrEnum) as its underlying value for YAML."""
    return representer.represent_data(data.value)


def _atomic_yaml_write(path: Path, data: dict[str, Any]) -> None:  # guard: loose-dict - YAML serialization boundary
    """Atomic YAML write using tmp file + os.replace.

    Preserves existing formatting when possible by using ruamel.yaml
    round-trip mode. Falls back to fresh write if file doesn't exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    tmp_path = path.with_suffix(".tmp")

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.default_flow_style = False
    yaml_rt.representer.add_multi_representer(Enum, _represent_enum)

    with open(lock_path, "w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml_rt.dump(data, f)
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
    return model.model_dump(mode="json", exclude_defaults=True)


def _deep_merge(
    base: dict[str, Any],  # guard: loose-dict - recursive merge of arbitrary YAML
    overlay: dict[str, Any],  # guard: loose-dict - recursive merge of arbitrary YAML
) -> dict[str, Any]:  # guard: loose-dict - recursive merge of arbitrary YAML
    """Recursively merge overlay into base, returning a new dict."""
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def save_global_config(config: GlobalConfig, path: Path | None = None) -> None:
    """Atomic merge-write of global config.

    Reads the existing file first and merges model fields on top, preserving
    keys that are not part of the GlobalConfig schema (e.g. jobs, deployment).
    """
    target = path or GLOBAL_CONFIG_PATH
    existing: dict[str, Any] = {}  # guard: loose-dict - raw YAML config
    if target.exists():
        yaml_rt = YAML()
        with open(target, encoding="utf-8") as f:
            existing = yaml_rt.load(f) or {}
    overlay = _model_to_dict(config)
    merged = _deep_merge(existing, overlay)
    _atomic_yaml_write(target, merged)
    logger.info("Saved global config to %s (merged, preserved %d existing keys)", target, len(existing))


def save_person_config(slug: str, config: PersonConfig) -> None:
    """Atomic write of per-person config keyed by slug. Creates directory if needed."""
    person_dir = PEOPLE_DIR / slug
    person_dir.mkdir(parents=True, exist_ok=True)
    target = person_dir / "teleclaude.yml"
    data = _model_to_dict(config)
    _atomic_yaml_write(target, data)
    logger.info("Saved person config for %s to %s", slug, target)


def load_global_config(path: Path | None = None) -> GlobalConfig:
    """Load global-level configuration."""
    if path is None:
        path = GLOBAL_CONFIG_PATH
    return load_config(path, GlobalConfig)


def load_person_config(path: Path) -> PersonConfig:
    """Load per-person configuration."""
    return load_config(path, PersonConfig)


def normalize_person_config_key(value: str) -> str:
    """Normalize a person name or username for tolerant config directory matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _person_config_keys(person: PersonEntry) -> set[str]:
    keys = {normalize_person_config_key(person.name)}
    if person.username:
        keys.add(normalize_person_config_key(person.username))
    if person.slug:
        keys.add(normalize_person_config_key(person.slug))
    return keys


def find_person_config_path(person: PersonEntry, people_dir: Path = PEOPLE_DIR) -> Path | None:
    """Find a per-person config file by slug, falling back to legacy name/username keys.

    The slug-named folder is the canonical location; the legacy scan covers the
    transition window before a person's folder has been renamed to its slug.
    """
    if person.slug:
        slug_path = people_dir / person.slug / "teleclaude.yml"
        if slug_path.exists():
            return slug_path
    person_keys = _person_config_keys(person)
    for person_config_path in sorted(people_dir.glob("*/teleclaude.yml")):
        if normalize_person_config_key(person_config_path.parent.name) in person_keys:
            return person_config_path
    return None


def load_person_config_for_entry(person: PersonEntry, people_dir: Path = PEOPLE_DIR) -> PersonConfig | None:
    """Load the per-person config for a global person entry when present."""
    person_config_path = find_person_config_path(person, people_dir)
    if person_config_path is None:
        return None
    return load_person_config(person_config_path)


def _find_person_entry(
    *,
    people: list[PersonEntry],
    person_email: str | None = None,
    person_name: str | None = None,
    person_slug: str | None = None,
) -> PersonEntry | None:
    normalized_email = person_email.lower() if person_email else None
    normalized_name = normalize_person_config_key(person_name) if person_name else None
    for person in people:
        if person_slug and person.slug == person_slug:
            return person
        if normalized_email and person.email.lower() == normalized_email:
            return person
        if normalized_name and normalized_name in _person_config_keys(person):
            return person
    return None


def resolve_person_output_visibility_settings(
    *,
    person_email: str | None = None,
    person_name: str | None = None,
    person_slug: str | None = None,
    people: list[PersonEntry] | None = None,
    people_dir: Path = PEOPLE_DIR,
) -> OutputVisibilitySettings | None:
    """Resolve optional per-person output visibility settings for a recipient."""
    known_people = people if people is not None else load_global_config().people
    person = _find_person_entry(
        people=known_people,
        person_email=person_email,
        person_name=person_name,
        person_slug=person_slug,
    )
    if person is None:
        return None
    person_config = load_person_config_for_entry(person, people_dir)
    if person_config is None:
        return None
    return person_config.settings.output_visibility


def _is_person_workspace(workspace: Path) -> bool:
    """Check if workspace is a person directory under <base>/.teleclaude/people/."""
    return workspace.parent.name == "people" and workspace.parent.parent.name == ".teleclaude"


def load_app_config(workspace: Path) -> AppConfig:
    """Load composed app config for the given workspace.

    Determines workspace type (person vs. project) and loads the appropriate
    config layers. No fallback for unrecognized paths — returns global-only.
    """
    global_config = load_global_config()
    person_config: PersonConfig | None = None
    project_config: ProjectConfig | None = None

    if _is_person_workspace(workspace):
        teleclaude_yml = workspace / "teleclaude.yml"
        if teleclaude_yml.exists():
            person_config = load_person_config(teleclaude_yml)
    else:
        teleclaude_yml = workspace / "teleclaude.yml"
        if teleclaude_yml.exists():
            project_config = load_project_config(teleclaude_yml)

    return AppConfig(global_=global_config, project=project_config, person=person_config)


def validate_config(path: Path, level: str) -> BaseModel:
    """Dispatcher to validate configuration at a specific level."""
    if level == "project":
        return load_project_config(path)
    if level == "global":
        return load_global_config(path)
    if level == "person":
        return load_person_config(path)
    raise ValueError(f"Invalid config level: {level}")
