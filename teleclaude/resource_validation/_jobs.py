"""Jobs-configuration validation at the resource-validation boundary."""

from __future__ import annotations

from pathlib import Path

from teleclaude.config.jobs import load_effective_jobs
from teleclaude.paths import ConfigFileName

__all__ = ["validate_jobs_config"]


def validate_jobs_config(project_root: Path) -> list[str]:
    """Translate the config owner's effective-set refusal into lint findings."""
    try:
        load_effective_jobs(project_root)
    except (OSError, ValueError) as exc:
        return [f"{project_root / ConfigFileName.OVERLAY}: {exc}"]
    return []
