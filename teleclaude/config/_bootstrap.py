"""Runtime machine-config location declaration."""

from __future__ import annotations

from pathlib import Path

from teleclaude.paths import MACHINE_CONFIG_PATH


def resolve_runtime_config_path() -> Path:
    """Return the machine-local path without reading or creating it."""
    return MACHINE_CONFIG_PATH
