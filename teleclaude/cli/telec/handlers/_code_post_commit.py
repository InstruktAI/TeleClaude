"""Typed ingress for the repository post-commit hook."""

from __future__ import annotations

import sys

from teleclaude.cli.telec.surface_types import TelecCommand
from teleclaude.core.integration.activation_registration import resolve_post_commit_activation_range
from teleclaude.core.integration.post_commit_maintenance import (
    OwedSetRecorded,
    record_activation,
    refusal_notice,
    start_drain_contender,
)
from teleclaude.project_root import resolve_invocation_roots

_POST_COMMIT_USAGE = "Usage: telec {family} post-commit"


def handle_code_post_commit(args: list[str], family: TelecCommand) -> None:
    """Execute the just-recorded canonical-root commit range.

    ``family`` is the command family the caller invoked; it names the usage line.
    """
    if args:
        print(_POST_COMMIT_USAGE.format(family=family.value), file=sys.stderr)
        raise SystemExit(2)
    roots = resolve_invocation_roots()
    checkout_root = roots.repository_root
    canonical_root = roots.require_commit_boundary_root()
    activation_range = resolve_post_commit_activation_range(checkout_root)
    maintenance_root = checkout_root if checkout_root != canonical_root else canonical_root
    recording = record_activation(maintenance_root, activation_range)
    if isinstance(recording, OwedSetRecorded):
        start_drain_contender(canonical_root)
        return
    notice = refusal_notice(recording)
    if notice is not None:
        print(notice, file=sys.stderr)
