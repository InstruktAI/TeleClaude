"""Range-bound internal publication handler used by maintenance and replay."""

from __future__ import annotations

import sys

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import ActivationRange
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import CODE_PUBLISH
from teleclaude.core.integration.post_commit_maintenance import (
    _SYNC_ACTION_ID,
    activation_range_owes_action,
)
from teleclaude.project_root import resolve_git_root, resolve_invocation_cwd
from teleclaude.sync import publish_recorded_commit

logger = get_logger(__name__)

_PUBLISH_USAGE = "Usage: telec code publish --after-sha <commit> [--before-sha <commit>]"
_PUBLISH_RANGE_REQUIRED = "A literal --after-sha is required."
_PUBLISH_FLAGS_REPEATED = "Each publication range flag may appear only once."
_PUBLISH_RANGE_NOT_OWED = "The recorded range is not eligible for the sync maintenance action."
_PUBLISH_ACTION_FINISHED_EVENT = "recorded_publication_action_finished"
_PUBLISH_SUCCEEDED = 0
_PUBLISH_FAILED = 1


def handle_code_publish(args: list[str]) -> None:
    """Publish only a literal range whose main-only maintenance owes ``sync``."""
    parsed = parse_command_args(CODE_PUBLISH, args)
    before_values = parsed.values(F.FLAG_PUBLISH_BEFORE_SHA)
    after_values = parsed.values(F.FLAG_PUBLISH_AFTER_SHA)
    if parsed.positionals:
        print(_PUBLISH_USAGE, file=sys.stderr)
        raise SystemExit(2)
    if len(before_values) > 1 or len(after_values) > 1:
        print(_PUBLISH_FLAGS_REPEATED, file=sys.stderr)
        print(_PUBLISH_USAGE, file=sys.stderr)
        raise SystemExit(2)
    if not after_values:
        print(_PUBLISH_RANGE_REQUIRED, file=sys.stderr)
        print(_PUBLISH_USAGE, file=sys.stderr)
        raise SystemExit(2)
    activation_range = ActivationRange(
        before_sha=before_values[0] if before_values else None,
        after_sha=after_values[0],
    )
    project_root = resolve_git_root(resolve_invocation_cwd())
    if not activation_range_owes_action(project_root, activation_range, _SYNC_ACTION_ID):
        print(_PUBLISH_RANGE_NOT_OWED, file=sys.stderr)
        raise SystemExit(1)
    succeeded = publish_recorded_commit(project_root, activation_range.after_sha)
    logger.info(
        _PUBLISH_ACTION_FINISHED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        action_id=_SYNC_ACTION_ID,
        exit_code=_PUBLISH_SUCCEEDED if succeeded else _PUBLISH_FAILED,
    )
    if not succeeded:
        raise SystemExit(_PUBLISH_FAILED)
