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

_STORAGE_ROOT = Path("~/.teleclaude/storage").expanduser()


def _archive_binary_artifacts(worktree_path: Path, slug: str) -> None:
    """Move binary artifact directories from worktree to permanent storage.

    Archives art/, html/, and input/ directories to
    ~/.teleclaude/storage/{delivery_date}/{slug}/ before worktree cleanup.
    Only moves directories that exist and contain files.
    """
    if not worktree_path.exists():
        return

    delivery_date = date.today().isoformat()
    storage_dir = _STORAGE_ROOT / delivery_date / slug

    for dirname in _BINARY_ARTIFACT_DIRS:
        source = worktree_path / "todos" / slug / dirname
        if not source.is_dir():
            continue
        if not any(source.iterdir()):
            continue

        dest = storage_dir / dirname
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(dest))
            logger.info("Archived %s/%s → %s", slug, dirname, dest)
        except Exception as exc:  # pylint: disable=broad-exception-caught
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

    # 0. Archive binary artifacts (art/, html/) before worktree removal
    worktree_path = Path(cwd) / WORKTREE_DIR / slug
    _archive_binary_artifacts(worktree_path, slug)

    # 1. Remove worktree
    if worktree_path.exists():
        rc, _, stderr = _run_git_cmd(["worktree", "remove", "--force", str(worktree_path)], cwd=cwd, timeout=10)
        if rc != 0:
            logger.warning("worktree remove failed for %s: %s", slug, stderr.strip())

    # 2. Delete local branch
    _run_git_cmd(["branch", "-D", branch], cwd=cwd)

    # 3. Delete remote branch (non-fatal, tight timeout)
    if remove_remote_branch:
        _run_git_cmd(["push", "origin", "--delete", branch], cwd=cwd, timeout=5)

    # 4. Remove todo directory (symlink-safe: unlink symlink, don't rmtree through it)
    todo_dir = Path(cwd) / "todos" / slug
    if todo_dir.is_symlink():
        todo_dir.unlink()
    elif todo_dir.exists():
        shutil.rmtree(str(todo_dir), ignore_errors=True)
