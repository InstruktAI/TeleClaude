"""Delivery cleanup — worktree, branch, and binary artifact archival.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.git import GitCommandError, Repo
from teleclaude.paths import STORAGE_DIR

logger = get_logger(__name__)


def _run_git_cmd(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
    """Run a git command; return (returncode, stdout, stderr)."""
    try:
        repo = Repo(cwd, search_parent_directories=True)
        output = str(repo.git.execute(["git", *args]))
        return 0, output, ""
    except GitCommandError as exc:
        if "timeout" in str(exc).lower():
            logger.warning("git %s timed out after %.0fs", " ".join(args[:2]), timeout)
            return 1, "", f"timeout after {timeout}s"
        rc = exc.status if isinstance(exc.status, int) else 1
        return rc, exc.stdout or "", exc.stderr or ""


_BINARY_ARTIFACT_DIRS = ("art", "html", "input")

_STORAGE_ROOT = STORAGE_DIR


def _archive_binary_artifacts(project_root: Path, slug: str) -> None:
    """Move binary artifact directories from workspace to permanent storage.

    Archives art/, html/, and input/ directories from workspace/{slug}/
    to ~/.teleclaude/storage/{delivery_date}/{slug}/ before cleanup.
    Only moves directories that exist and contain files.
    """
    workspace_slug_dir = project_root / "workspace" / slug
    if not workspace_slug_dir.exists():
        return

    delivery_date = date.today().isoformat()
    storage_dir = _STORAGE_ROOT / delivery_date / slug

    for dirname in _BINARY_ARTIFACT_DIRS:
        source = workspace_slug_dir / dirname
        if not source.is_dir():
            continue
        if not any(source.iterdir()):
            continue

        dest = storage_dir / dirname
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(dest))
            logger.info("Archived %s/%s → %s", slug, dirname, dest)
        except Exception as exc:
            logger.warning("Failed to archive %s/%s: %s", slug, dirname, exc)


def cleanup_delivered_slug(
    cwd: str,
    slug: str,
    *,
    branch: str | None = None,
    remove_remote_branch: bool = True,
) -> None:
    """Idempotent cleanup of all physical artifacts for a delivered slug.

    Each step is a no-op if the artifact is already gone.
    """
    branch = branch or slug
    project_root = Path(cwd)

    # 0. Archive binary artifacts (art/, html/) from workspace/ before cleanup
    _archive_binary_artifacts(project_root, slug)

    # 1. Remove worktree
    worktree_path = project_root / WORKTREE_DIR / slug
    if worktree_path.exists():
        rc, _, stderr = _run_git_cmd(["worktree", "remove", "--force", str(worktree_path)], cwd=cwd, timeout=10)
        if rc != 0:
            logger.warning("worktree remove failed for %s: %s", slug, stderr.strip())

    # 2. Delete local branch
    _run_git_cmd(["branch", "-D", branch], cwd=cwd)

    # 3. Delete remote branch (non-fatal, tight timeout)
    if remove_remote_branch:
        _run_git_cmd(["push", "origin", "--delete", branch], cwd=cwd, timeout=5)

    # 4. Clean up workspace/{slug}/ directory
    workspace_dir = project_root / "workspace" / slug
    if workspace_dir.is_symlink():
        workspace_dir.unlink()
    elif workspace_dir.exists():
        shutil.rmtree(str(workspace_dir), ignore_errors=True)
