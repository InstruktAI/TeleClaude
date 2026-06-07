"""Project artifact syncing for TeleClaude."""

from pathlib import Path

from teleclaude import sync as teleclaude_sync


def sync_project_artifacts(project_root: Path) -> None:
    """Build snippet indexes and distribute artifacts for project bootstrap.

    Delegates to the bootstrap sync: validation runs and reports findings without
    blocking, then artifacts deploy. A fresh or imperfect project sets up while still
    surfacing issues; the commit gate enforces validation once real work begins.
    """
    teleclaude_sync.sync_bootstrap(project_root)
