from pathlib import Path
from typing import Optional, Type, TypeVar

import yaml
from instrukt_ai_logging import get_logger
from pydantic import BaseModel

from teleclaude.config.schema import GlobalConfig, PersonConfig, ProjectConfig
from teleclaude.utils import expand_env_vars

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


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


def load_config(path: Path, model_class: Type[T]) -> T:
    """Load and validate configuration from a YAML file.

    Args:
        path: Path to the teleclaude.yml file.
        model_class: The Pydantic model class to use for validation.

    Returns:
        The validated configuration model.
    """
    if not path.exists():
        return model_class()

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Failed to read config file %s: %s", path, e)
        return model_class()

    expanded = expand_env_vars(raw)
    model = model_class.model_validate(expanded)
    _warn_unknown_keys(model, "root", path)
    return model


def load_project_config(path: Path) -> ProjectConfig:
    """Load project-level configuration."""
    return load_config(path, ProjectConfig)


def load_global_config(path: Optional[Path] = None) -> GlobalConfig:
    """Load global-level configuration."""
    if path is None:
        path = Path("~/.teleclaude/teleclaude.yml").expanduser()
    return load_config(path, GlobalConfig)


def load_person_config(path: Path) -> PersonConfig:
    """Load per-person configuration."""
    return load_config(path, PersonConfig)


def validate_config(path: Path, level: str) -> BaseModel:
    """Dispatcher to validate configuration at a specific level."""
    if level == "project":
        return load_project_config(path)
    elif level == "global":
        return load_global_config(path)
    elif level == "person":
        return load_person_config(path)
    else:
        raise ValueError(f"Invalid config level: {level}")
