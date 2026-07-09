"""Post-merge Blueprint regeneration entrypoint.

This module is automation-only. It gives the repo-root ``post-merge`` hook a
Python boundary while keeping Blueprint generation off the public ``telec``
surface.
"""

from __future__ import annotations

import os
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import ENV_ENABLE, INTEGRATOR_GITOP_ENV
from teleclaude.core.blueprint.generate import regenerate_blueprint
from teleclaude.git import GitCommandError, Repo

logger = get_logger(__name__)


def _repo_root_from_env() -> Path:
    configured = os.environ.get("GRAPHIFY_REPO_ROOT")
    return Path(configured).expanduser().resolve() if configured else Path.cwd().resolve()


def _rev_parse(repo_root: Path, rev: str) -> str | None:
    try:
        repo = Repo(repo_root, search_parent_directories=True)
        value = str(repo.git.rev_parse(rev)).strip()
        return value or None
    except GitCommandError:
        logger.debug("post-merge Blueprint hook could not resolve %s", rev, exc_info=True)
        return None


def run_post_merge_regeneration() -> int:
    """Regenerate the Blueprint after an external repo-root merge changed HEAD.

    The hook is best-effort by contract: every failure is logged and returns zero
    so the git operation that triggered it is never blocked.
    """
    if os.environ.get(INTEGRATOR_GITOP_ENV) == ENV_ENABLE:
        return 0

    try:
        repo_root = _repo_root_from_env()
        head = _rev_parse(repo_root, "HEAD")
        orig_head = _rev_parse(repo_root, "ORIG_HEAD")
        if head is None or orig_head is None or head == orig_head:
            return 0
        regenerate_blueprint(repo_root, baseline_sha=head)
    except Exception:
        logger.warning("post-merge Blueprint regeneration failed", exc_info=True)
    return 0


def main() -> int:
    """Console entrypoint for ``python -m teleclaude.core.blueprint.post_merge``."""
    return run_post_merge_regeneration()


if __name__ == "__main__":
    raise SystemExit(main())
