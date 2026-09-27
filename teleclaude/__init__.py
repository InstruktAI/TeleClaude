"""Public package surface."""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path
from typing import cast

__version__: str


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
    metadata = importlib.import_module("importlib.metadata")
    try:
        metadata_version = cast(str, metadata.version("teleclaude"))
    except metadata.PackageNotFoundError:
        return pyproject_version

    # In source-tree runs, local pyproject version is authoritative.
    if pyproject_version not in ("0.0.0", metadata_version):
        return pyproject_version

    return metadata_version


def __getattr__(name: str) -> str:
    """Resolve package metadata only when a caller asks for the version."""
    if name != "__version__":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = _resolve_version()
    globals()[name] = value
    return value


__all__ = ["__version__"]
