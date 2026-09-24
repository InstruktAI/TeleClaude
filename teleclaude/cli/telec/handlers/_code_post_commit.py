"""Typed ingress for the repository post-commit hook."""

from __future__ import annotations

import sys

from teleclaude.core.integration.post_commit_maintenance import (
    resolve_post_commit_activation_range,
    run_post_commit_maintenance,
)
from teleclaude.git import Repo
from teleclaude.project_root import resolve_git_root, resolve_invocation_cwd, resolve_project_root

_POST_COMMIT_USAGE = "Usage: telec code post-commit"


def handle_code_post_commit(args: list[str]) -> None:
    """Execute the just-recorded canonical-root commit range."""
    if args:
        print(_POST_COMMIT_USAGE, file=sys.stderr)
        raise SystemExit(2)
    checkout_root = resolve_git_root(resolve_invocation_cwd())
    canonical_root = resolve_project_root(checkout_root)
    activation_range = resolve_post_commit_activation_range(checkout_root)
    if checkout_root != canonical_root:
        run_post_commit_maintenance(checkout_root, activation_range)
        return
    _ = Repo(str(canonical_root))
    run_post_commit_maintenance(canonical_root, activation_range)
