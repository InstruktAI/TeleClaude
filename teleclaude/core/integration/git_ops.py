"""Low-level git helpers for the integration state machine.

Pure process-boundary git I/O (GitPython wrapper plus thin readers) extracted so
the step-function module stays focused on phase logic. No imports from
``step_functions`` or ``state_machine`` — this is a leaf module.
"""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.git import GIT_EXECUTABLE, GitCommandError, Repo

logger = get_logger(__name__)

__all__ = [
    "_get_branch_log",
    "_get_conflicted_files",
    "_get_diff_stats",
    "_get_head_sha",
    "_get_remote_main_sha",
    "_git_dir",
    "_merge_head_exists",
    "_run_git",
]


def _run_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
    """Run a git command via GitPython; return (returncode, stdout, stderr)."""
    try:
        repo = Repo(cwd, search_parent_directories=True)
        stdout = str(repo.git.execute([GIT_EXECUTABLE, *args]))
        return 0, stdout, ""
    except GitCommandError as exc:
        rc = exc.status if isinstance(exc.status, int) else 1
        return rc, exc.stdout or "", exc.stderr or ""
    except Exception as exc:
        logger.warning("git %s failed: %s", " ".join(args[:2]), exc)
        return 1, "", str(exc)


def _get_head_sha(cwd: str) -> str | None:
    rc, stdout, _ = _run_git(["rev-parse", "HEAD"], cwd=cwd)
    return stdout.strip() if rc == 0 and stdout.strip() else None


def _get_remote_main_sha(cwd: str) -> str | None:
    rc, stdout, _ = _run_git(["ls-remote", "origin", "refs/heads/main"], cwd=cwd)
    if rc != 0 or not stdout.strip():
        return None
    parts = stdout.strip().split()
    return parts[0] if parts else None


def _git_dir(cwd: str) -> Path | None:
    """Return the actual .git directory, handling worktree indirection."""
    rc, stdout, _ = _run_git(["rev-parse", "--git-dir"], cwd=cwd)
    if rc != 0:
        return None
    git_dir = Path(stdout.strip())
    if not git_dir.is_absolute():
        git_dir = Path(cwd) / git_dir
    return git_dir


def _merge_head_exists(cwd: str) -> bool:
    gd = _git_dir(cwd)
    return gd is not None and (gd / "MERGE_HEAD").exists()


def _get_conflicted_files(cwd: str) -> list[str]:
    rc, stdout, _ = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=cwd)
    if rc != 0:
        return []
    return [f.strip() for f in stdout.splitlines() if f.strip()]


def _get_diff_stats(cwd: str) -> str:
    rc, stdout, _ = _run_git(["diff", "--cached", "--stat"], cwd=cwd)
    return stdout.strip() if rc == 0 else ""


def _get_branch_log(cwd: str, branch: str, *, base_ref: str = "main") -> str:
    rc, stdout, _ = _run_git(["log", f"{base_ref}..{branch}", "--oneline", "--no-decorate"], cwd=cwd)
    return stdout.strip() if rc == 0 else ""
