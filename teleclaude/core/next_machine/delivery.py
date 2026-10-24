"""Delivery cleanup — worktree, branch, and binary artifact archival.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import cast
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine.worktree_home import (
    WorktreeHomeCleanupError,
    move_worktree_home,
    release_worktree_home,
)
from teleclaude.git import GIT_EXECUTABLE, GitCommandError, Repo
from teleclaude.paths import STORAGE_DIR
from teleclaude.runtime.agy_workspace_trust import remove_worktree_trust

logger = get_logger(__name__)

GitNameSetFailureHandler = Callable[[list[str], str], None]

GIT_COMMAND_TIMEOUT_SECONDS = 30
GIT_TIMEOUT_ERROR_TEMPLATE = "timeout after {timeout}s"

_WORKTREE_DETACH_FAILED = "worktree detachment failed for %s: %s"
_WORKTREE_TRASH_DIR = ".trash"
_WORKTREE_TRASH_ENTRY_TEMPLATE = "{slug}-{nonce}"
_WORKTREE_TRASH_RECLAIM_FAILED = "worktree trash reclaim failed for %s: %s"
_WORKTREE_HOME_RELEASE_FAILED = "worktree home release failed for %s: %s"


def _run_git_cmd(
    args: list[str],
    *,
    cwd: str,
    timeout: float | None = GIT_COMMAND_TIMEOUT_SECONDS,
    preserve_stdout_newlines: bool = False,
) -> tuple[int, str, str]:
    """Run a git command; return (returncode, stdout, stderr)."""
    try:
        repo = Repo(cwd, search_parent_directories=True)
        execute = cast(Callable[..., object], repo.git.execute)
        if timeout is None:
            output = str(execute([GIT_EXECUTABLE, *args], strip_newline_in_stdout=not preserve_stdout_newlines))
        else:
            output = str(
                execute(
                    [GIT_EXECUTABLE, *args],
                    kill_after_timeout=timeout,
                    strip_newline_in_stdout=not preserve_stdout_newlines,
                )
            )
        return 0, output, ""
    except GitCommandError as exc:
        if timeout is not None and "timeout" in str(exc).lower():
            logger.warning("git %s timed out after %.0fs", " ".join(args[:2]), timeout)
            return 1, "", GIT_TIMEOUT_ERROR_TEMPLATE.format(timeout=timeout)
        rc = exc.status if isinstance(exc.status, int) else 1
        return rc, exc.stdout or "", exc.stderr or ""


def parse_git_name_list(stdout: str) -> set[str]:
    """Return the path set from Git name-only output."""
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def parse_git_porcelain_paths(stdout: str) -> set[str]:
    """Return changed paths from Git porcelain output."""
    paths: set[str] = set()
    for line in stdout.splitlines():
        if not line.strip():
            continue
        raw_path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in raw_path:
            raw_path = raw_path.rsplit(" -> ", 1)[1]
        paths.add(raw_path.strip('"'))
    return paths


def git_name_set(
    project_root: Path,
    args: list[str],
    *,
    on_failure: GitNameSetFailureHandler | None = None,
) -> set[str] | None:
    """Run Git and parse its name-only result, optionally reporting a failure."""
    returncode, stdout, stderr = _run_git_cmd(args, cwd=str(project_root))
    if returncode != 0:
        if on_failure is not None:
            on_failure(args, stderr)
        return None
    return parse_git_name_list(stdout)


_BINARY_ARTIFACT_DIRS = ("art", "html", "input")

_STORAGE_ROOT = STORAGE_DIR


@dataclass(frozen=True)
class TodoSlugSurfaceMove:
    """A completed physical rename leg."""

    surface: TodoSlugSurface
    old: Path | str
    new: Path | str


class TodoSlugSurface(StrEnum):
    """Closed vocabulary for physical todo-slug rename surfaces."""

    REMOTE_BRANCH = "remote_branch"
    WORKTREE = "worktree"
    HOME = "home"
    LOCAL_BRANCH = "local_branch"
    WORKSPACE = "workspace"


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _project_has_git(project_root: Path) -> bool:
    return _path_exists(project_root / ".git")


def _local_branch_exists(cwd: str, branch: str) -> bool:
    rc, _, _ = _run_git_cmd(["rev-parse", "--verify", branch], cwd=cwd, timeout=5)
    return rc == 0


def _ensure_destination_absent(destination: Path) -> None:
    if _path_exists(destination):
        msg = f"rename destination already exists: {destination}"
        raise FileExistsError(msg)


def _move_path(source: Path, destination: Path) -> None:
    _ensure_destination_absent(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def _rollback_path(source: Path, destination: Path) -> None:
    if _path_exists(destination) and not _path_exists(source):
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(source))


def move_todo_slug_surfaces(cwd: str, old_slug: str, new_slug: str) -> list[TodoSlugSurfaceMove]:
    """Move physical todo surfaces from old slug to new slug, recording inverses."""
    project_root = Path(cwd)
    moves: list[TodoSlugSurfaceMove] = []

    try:
        if _project_has_git(project_root) and _local_branch_exists(cwd, old_slug):
            rc, _, stderr = _run_git_cmd(["push", "origin", f"{old_slug}:{new_slug}"], cwd=cwd, timeout=10)
            if rc != 0:
                msg = f"git push new rename ref failed for {old_slug!r}->{new_slug!r}: {stderr.strip()}"
                raise RuntimeError(msg)
            moves.append(TodoSlugSurfaceMove(surface=TodoSlugSurface.REMOTE_BRANCH, old=old_slug, new=new_slug))

        old_worktree = project_root / WORKTREE_DIR / old_slug
        new_worktree = project_root / WORKTREE_DIR / new_slug
        if _path_exists(old_worktree):
            _ensure_destination_absent(new_worktree)
            if _project_has_git(project_root):
                rc, _, stderr = _run_git_cmd(
                    ["worktree", "move", str(old_worktree), str(new_worktree)], cwd=cwd, timeout=10
                )
                if rc != 0:
                    msg = f"git worktree move failed for {old_slug!r}->{new_slug!r}: {stderr.strip()}"
                    raise RuntimeError(msg)
            else:
                _move_path(old_worktree, new_worktree)
            moves.append(TodoSlugSurfaceMove(surface=TodoSlugSurface.WORKTREE, old=old_worktree, new=new_worktree))

        if move_worktree_home(project_root, old_slug, new_slug):
            moves.append(TodoSlugSurfaceMove(surface=TodoSlugSurface.HOME, old=old_slug, new=new_slug))

        if _project_has_git(project_root) and _local_branch_exists(cwd, old_slug):
            rc, _, stderr = _run_git_cmd(["branch", "-m", old_slug, new_slug], cwd=cwd, timeout=10)
            if rc != 0:
                msg = f"git branch rename failed for {old_slug!r}->{new_slug!r}: {stderr.strip()}"
                raise RuntimeError(msg)
            moves.append(TodoSlugSurfaceMove(surface=TodoSlugSurface.LOCAL_BRANCH, old=old_slug, new=new_slug))

        old_workspace = project_root / "workspace" / old_slug
        new_workspace = project_root / "workspace" / new_slug
        if _path_exists(old_workspace):
            _move_path(old_workspace, new_workspace)
            moves.append(TodoSlugSurfaceMove(surface=TodoSlugSurface.WORKSPACE, old=old_workspace, new=new_workspace))
    except Exception:
        rollback_todo_slug_surfaces(cwd, moves)
        raise

    return moves


def rollback_todo_slug_surfaces(cwd: str, moves: list[TodoSlugSurfaceMove]) -> None:
    """Best-effort LIFO compensation for physical rename legs."""
    project_root = Path(cwd)
    for move in reversed(moves):
        try:
            if move.surface is TodoSlugSurface.WORKSPACE:
                _rollback_path(Path(move.old), Path(move.new))
            elif move.surface is TodoSlugSurface.WORKTREE:
                if _project_has_git(project_root):
                    rc, _, stderr = _run_git_cmd(
                        ["worktree", "move", str(move.new), str(move.old)], cwd=cwd, timeout=10
                    )
                    if rc != 0:
                        msg = f"git worktree rollback failed for {move.new!s}->{move.old!s}: {stderr.strip()}"
                        raise RuntimeError(msg)
                else:
                    _rollback_path(Path(move.old), Path(move.new))
            elif move.surface is TodoSlugSurface.HOME:
                move_worktree_home(project_root, str(move.new), str(move.old))
            elif move.surface is TodoSlugSurface.LOCAL_BRANCH:
                _run_git_cmd(["branch", "-m", str(move.new), str(move.old)], cwd=cwd, timeout=10)
            elif move.surface is TodoSlugSurface.REMOTE_BRANCH:
                _run_git_cmd(["push", "origin", "--delete", str(move.new)], cwd=cwd, timeout=5)
        except Exception as exc:  # pragma: no cover - rollback logging is best effort
            logger.warning("rename rollback failed for %s: %s", move.surface, exc)


def delete_old_remote_slug_ref(cwd: str, old_slug: str) -> None:
    """Best-effort post-commit cleanup of the old remote branch."""
    rc, _, stderr = _run_git_cmd(["push", "origin", "--delete", old_slug], cwd=cwd, timeout=5)
    if rc != 0:
        logger.warning("old remote branch cleanup failed for %s: %s", old_slug, stderr.strip())


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


def reclaim_worktree_trash(cwd: str) -> None:
    """Reclaim detached worktrees while keeping the container available to writers."""
    trash_dir = Path(cwd) / WORKTREE_DIR / _WORKTREE_TRASH_DIR
    try:
        entries = sorted(trash_dir.iterdir())
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning(_WORKTREE_TRASH_RECLAIM_FAILED, trash_dir, exc)
        return

    for entry in entries:
        try:
            if entry.is_symlink() or entry.is_file():
                entry.unlink(missing_ok=True)
            elif entry.is_dir():
                shutil.rmtree(entry)
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning(_WORKTREE_TRASH_RECLAIM_FAILED, entry, exc)


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

    # 1. Detach the worktree for background reclamation, then prune its bookkeeping.
    worktree_path = project_root / WORKTREE_DIR / slug
    if worktree_path.exists():
        _run_git_cmd(["worktree", "unlock", str(worktree_path)], cwd=cwd, timeout=None)
        trash_dir = project_root / WORKTREE_DIR / _WORKTREE_TRASH_DIR
        trash_path = trash_dir / _WORKTREE_TRASH_ENTRY_TEMPLATE.format(slug=slug, nonce=uuid4().hex)
        try:
            trash_dir.mkdir(parents=True, exist_ok=True)
            worktree_path.rename(trash_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning(_WORKTREE_DETACH_FAILED, slug, exc)
        _run_git_cmd(["worktree", "prune", "--expire=now"], cwd=cwd, timeout=None)

    remove_worktree_trust(worktree_path)

    try:
        release_worktree_home(project_root, slug)
    except WorktreeHomeCleanupError as exc:
        logger.warning(_WORKTREE_HOME_RELEASE_FAILED, slug, exc, exc_info=True)

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
