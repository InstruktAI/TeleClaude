"""Root-only project registry persisted at ``~/.teleclaude/projects.yaml``.

The manifest stores just the list of absolute project root paths. All metadata
(project name, description, jobs, docs index path) lives in each project's own
``teleclaude.yml`` and is loaded through the project catalog service.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import yaml

from teleclaude.paths import PROJECTS_MANIFEST_PATH

MANIFEST_PATH = PROJECTS_MANIFEST_PATH
_UTF8 = "utf-8"


class RegisteredProjectRoot(NamedTuple):
    """One manifest entry and whether its registered directory is available."""

    path: Path
    is_present: bool


def _normalize_manifest_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _coerce_root(raw: object) -> Path | None:
    """Accept either a string path or a legacy ``{project_root: ...}`` dict."""
    if isinstance(raw, str):
        text = raw.strip()
        return Path(text).expanduser().resolve() if text else None
    if isinstance(raw, dict):
        candidate = raw.get("project_root")
        if isinstance(candidate, str) and candidate.strip():
            return Path(candidate).expanduser().resolve()
    return None


def _parse_manifest_data(raw_data: object) -> list[Path]:
    if isinstance(raw_data, dict):
        raw_entries = raw_data.get("projects")
    elif isinstance(raw_data, list):
        raw_entries = raw_data
    else:
        raw_entries = []
    if not isinstance(raw_entries, list):
        return []

    roots: list[Path] = []
    seen: set[Path] = set()
    for entry in raw_entries:
        root = _coerce_root(entry)
        if root is None or root in seen:
            continue
        seen.add(root)
        roots.append(root)
    return roots


def load_roots(path: Path = MANIFEST_PATH) -> list[Path]:
    """Load registered project roots whose directories still exist on disk."""
    return [entry.path for entry in load_registered_roots(path) if entry.is_present]


def load_registered_roots(path: Path = MANIFEST_PATH) -> list[RegisteredProjectRoot]:
    """Load every registered project root, retaining unavailable entries."""
    manifest_path = _normalize_manifest_path(path)
    if not manifest_path.exists():
        return []

    try:
        raw_data: object = yaml.safe_load(manifest_path.read_text(encoding=_UTF8))
    except (yaml.YAMLError, OSError):
        return []

    roots = _parse_manifest_data(raw_data)
    return [RegisteredProjectRoot(path=root, is_present=root.is_dir()) for root in roots]


def register_root(*, path: Path | None = None, project_root: Path) -> None:
    """Idempotently append ``project_root`` to the registry file.

    ``path`` defaults to the module-level ``MANIFEST_PATH`` when omitted. We
    resolve the default at call time (not at function-definition time) so
    tests that monkeypatch ``project_manifest.MANIFEST_PATH`` observe the
    override without needing to reload the module.
    """
    manifest_path = _normalize_manifest_path(path if path is not None else MANIFEST_PATH)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    normalized = project_root.expanduser().resolve()

    existing_raw: object = None
    if manifest_path.exists():
        try:
            existing_raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            existing_raw = None

    roots = _parse_manifest_data(existing_raw)
    if normalized not in roots:
        roots.append(normalized)

    payload = {"projects": [str(root) for root in roots]}
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
