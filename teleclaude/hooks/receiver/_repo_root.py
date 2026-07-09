"""Compatibility shim for standalone hook bootstrap repo-root resolution."""

from __future__ import annotations

import importlib.util
from pathlib import Path

try:
    import teleclaude.project_root as _project_root
except ModuleNotFoundError as exc:
    _shared_path = Path(__file__).resolve().parents[2] / "project_root.py"
    _shared_spec = importlib.util.spec_from_file_location("teleclaude_project_root", _shared_path)
    if _shared_spec is None or _shared_spec.loader is None:
        raise RuntimeError(f"Unable to load project-root helper from {_shared_path}") from exc
    _shared_module = importlib.util.module_from_spec(_shared_spec)
    _shared_spec.loader.exec_module(_shared_module)
    resolve_project_root = _shared_module.resolve_project_root
else:
    resolve_project_root = _project_root.resolve_project_root
