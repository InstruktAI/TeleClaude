"""Project artifact syncing for TeleClaude."""

from pathlib import Path


def sync_project_artifacts(project_root: Path) -> None:
    """Build snippet indexes and distribute artifacts via ``telec sync``."""
    from teleclaude import sync as teleclaude_sync  # pylint: disable=import-outside-toplevel,ungrouped-imports

    ok = teleclaude_sync.sync(project_root, warn_only=True)
    if not ok:
        print("telec init: sync completed with warnings.")
