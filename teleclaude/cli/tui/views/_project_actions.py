"""Shared helpers for project-related view actions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, TypedDict, cast

import yaml


class NewProjectResultLike(Protocol):  # pylint: disable=too-few-public-methods
    """Duck-typed project modal result used by the view helpers."""

    name: str
    path: str
    description: str | None


class ProjectNotifier(Protocol):  # pylint: disable=too-few-public-methods
    """Minimal notification protocol needed by project action helpers."""

    def notify(self, message: str, *, severity: str = "information") -> None:
        """Notify the user of a project action result."""


class TrustedDirEntryData(TypedDict, total=False):
    """Typed representation of one trusted_dirs YAML entry."""

    name: str
    path: str
    desc: str
    discord_forum: int


class ComputerConfigData(TypedDict, total=False):
    """Typed subset of the computer section used by this helper."""

    trusted_dirs: list[TrustedDirEntryData]


class RootConfigData(TypedDict, total=False):
    """Typed subset of config.yml needed by this helper."""

    computer: ComputerConfigData


def _resolve_config_path() -> Path:
    """Resolve the daemon config path using the same precedence as `telec config`."""
    env_path = os.getenv("TELECLAUDE_CONFIG_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return Path.cwd() / "config.yml"


def _load_raw_config(path: Path) -> RootConfigData:
    """Load the current config.yml as a YAML mapping."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found at {path}")

    with open(path, encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle) or {}

    if not isinstance(raw_config, dict):
        raise ValueError("Config must be a YAML mapping.")

    return cast(RootConfigData, raw_config)


def _build_trusted_dir_entry(result: NewProjectResultLike) -> TrustedDirEntryData:
    """Serialize the modal result to the config.yml trusted_dirs shape."""
    entry: TrustedDirEntryData = {
        "name": result.name,
        "path": result.path,
    }
    description = result.description.strip() if result.description else ""
    if description:
        entry["desc"] = description
    return entry


def _write_raw_config(path: Path, raw_config: RootConfigData) -> None:
    """Persist config.yml atomically."""
    temp_path = path.with_suffix(".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(raw_config, handle, sort_keys=False)
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def save_new_project(app: ProjectNotifier, result: NewProjectResultLike) -> bool:
    """Persist a new trusted project and notify the user about the outcome."""
    try:
        config_path = _resolve_config_path()
        raw_config = _load_raw_config(config_path)
        computer_obj = raw_config.get("computer")
        if computer_obj is None:
            computer_raw: ComputerConfigData = {}
            raw_config["computer"] = computer_raw
        elif not isinstance(computer_obj, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError("Config key `computer` must be a YAML mapping.")
        else:
            computer_raw = computer_obj

        trusted_dirs_obj = computer_raw.get("trusted_dirs")
        if trusted_dirs_obj is None:
            trusted_dirs_raw: list[TrustedDirEntryData] = []
            computer_raw["trusted_dirs"] = trusted_dirs_raw
        elif not isinstance(trusted_dirs_obj, list):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError("Config key `computer.trusted_dirs` must be a YAML list.")
        else:
            for item in trusted_dirs_obj:
                if not isinstance(item, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
                    raise ValueError("Config key `computer.trusted_dirs` must contain YAML mappings.")
            trusted_dirs_raw = trusted_dirs_obj

        trusted_dirs_raw.append(_build_trusted_dir_entry(result))
        _write_raw_config(config_path, raw_config)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        app.notify(f"Failed to save project: {str(exc)[:80]}", severity="error")
        return False

    app.notify(f"Project '{result.name}' added")
    return True
