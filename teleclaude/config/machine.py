"""This computer's machine configuration: loaded on first attribute access, reloaded in place.

Available as ``from teleclaude.config.machine import config``.
"""

import os
from pathlib import Path
from typing import Any, cast

import yaml

from teleclaude.config._bootstrap import resolve_runtime_config_path
from teleclaude.config._machine_build import (
    CONFIG_LOAD_ID,
    EXPERIMENTS_FILE_NAME,
    WORKING_DIR,
    build_config_from_raw,
)
from teleclaude.config._models import (
    TeleclaudeConfig,
)
from teleclaude.config.errors import ConfigLoadError
from teleclaude.config.migrations.read import upcast_for_read
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.paths import ENV_PATH

_WORKING_DIR_VARIABLE = "WORKING_DIR"
_READ_ERROR = "Failed to read config file {path}: {error}"

# Sections whose consumers re-read config at call-time, so a reload applies live via
# in-place singleton mutation (tts additionally needs TTSManager.reload()). This is a
# safe allowlist: any changed section NOT listed requires a daemon restart, because its
# consumers captured the value at startup and would otherwise silently ignore the change.
HOT_RELOADABLE_SECTIONS = frozenset({"chiptunes", "summarizer", "stt", "tts"})


def restart_required_sections(changed: list[str]) -> list[str]:
    """Return the changed sections that need a daemon restart (everything not hot-reloadable)."""
    return [section for section in changed if section not in HOT_RELOADABLE_SECTIONS]


def _load_config_from_disk(path: Path) -> TeleclaudeConfig:
    """Read config.yml (and optional adjacent experiments.yml) and build a typed Config."""
    os.environ.setdefault(_WORKING_DIR_VARIABLE, WORKING_DIR)
    try:
        with open(path, encoding="utf-8") as f:
            parsed: object = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as error:
        raise ConfigLoadError(_READ_ERROR.format(path=path, error=error), document=path) from error
    raw_user_config = parsed if isinstance(parsed, dict) else {}
    try:
        migrated = upcast_for_read(path, raw_user_config, subject=SubjectRef(ConfigSubjectKind.COMPUTER))
    except ValueError as error:
        raise ConfigLoadError(_READ_ERROR.format(path=path, error=error), document=path) from error
    return build_config_from_raw(migrated, path.parent, config_source=path)


# Runtime config lives at ~/.teleclaude/config.yml, seeded from the repo blueprint.
_config_path = resolve_runtime_config_path()
_config: TeleclaudeConfig | None = None
config_path = _config_path
dotenv_path = ENV_PATH  # public alias; the config watcher watches config_path + dotenv_path


def machine_configuration_sources() -> list[Path]:
    """The files the machine configuration is built from; a change to any of them can change it."""
    return [_config_path, _config_path.parent / EXPERIMENTS_FILE_NAME, dotenv_path]


def _runtime_config() -> TeleclaudeConfig:
    """Load the runtime aggregate only when a runtime consumer requests it."""
    global _config
    if _config is None:
        if not _config_path.exists():
            raise FileNotFoundError(f"Config file not found: {_config_path}. Run 'telec config wizard' to create it.")
        _config = _load_config_from_disk(_config_path)
    return _config


class _RuntimeConfigAccessor:
    """Delegate runtime configuration attribute access to the lazy aggregate."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_runtime_config(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(_runtime_config(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(_runtime_config(), name)


# Keep the established import surface and aggregate type for consumers. Importing
# this binding is cheap; using an aggregate attribute is the resolution boundary.
config = cast(TeleclaudeConfig, _RuntimeConfigAccessor())


def loaded_machine_config() -> TeleclaudeConfig:
    """The validated machine configuration model this process runs on, loading it on first use."""
    return _runtime_config()


def reload_config() -> list[str]:
    """Re-read config from disk and apply it to the live ``config`` singleton in place.

    The singleton's identity is preserved, so every ``from teleclaude.config.machine import config``
    holder observes the new values without re-importing. Returns the names of the top-level
    sections that changed. Changed sections in ``HOT_RELOADABLE_SECTIONS`` take effect live;
    any other changed section needs a daemon restart (see ``restart_required_sections``).
    """
    current = _runtime_config()
    fresh = _load_config_from_disk(_config_path)
    changed = [
        name
        for name in TeleclaudeConfig.model_fields
        if name != CONFIG_LOAD_ID and getattr(current, name) != getattr(fresh, name)
    ]
    for name in TeleclaudeConfig.model_fields:
        object.__setattr__(current, name, getattr(fresh, name))
    object.__setattr__(current, "__pydantic_fields_set__", set(fresh.__pydantic_fields_set__))
    return changed
