"""Typed ingress for the reference-transaction hook's remote-main advance."""

from __future__ import annotations

import re
import sys

from teleclaude.core.integration.post_commit_maintenance import (
    OwedSetRecorded,
    record_remote_main_activation,
    refusal_notice,
    start_drain_contender,
)
from teleclaude.project_root import resolve_invocation_roots, resolve_project_root

_OBJECT_ID_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_NULL_OBJECT_ID_PATTERN = re.compile(r"0{40,64}")
_ARGUMENT_COUNT = 2


def handle_code_remote_main(args: list[str]) -> None:
    """Record the maintenance one remote-main advance owes the project and start its drain."""
    if len(args) != _ARGUMENT_COUNT or not all(_OBJECT_ID_PATTERN.fullmatch(argument) for argument in args):
        print("Usage: telec repo remote-main <previous-object-id> <new-object-id>", file=sys.stderr)
        raise SystemExit(2)
    previous, new = args
    before_sha = None if _NULL_OBJECT_ID_PATTERN.fullmatch(previous) else previous
    checkout_root = resolve_invocation_roots().repository_root
    recording = record_remote_main_activation(checkout_root, before_sha, new)
    if isinstance(recording, OwedSetRecorded):
        start_drain_contender(resolve_project_root(checkout_root))
        return
    notice = refusal_notice(recording)
    if notice is not None:
        print(notice, file=sys.stderr)
