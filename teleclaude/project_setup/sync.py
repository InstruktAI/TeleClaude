"""Project artifact syncing for TeleClaude."""

from pathlib import Path

from teleclaude import sync as teleclaude_sync


def sync_project_artifacts(project_root: Path) -> None:
    """Build snippet indexes and distribute artifacts via ``telec sync``."""
    ok = teleclaude_sync.sync(project_root, warn_only=True)
    if not ok:
        print("telec init: sync completed with warnings.")
