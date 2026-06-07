"""Project artifact syncing for TeleClaude."""

from pathlib import Path

from teleclaude import sync as teleclaude_sync


def sync_project_artifacts(project_root: Path) -> None:
    """Build snippet indexes and distribute artifacts via ``telec sync``.

    Bootstrap deploy: skips validation so a fresh project sets up without blocking;
    the commit gate validates once real work begins.
    """
    teleclaude_sync.sync(project_root, skip_validation=True)
