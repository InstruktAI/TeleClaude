"""Typed ingress for the repository post-commit hook."""

from __future__ import annotations

import sys

from teleclaude.core.integration.post_commit_maintenance import run_post_commit_maintenance
from teleclaude.git import Repo
from teleclaude.project_root import resolve_git_root, resolve_invocation_cwd, resolve_project_root

_GIT_PARENT_TO_HEAD_RANGE = "HEAD^..HEAD"
_POST_COMMIT_USAGE = "Usage: telec code post-commit"


def handle_code_post_commit(args: list[str]) -> None:
    """Execute the just-recorded canonical-root commit range."""
    if args:
        print(_POST_COMMIT_USAGE, file=sys.stderr)
        raise SystemExit(2)
    checkout_root = resolve_git_root(resolve_invocation_cwd())
    canonical_root = resolve_project_root(checkout_root)
    if checkout_root != canonical_root:
        run_post_commit_maintenance(checkout_root, _GIT_PARENT_TO_HEAD_RANGE)
        return
    _ = Repo(str(canonical_root))
    run_post_commit_maintenance(canonical_root, _GIT_PARENT_TO_HEAD_RANGE)
