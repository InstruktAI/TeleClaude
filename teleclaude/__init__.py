"""Public package surface."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _version_from_pyproject() -> str:
    """Fallback to pyproject.toml when package metadata is unavailable."""
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return "0.0.0"

    project = data.get("project")
    if not isinstance(project, dict):
        return "0.0.0"

    project_version = project.get("version")
    if not isinstance(project_version, str):
        return "0.0.0"

    return project_version


def _resolve_version() -> str:
    """Read runtime version from installed package metadata."""
    pyproject_version = _version_from_pyproject()
    try:
        metadata_version = version("teleclaude")
    except PackageNotFoundError:
        return pyproject_version

    # In source-tree runs, local pyproject version is authoritative.
    if pyproject_version != "0.0.0" and pyproject_version != metadata_version:
        return pyproject_version

    return metadata_version


__version__ = _resolve_version()

__all__ = ["__version__"]
