"""Post-merge Blueprint regeneration entrypoint.

This module is automation-only. It gives the repo-root ``post-merge`` hook a
Python boundary while keeping Blueprint generation off the public ``telec``
surface.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.capabilities import resolve_capabilities
from teleclaude.constants import ENV_ENABLE, INTEGRATOR_GITOP_ENV
from teleclaude.core.blueprint._paths import manifest_path
from teleclaude.core.blueprint.generate import blueprint_generation_lock, regenerate_blueprint
from teleclaude.core.blueprint.manifest import BlueprintStatus, read_manifest
from teleclaude.git import GitCommandError, Repo, hook_free_environment
from teleclaude.logging_config import setup_logging
from teleclaude.project_root import is_slug_worktree

logger = get_logger(__name__)

_GRAPHIFY_REPO_ROOT_ENV = "GRAPHIFY_REPO_ROOT"
_POST_MERGE_MODULE_FLAG = "-m"
_POST_MERGE_MODULE = "teleclaude.core.blueprint.post_merge"
_POST_MERGE_DISPATCH_EVENT = "blueprint_post_merge_dispatched"
_POST_MERGE_DISPATCH_FAILED_MESSAGE = "post-merge Blueprint dispatch failed: %s"
_POST_MERGE_GENERATION_FAILED_MESSAGE = "post-merge Blueprint generation failed"
_HEAD_REFERENCE = "HEAD"


def resolve_post_merge_root(fallback_root: Path | None = None) -> Path:
    """Resolve the post-merge automation root, preserving the explicit override."""
    configured = os.environ.get("GRAPHIFY_REPO_ROOT")  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal
    if configured:
        return Path(configured).expanduser().resolve()
    return fallback_root.resolve() if fallback_root is not None else Path.cwd().resolve()


def _rev_parse(repo_root: Path, rev: str) -> str | None:
    try:
        repo = Repo(repo_root, search_parent_directories=True)
        value = str(repo.git.rev_parse(rev)).strip()
        return value or None
    except GitCommandError:
        logger.debug("post-merge Blueprint hook could not resolve %s", rev, exc_info=True)
        return None


def run_post_merge_regeneration(repo_root: Path | None = None) -> int:
    """Regenerate the Blueprint after an external repo-root merge changed HEAD.

    The hook is best-effort by contract: every failure is logged and returns zero
    so the git operation that triggered it is never blocked.
    """
    if os.environ.get(INTEGRATOR_GITOP_ENV) == ENV_ENABLE:  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal
        return 0

    try:
        resolved_root = resolve_post_merge_root(repo_root)
        if is_slug_worktree(resolved_root) or not resolve_capabilities(resolved_root).code:
            return 0
        head = _rev_parse(resolved_root, "HEAD")
        orig_head = _rev_parse(resolved_root, "ORIG_HEAD")
        if head is None or orig_head is None or head == orig_head:
            return 0
        env = hook_free_environment(resolved_root)
        env[_GRAPHIFY_REPO_ROOT_ENV] = str(resolved_root)
        # A detached process is required to keep graph extraction off the Git hook's lifetime.
        subprocess.Popen(
            [sys.executable, _POST_MERGE_MODULE_FLAG, _POST_MERGE_MODULE],
            cwd=str(resolved_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info(_POST_MERGE_DISPATCH_EVENT, repo_root=str(resolved_root), baseline_sha=head)
    except OSError as exc:
        logger.warning(_POST_MERGE_DISPATCH_FAILED_MESSAGE, exc)
    except Exception:
        logger.warning(_POST_MERGE_GENERATION_FAILED_MESSAGE, exc_info=True)
    return 0


def main() -> int:
    """Console entrypoint for ``python -m teleclaude.core.blueprint.post_merge``."""
    setup_logging()
    resolved_root = resolve_post_merge_root()
    try:
        with blueprint_generation_lock(resolved_root, wait=True):
            head = _rev_parse(resolved_root, _HEAD_REFERENCE)
            if head is None:
                return 0
            manifest = read_manifest(manifest_path(resolved_root))
            if manifest is not None and manifest.status is BlueprintStatus.OK and manifest.baseline_sha == head:
                return 0
            regenerate_blueprint(resolved_root, baseline_sha=head)
    except Exception:
        logger.warning(_POST_MERGE_GENERATION_FAILED_MESSAGE, exc_info=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
