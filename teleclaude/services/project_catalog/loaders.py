"""Load project metadata from a registered root directory."""

from __future__ import annotations

from pathlib import Path

from teleclaude.config.loader import load_project_config
from teleclaude.paths import ConfigFileName
from teleclaude.services.project_catalog.models import ProjectNode
from teleclaude.slug import normalize_slug


def load_project_node(root: Path) -> ProjectNode | None:
    """Build a ``ProjectNode`` from a registered project root.

    Returns ``None`` when the project directory exists but does not contain a
    loadable ``teleclaude.yml``. Missing slugs are derived from ``project_name``
    (falling back to the directory name) via :func:`normalize_slug`.
    """
    resolved_root = root.expanduser().resolve()
    config_path = resolved_root / ConfigFileName.OVERLAY
    if not config_path.is_file():
        return None

    try:
        config = load_project_config(config_path)
    except (ValueError, OSError):
        return None

    slug = (config.project_slug or "").strip()
    if not slug:
        source = config.project_name or resolved_root.name
        slug = normalize_slug(source)
    if not slug:
        return None

    return ProjectNode(root=resolved_root, slug=slug, config=config)
