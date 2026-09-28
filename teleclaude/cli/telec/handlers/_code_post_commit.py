"""Typed ingress for the repository post-commit hook."""

from __future__ import annotations

import sys

from teleclaude.core.integration.post_commit_maintenance import (
    record_activation,
    resolve_post_commit_activation_range,
    start_drain_contender,
)
from teleclaude.project_root import resolve_invocation_roots

_POST_COMMIT_USAGE = "Usage: telec code post-commit"


def handle_code_post_commit(args: list[str]) -> None:
    """Execute the just-recorded canonical-root commit range."""
    if args:
        print(_POST_COMMIT_USAGE, file=sys.stderr)
        raise SystemExit(2)
    roots = resolve_invocation_roots()
    checkout_root = roots.repository_root
    canonical_root = roots.require_project_root()
    activation_range = resolve_post_commit_activation_range(checkout_root)
    maintenance_root = checkout_root if checkout_root != canonical_root else canonical_root
    if record_activation(maintenance_root, activation_range):
        start_drain_contender(canonical_root)
