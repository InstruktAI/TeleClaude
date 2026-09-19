"""Typed ingress for the repository post-merge hook."""

from __future__ import annotations

import sys

from teleclaude.core.blueprint.post_merge import run_post_merge_regeneration
from teleclaude.core.integration.post_commit_maintenance import run_post_commit_maintenance
from teleclaude.project_root import resolve_git_root, resolve_invocation_cwd, resolve_project_root

_GIT_PRE_MERGE_TO_HEAD_RANGE = "ORIG_HEAD..HEAD"
_POST_MERGE_USAGE = "Usage: telec code post-merge"


def handle_code_post_merge(args: list[str]) -> None:
    """Execute automation for the canonical-root range activated by a merge."""
    if args:
        print(_POST_MERGE_USAGE, file=sys.stderr)
        raise SystemExit(2)
    checkout_root = resolve_git_root(resolve_invocation_cwd())
    canonical_root = resolve_project_root(checkout_root)
    run_post_merge_regeneration(checkout_root)
    maintenance_root = checkout_root if checkout_root != canonical_root else canonical_root
    run_post_commit_maintenance(maintenance_root, _GIT_PRE_MERGE_TO_HEAD_RANGE)
