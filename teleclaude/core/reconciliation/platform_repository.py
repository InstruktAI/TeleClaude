"""Which repositories are the platform's own.

The platform's code runs from a release of the installation, so the checkout the running code sits in
no longer says which project is the platform's. A repository is the platform's own when it is the one
the running code belongs to, when it is a release of the installation, or when it shares history with
the repository the installation keeps: a contributor's clone, or a fork they follow, descends from the
same first commit as every release installed from it
(``local/projects/teleclaude/design/architecture/installation``).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from teleclaude.core.reconciliation.installation import InstallationLayout
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.paths import REPO_ROOT

_ROOT_COMMITS_ARGUMENTS = ("--max-parents=0", "--all")
_REPOSITORY_FAILURES = (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError)


def _common_directory(root: Path) -> Path | None:
    """Git's shared directory for a checkout, a linked worktree or a bare repository; ``None`` when ``root`` has none."""
    try:
        return Path(Repo(str(root), search_parent_directories=True).common_dir).resolve()
    except _REPOSITORY_FAILURES:
        return None


@cache
def _root_commits(common_directory: Path) -> frozenset[str]:
    """The first commits of every history a repository holds."""
    try:
        listed = str(Repo(str(common_directory)).git.rev_list(*_ROOT_COMMITS_ARGUMENTS))
    except _REPOSITORY_FAILURES:
        return frozenset()
    return frozenset(listed.split())


def is_platform_repository(root: Path, layout: InstallationLayout | None = None) -> bool:
    """Whether ``root`` belongs to the platform's own repository."""
    common = _common_directory(root)
    if common is None:
        return False
    if common == _common_directory(REPO_ROOT):
        return True
    resolved = layout or InstallationLayout()
    if resolved.release_revision(root) is not None:
        return True
    kept = _common_directory(resolved.repository) if resolved.repository.is_dir() else None
    return kept is not None and bool(_root_commits(common) & _root_commits(kept))


def platform_scope_key(layout: InstallationLayout | None = None) -> str:
    """The key under which the platform's published artifacts are owned, stable across releases.

    A release's own folder changes with every install, so code running from a release is owned under the
    installation's kept repository; code running from any other checkout is owned under that checkout.
    """
    resolved = layout or InstallationLayout()
    if resolved.release_revision(REPO_ROOT) is not None:
        return str(resolved.repository.resolve())
    common = _common_directory(REPO_ROOT)
    return str(common.parent if common is not None and common.name == ".git" else REPO_ROOT.resolve())
