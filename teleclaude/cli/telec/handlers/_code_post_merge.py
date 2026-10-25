"""Typed ingress for the repository post-merge hook."""

from __future__ import annotations

import sys

from teleclaude.cli.telec.surface_types import TelecCommand
from teleclaude.core.integration.activation_registration import resolve_post_merge_activation_range
from teleclaude.core.integration.post_commit_maintenance import (
    OwedSetRecorded,
    record_activation,
    refusal_notice,
    start_drain_contender,
)
from teleclaude.project_root import resolve_invocation_roots, resolve_project_root

_POST_MERGE_USAGE = "Usage: telec {family} post-merge"
_MAINTENANCE_STARTED_NOTICE = (
    "Automatic maintenance started in the background; it may take a while. No need to run make install."
)


def handle_code_post_merge(args: list[str], family: TelecCommand) -> None:
    """Execute automation for the canonical-root range activated by a merge.

    ``family`` is the command family the caller invoked; it names the usage line.
    """
    if args:
        print(_POST_MERGE_USAGE.format(family=family.value), file=sys.stderr)
        raise SystemExit(2)
    checkout_root = resolve_invocation_roots().repository_root
    activation_range = resolve_post_merge_activation_range(checkout_root)
    recording = record_activation(checkout_root, activation_range)
    if isinstance(recording, OwedSetRecorded):
        canonical_root = resolve_project_root(checkout_root)
        if start_drain_contender(canonical_root):
            print(_MAINTENANCE_STARTED_NOTICE, file=sys.stderr)
        return
    notice = refusal_notice(recording)
    if notice is not None:
        print(notice, file=sys.stderr)
