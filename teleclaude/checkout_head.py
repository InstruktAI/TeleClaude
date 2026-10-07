"""The commit a checkout stands on, read for a process that records where it started."""

from __future__ import annotations

from pathlib import Path

from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

__all__ = ["read_checkout_head"]


def read_checkout_head(checkout: Path) -> str | None:
    """Return the full commit id ``checkout`` stands on, or ``None`` when git cannot say."""
    try:
        return Repo(str(checkout)).head.commit.hexsha
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError):
        return None
