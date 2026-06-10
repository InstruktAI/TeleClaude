"""Configuration file loading and validation."""

import os
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger
from pydantic import BaseModel

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
    return keys


def find_person_config_path(person: PersonEntry, people_dir: Path = PEOPLE_DIR) -> Path | None:
    """Find a per-person config file by scanning known person directories."""
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
) -> PersonEntry | None:
    normalized_email = person_email.lower() if person_email else None
    normalized_name = normalize_person_config_key(person_name) if person_name else None
    for person in people:
        if normalized_email and person.email.lower() == normalized_email:
            return person
        if normalized_name and normalized_name in _person_config_keys(person):
            return person
    return None


def resolve_person_output_visibility_settings(
    *,
    person_email: str | None = None,
    person_name: str | None = None,
    people: list[PersonEntry] | None = None,
    people_dir: Path = PEOPLE_DIR,
) -> OutputVisibilitySettings | None:
    """Resolve optional per-person output visibility settings for a recipient."""
    known_people = people if people is not None else load_global_config().people
    person = _find_person_entry(people=known_people, person_email=person_email, person_name=person_name)
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
