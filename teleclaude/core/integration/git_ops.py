"""Low-level git helpers for the integration state machine.

Pure process-boundary git I/O (GitPython wrapper plus thin readers) extracted so
the step-function module stays focused on phase logic. No imports from
``step_functions`` or ``state_machine`` — this is a leaf module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.constants import ENV_ENABLE, INTEGRATOR_GITOP_ENV, WORKTREE_DIR
from teleclaude.git import GIT_EXECUTABLE, GitCommandError, Repo, no_autostash_env

logger = get_logger(__name__)

_GIT_FETCH_ORIGIN_MAIN_ARGS = ("fetch", "origin", "main")
_GIT_REV_LIST_COUNTS_ARGS = ("rev-list", "--left-right", "--count", "HEAD...origin/main")
_GIT_INCOMING_PATHS_ARGS = ("diff", "--name-only", "-z", "HEAD...origin/main")
_GIT_DIRTY_PATHS_ARGS = ("status", "--porcelain=v1", "-z")
_GIT_FAST_FORWARD_ARGS = ("merge", "--ff-only", "origin/main")
_GIT_PATH_SEPARATOR = "\0"
_GIT_STATUS_PATH_OFFSET = 3
_GIT_RENAME_OR_COPY_CODES = frozenset({"R", "C"})
_REPO_ROOT_SYNC_STARTED_LOG = "integration.repo_root_sync.started"
_REPO_ROOT_SYNC_CLASSIFIED_LOG = "integration.repo_root_sync.classified"


class RepoRootSyncStage(StrEnum):
    """Lifecycle boundary requesting a repo-root synchronization assessment."""

    ENTRY = "entry"
    POST_DELIVERY = "post_delivery"


class RepoRootSyncOutcome(StrEnum):
    """Closed outcomes for repo-root synchronization."""

    EQUAL = "equal"
    AHEAD_ONLY = "ahead_only"
    FAST_FORWARDED = "fast_forwarded"
    SPLIT_HISTORY = "split_history"
    DIRTY_OVERLAP = "dirty_overlap"
    FETCH_FAILED = "fetch_failed"
    GRAPH_INSPECTION_FAILED = "graph_inspection_failed"
    DIRTY_STATE_INSPECTION_FAILED = "dirty_state_inspection_failed"
    FAST_FORWARD_FAILED = "fast_forward_failed"
    BOOKKEEPING_PUSH_FAILED = "bookkeeping_push_failed"


@dataclass(frozen=True)
class RepoRootSyncResult:
    """Immutable graph, path, and failure facts for one synchronization attempt."""

    stage: RepoRootSyncStage
    outcome: RepoRootSyncOutcome
    sync_id: str
    session_id: str
    ahead_count: int = 0
    behind_count: int = 0
    incoming_paths: tuple[str, ...] = ()
    dirty_paths: tuple[str, ...] = ()
    dirty_overlap_paths: tuple[str, ...] = ()
    failed_operation: str | None = None
    diagnostic: str = ""

    @property
    def is_ready(self) -> bool:
        """Whether callers may continue through their normal sequencing."""
        return self.outcome in {
            RepoRootSyncOutcome.EQUAL,
            RepoRootSyncOutcome.AHEAD_ONLY,
            RepoRootSyncOutcome.FAST_FORWARDED,
        }


__all__ = [
    "RepoRootSyncOutcome",
    "RepoRootSyncResult",
    "RepoRootSyncStage",
    "_ensure_integration_worktree",
    "_get_branch_log",
    "_get_conflicted_files",
    "_get_diff_stats",
    "_get_head_sha",
    "_get_remote_main_sha",
    "_git_dir",
    "_integration_worktree_path",
    "_integrator_gitop_env",
    "_mark_repo_root_sync_failure",
    "_merge_head_exists",
    "_run_git",
    "_synchronize_repo_root",
]


def _integration_worktree_path(cwd: str) -> Path:
    """Compute the persistent integration worktree path."""
    return Path(cwd) / WORKTREE_DIR / "_integration"


def _integrator_gitop_env() -> dict[str, str]:
    """Env for git commands whose hook side effects the integrator owns explicitly.

    Composes ``no_autostash_env()`` so every integrator git operation is immune
    to ambient ``rebase.autoStash``/``merge.autoStash`` config — these calls run
    against trees concurrent agents may hold uncommitted work in, and ADR 0001's
    autostash-off invariant must hold regardless of the machine's git config.
    """
    env = no_autostash_env()
    env[INTEGRATOR_GITOP_ENV] = ENV_ENABLE
    return env


def _parse_nul_paths(output: str) -> tuple[str, ...]:
    """Return sorted, non-empty paths from Git's NUL-delimited path output."""
    return tuple(sorted(path for path in output.split(_GIT_PATH_SEPARATOR) if path))


def _parse_dirty_paths(output: str) -> tuple[str, ...]:
    """Return sorted repo-relative paths from porcelain-v1 NUL output."""
    entries = output.split(_GIT_PATH_SEPARATOR)
    paths: set[str] = set()
    index = 0
    while index < len(entries):
        entry = entries[index]
        if not entry:
            index += 1
            continue
        paths.add(entry[_GIT_STATUS_PATH_OFFSET:])
        if entry[:2] and any(code in _GIT_RENAME_OR_COPY_CODES for code in entry[:2]):
            index += 1
            if index < len(entries) and entries[index]:
                paths.add(entries[index])
        index += 1
    return tuple(sorted(path for path in paths if path))


def _sync_result(
    *,
    stage: RepoRootSyncStage,
    outcome: RepoRootSyncOutcome,
    sync_id: str,
    session_id: str,
    ahead_count: int = 0,
    behind_count: int = 0,
    incoming_paths: tuple[str, ...] = (),
    dirty_paths: tuple[str, ...] = (),
    dirty_overlap_paths: tuple[str, ...] = (),
    failed_operation: str | None = None,
    diagnostic: str = "",
) -> RepoRootSyncResult:
    """Create and log one closed synchronization outcome."""
    result = RepoRootSyncResult(
        stage=stage,
        outcome=outcome,
        sync_id=sync_id,
        session_id=session_id,
        ahead_count=ahead_count,
        behind_count=behind_count,
        incoming_paths=incoming_paths,
        dirty_paths=dirty_paths,
        dirty_overlap_paths=dirty_overlap_paths,
        failed_operation=failed_operation,
        diagnostic=diagnostic.strip(),
    )
    logger.info(
        _REPO_ROOT_SYNC_CLASSIFIED_LOG,
        extra={
            "stage": result.stage.value,
            "sync_id": result.sync_id,
            "session_id": result.session_id,
            "outcome": result.outcome.value,
            "ahead_count": result.ahead_count,
            "behind_count": result.behind_count,
            "incoming_path_count": len(result.incoming_paths),
            "dirty_overlap_paths": result.dirty_overlap_paths,
            "failed_operation": result.failed_operation,
        },
    )
    return result


def _synchronize_repo_root(*, cwd: str, session_id: str, stage: RepoRootSyncStage) -> RepoRootSyncResult:
    """Classify and safely fast-forward repo root against origin/main."""
    sync_id = uuid4().hex
    logger.info(
        _REPO_ROOT_SYNC_STARTED_LOG,
        extra={"stage": stage.value, "sync_id": sync_id, "session_id": session_id},
    )
    env = _integrator_gitop_env()
    fetch_rc, _, fetch_stderr = _run_git(list(_GIT_FETCH_ORIGIN_MAIN_ARGS), cwd=cwd, env=env)
    if fetch_rc != 0:
        return _sync_result(
            stage=stage,
            outcome=RepoRootSyncOutcome.FETCH_FAILED,
            sync_id=sync_id,
            session_id=session_id,
            failed_operation=_GIT_FETCH_ORIGIN_MAIN_ARGS[0],
            diagnostic=fetch_stderr,
        )

    counts_rc, counts_stdout, counts_stderr = _run_git(list(_GIT_REV_LIST_COUNTS_ARGS), cwd=cwd)
    try:
        ahead_count, behind_count = (int(value) for value in counts_stdout.split())
    except ValueError:
        ahead_count = 0
        behind_count = 0
        counts_rc = 1
    if counts_rc != 0:
        return _sync_result(
            stage=stage,
            outcome=RepoRootSyncOutcome.GRAPH_INSPECTION_FAILED,
            sync_id=sync_id,
            session_id=session_id,
            failed_operation=_GIT_REV_LIST_COUNTS_ARGS[0],
            diagnostic=counts_stderr,
        )

    incoming_rc, incoming_stdout, incoming_stderr = _run_git(list(_GIT_INCOMING_PATHS_ARGS), cwd=cwd)
    dirty_rc, dirty_stdout, dirty_stderr = _run_git(list(_GIT_DIRTY_PATHS_ARGS), cwd=cwd)
    if incoming_rc != 0:
        return _sync_result(
            stage=stage,
            outcome=RepoRootSyncOutcome.GRAPH_INSPECTION_FAILED,
            sync_id=sync_id,
            session_id=session_id,
            ahead_count=ahead_count,
            behind_count=behind_count,
            failed_operation=_GIT_INCOMING_PATHS_ARGS[0],
            diagnostic=incoming_stderr,
        )
    if dirty_rc != 0:
        return _sync_result(
            stage=stage,
            outcome=RepoRootSyncOutcome.DIRTY_STATE_INSPECTION_FAILED,
            sync_id=sync_id,
            session_id=session_id,
            ahead_count=ahead_count,
            behind_count=behind_count,
            failed_operation=_GIT_DIRTY_PATHS_ARGS[0],
            diagnostic=dirty_stderr,
        )

    incoming_paths = _parse_nul_paths(incoming_stdout)
    dirty_paths = _parse_dirty_paths(dirty_stdout)
    dirty_overlap_paths = tuple(sorted(set(incoming_paths) & set(dirty_paths)))
    if behind_count == 0:
        outcome = RepoRootSyncOutcome.AHEAD_ONLY if ahead_count else RepoRootSyncOutcome.EQUAL
        return _sync_result(
            stage=stage,
            outcome=outcome,
            sync_id=sync_id,
            session_id=session_id,
            ahead_count=ahead_count,
            behind_count=behind_count,
            incoming_paths=incoming_paths,
            dirty_paths=dirty_paths,
            dirty_overlap_paths=dirty_overlap_paths,
        )
    if ahead_count:
        return _sync_result(
            stage=stage,
            outcome=RepoRootSyncOutcome.SPLIT_HISTORY,
            sync_id=sync_id,
            session_id=session_id,
            ahead_count=ahead_count,
            behind_count=behind_count,
            incoming_paths=incoming_paths,
            dirty_paths=dirty_paths,
            dirty_overlap_paths=dirty_overlap_paths,
        )
    if dirty_overlap_paths:
        return _sync_result(
            stage=stage,
            outcome=RepoRootSyncOutcome.DIRTY_OVERLAP,
            sync_id=sync_id,
            session_id=session_id,
            ahead_count=ahead_count,
            behind_count=behind_count,
            incoming_paths=incoming_paths,
            dirty_paths=dirty_paths,
            dirty_overlap_paths=dirty_overlap_paths,
        )

    fast_forward_rc, _, fast_forward_stderr = _run_git(list(_GIT_FAST_FORWARD_ARGS), cwd=cwd, env=env)
    outcome = RepoRootSyncOutcome.FAST_FORWARDED if fast_forward_rc == 0 else RepoRootSyncOutcome.FAST_FORWARD_FAILED
    return _sync_result(
        stage=stage,
        outcome=outcome,
        sync_id=sync_id,
        session_id=session_id,
        ahead_count=ahead_count,
        behind_count=behind_count,
        incoming_paths=incoming_paths,
        dirty_paths=dirty_paths,
        dirty_overlap_paths=dirty_overlap_paths,
        failed_operation=None if fast_forward_rc == 0 else _GIT_FAST_FORWARD_ARGS[0],
        diagnostic=fast_forward_stderr,
    )


def _mark_repo_root_sync_failure(
    result: RepoRootSyncResult,
    *,
    outcome: RepoRootSyncOutcome,
    failed_operation: str,
    diagnostic: str,
) -> RepoRootSyncResult:
    """Record a later Git-boundary failure against an existing sync assessment."""
    return _sync_result(
        stage=result.stage,
        outcome=outcome,
        sync_id=result.sync_id,
        session_id=result.session_id,
        ahead_count=result.ahead_count,
        behind_count=result.behind_count,
        incoming_paths=result.incoming_paths,
        dirty_paths=result.dirty_paths,
        dirty_overlap_paths=result.dirty_overlap_paths,
        failed_operation=failed_operation,
        diagnostic=diagnostic,
    )


def _ensure_integration_worktree(cwd: str) -> tuple[Path, str]:
    """Ensure persistent integration worktree exists and is synced to origin/main.

    Returns (worktree_path, error_message). Error is empty on success.
    Fresh dequeues resync before pinning the squash base; mid-merge re-entry
    routes through awaiting-commit and does not call this function.
    """
    integration_wt = _integration_worktree_path(cwd)

    if not integration_wt.exists():
        rc, _, stderr = _run_git(["fetch", "origin", "main"], cwd=cwd)
        if rc != 0:
            return integration_wt, f"git fetch origin main failed:\n{stderr.strip()}"
        rc, _, stderr = _run_git(["worktree", "add", str(integration_wt), "origin/main", "--detach"], cwd=cwd)
        if rc != 0:
            return integration_wt, f"git worktree add (integration) failed:\n{stderr.strip()}"

    wt = str(integration_wt)
    rc, _, stderr = _run_git(["fetch", "origin"], cwd=wt)
    if rc != 0:
        return integration_wt, f"git fetch origin failed in integration worktree:\n{stderr.strip()}"
    rc, _, stderr = _run_git(["reset", "--hard", "origin/main"], cwd=wt)
    if rc != 0:
        return integration_wt, f"git reset to origin/main failed in integration worktree:\n{stderr.strip()}"

    return integration_wt, ""


def _run_git(
    args: list[str],
    *,
    cwd: str,
    timeout: float = 30,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a git command via GitPython; return (returncode, stdout, stderr)."""
    try:
        repo = Repo(cwd, search_parent_directories=True)
        execute = cast(Callable[..., object], repo.git.execute)
        if env is None:
            stdout = str(execute([GIT_EXECUTABLE, *args]))
        else:
            stdout = str(execute([GIT_EXECUTABLE, *args], env=dict(env)))
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
