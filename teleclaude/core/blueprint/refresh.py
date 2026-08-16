"""Detached, single-flight Blueprint refresh dispatched from the freshness observation.

The only point in the system that observes every advance of ``origin/main``,
regardless of which path produced it, is the freshness check inside
``telec code blueprint affected``. This module gives that observation a writer:
on a stale baseline it spawns a detached child that regenerates the Blueprint, so a
direct commit pushed to main (a path no git hook covers) converges without adding a
new hook and without the ~77s extraction ever running on the agent's read path.

This is a sibling entrypoint to ``post_merge.py``, dispatched by a subprocess spawn
instead of a git hook: ``python -m teleclaude.core.blueprint.refresh``.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import ENV_ENABLE, INTEGRATOR_GITOP_ENV
from teleclaude.core.blueprint._paths import refresh_lock_path
from teleclaude.core.blueprint.generate import regenerate_blueprint
from teleclaude.core.blueprint.post_merge import _repo_root_from_env, _rev_parse
from teleclaude.project_root import is_slug_worktree, resolve_invocation_cwd, resolve_workspace_root

logger = get_logger(__name__)


def _dispatched_from_slug_worktree() -> bool:
    """Whether this invocation originates inside a todo slug worktree (trees/<slug>).

    Resolved from the invocation cwd rather than the canonical project root the
    caller already holds, since that root has already been normalized away from
    the worktree. An unresolvable cwd suppresses dispatch rather than risking a
    refresh from an indeterminate origin.
    """
    try:
        return is_slug_worktree(resolve_workspace_root(resolve_invocation_cwd()))
    except FileNotFoundError:
        return True


def _lock_is_free(lock_path: Path) -> bool:
    """Probe the refresh lock non-blockingly, releasing it immediately either way.

    An optimization only: it lets the common case skip a spawn that would
    immediately no-op. The child's own acquisition is the correctness boundary.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return True


def dispatch_refresh(repo_root: Path, *, main_sha: str | None) -> None:
    """Fire-and-forget a detached Blueprint refresh for an observed-stale baseline.

    Best-effort by contract, matching ``regenerate_blueprint``: every failure is
    logged and swallowed so the caller's fallback path always completes.
    """
    if main_sha is None:
        return
    if os.environ.get(INTEGRATOR_GITOP_ENV) == ENV_ENABLE:
        return
    if _dispatched_from_slug_worktree():
        return
    try:
        if not _lock_is_free(refresh_lock_path(repo_root)):
            return
        env = dict(os.environ)
        env["GRAPHIFY_REPO_ROOT"] = str(repo_root)
        subprocess.Popen(
            [sys.executable, "-m", "teleclaude.core.blueprint.refresh"],
            cwd=str(repo_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        logger.warning("blueprint_refresh_dispatch_failed repo_root=%s err=%s", repo_root, exc)


def main() -> int:
    """Console entrypoint for ``python -m teleclaude.core.blueprint.refresh``.

    Acquires the refresh lock non-blockingly and exits without regenerating if a
    refresh is already running — this acquisition, not the parent's probe, is the
    single-flight boundary. Resolves ``origin/main`` itself rather than trusting a
    value the parent read earlier, since it may have moved again by the time this
    process runs.
    """
    repo_root = _repo_root_from_env()
    lock_path = refresh_lock_path(repo_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return 0
    try:
        main_sha = _rev_parse(repo_root, "origin/main")
        if main_sha is not None:
            regenerate_blueprint(repo_root, baseline_sha=main_sha)
    except Exception:
        logger.warning("blueprint refresh child failed repo_root=%s", repo_root, exc_info=True)
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
