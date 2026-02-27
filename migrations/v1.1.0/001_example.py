"""Example deployment migration: rename a config key in a local JSON file."""

from __future__ import annotations

import json
from pathlib import Path

_EXAMPLE_CONFIG_PATH = Path.home() / ".teleclaude" / "example_config.json"
_OLD_KEY = "legacy_feature_toggle"
_NEW_KEY = "feature_toggle"


def _read_config() -> dict[str, object]:
    if not _EXAMPLE_CONFIG_PATH.exists():
        return {}

    with _EXAMPLE_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid example config format: {_EXAMPLE_CONFIG_PATH}")
    return data


def _write_config(data: dict[str, object]) -> None:
    _EXAMPLE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _EXAMPLE_CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def check() -> bool:
    """Return True when the old key is already gone."""
    config = _read_config()
    return _OLD_KEY not in config


def migrate() -> bool:
    """Rename legacy_feature_toggle -> feature_toggle when needed."""
    config = _read_config()
    if _OLD_KEY not in config:
        return True

    value = config.pop(_OLD_KEY)
    config[_NEW_KEY] = value
    _write_config(config)
    return True
