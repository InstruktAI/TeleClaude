"""Configuration file loading and validation."""

import os
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger
from pydantic import BaseModel

from teleclaude.config.schema import AppConfig, GlobalConfig, PersonConfig, ProjectConfig
from teleclaude.paths import GLOBAL_CONFIG_PATH
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
