"""This computer's machine configuration: loaded on first attribute access, reloaded in place.

Available as ``from teleclaude.config.machine import config``.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import yaml
from dotenv import dotenv_values

from teleclaude.config._bootstrap import resolve_runtime_config_path
from teleclaude.config._machine_build import (
    CONFIG_LOAD_ID,
    WORKING_DIR,
    build_config_from_raw,
)
from teleclaude.config._models import (
    TeleclaudeConfig,
)
from teleclaude.config.errors import ConfigLoadError
from teleclaude.config.migrations.read import upcast_for_read
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.paths import PROJECT_ENV_PATH

_dotenv_path = PROJECT_ENV_PATH
_WORKING_DIR_VARIABLE = "WORKING_DIR"
_READ_ERROR = "Failed to read config file {path}: {error}"

# Variables present before any .env load are shell-provided and keep precedence;
# .env-sourced variables are refreshed from the file on every (re)load.
_PRE_DOTENV_ENV_KEYS = frozenset(os.environ)
# Keys currently sourced from .env, so a reload can drop ones deleted from the file.
_dotenv_managed_keys: set[str] = set()


def _refresh_dotenv() -> None:
    """Apply the .env file to os.environ so config reload observes out-of-process edits.

    Shell-provided variables (captured before the first load) keep precedence over .env.
    .env-sourced variables are refreshed each call, and ones removed from the file are
    dropped from os.environ — so reload_config() reflects both edits and deletions of
    the ${VAR}-backed values the TUI writes to .env (Redis creds, summarizer URL, keys).
    """
    values = dotenv_values(_dotenv_path)
    current = {k for k, v in values.items() if v is not None and k not in _PRE_DOTENV_ENV_KEYS}
    for key in _dotenv_managed_keys - current:
        os.environ.pop(key, None)
    for key in current:
        os.environ[key] = str(values[key])
    _dotenv_managed_keys.clear()
    _dotenv_managed_keys.update(current)


def machine_runtime_environment() -> Mapping[str, str]:
    """Expose the established machine runtime environment to config adapters."""
    return os.environ


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
    _refresh_dotenv()  # pick up out-of-process .env edits before expanding ${VAR} placeholders
    os.environ.setdefault(_WORKING_DIR_VARIABLE, WORKING_DIR)
    try:
        with open(path, encoding="utf-8") as f:
            parsed: object = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as error:
        raise ConfigLoadError(_READ_ERROR.format(path=path, error=error), document=path) from error
    raw_user_config = parsed if isinstance(parsed, dict) else {}
    migrated = upcast_for_read(path, raw_user_config, subject=SubjectRef(ConfigSubjectKind.COMPUTER))
    return build_config_from_raw(migrated, path.parent, config_source=path)


# Runtime config lives at ~/.teleclaude/config.yml, seeded from the repo blueprint.
_config_path = resolve_runtime_config_path()
_config: TeleclaudeConfig | None = None
config_path = _config_path
dotenv_path = _dotenv_path  # public alias; the config watcher watches config_path + dotenv_path


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
