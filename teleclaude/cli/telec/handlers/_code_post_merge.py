"""Typed ingress for the repository post-merge hook."""

from __future__ import annotations

import sys

from teleclaude.core.integration.post_commit_maintenance import (
    record_activation,
    resolve_post_merge_activation_range,
    start_drain_contender,
)
from teleclaude.project_root import resolve_invocation_roots, resolve_project_root

_POST_MERGE_USAGE = "Usage: telec code post-merge"
_MAINTENANCE_STARTED_NOTICE = (
    "Automatic maintenance started in the background; it may take a while. No need to run make install."
)


def handle_code_post_merge(args: list[str]) -> None:
    """Execute automation for the canonical-root range activated by a merge."""
    if args:
        print(_POST_MERGE_USAGE, file=sys.stderr)
        raise SystemExit(2)
    checkout_root = resolve_invocation_roots().repository_root
    activation_range = resolve_post_merge_activation_range(checkout_root)
    if record_activation(checkout_root, activation_range):
        canonical_root = resolve_project_root(checkout_root)
        if start_drain_contender(canonical_root):
            print(_MAINTENANCE_STARTED_NOTICE, file=sys.stderr)
