"""Execute the range-bound ``sync`` maintenance action."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import ActivationRange
from teleclaude.core.integration.post_commit_maintenance import _SYNC_ACTION_ID, activation_range_owes_action
from teleclaude.sync import PublicationOutcome, publish_recorded_commit

logger = get_logger(__name__)

_PUBLISH_RANGE_NOT_OWED = "The recorded range is not eligible for the sync maintenance action."
_PUBLISH_ACTION_FINISHED_EVENT = "recorded_publication_action_finished"
_PUBLISH_SUCCEEDED = 0
_PUBLISH_FAILED = 1


def run_sync_action(activation_range: ActivationRange, project_root: Path) -> int:
    """Publish only a literal range whose main-only maintenance owes ``sync``."""
    if not activation_range_owes_action(project_root, activation_range, _SYNC_ACTION_ID):
        print(_PUBLISH_RANGE_NOT_OWED, file=sys.stderr)
        return _PUBLISH_FAILED
    result = publish_recorded_commit(project_root, activation_range.after_sha)
    published = result.outcome in (PublicationOutcome.PUBLISHED, PublicationOutcome.SUPERSEDED)
    exit_code = _PUBLISH_SUCCEEDED if published else _PUBLISH_FAILED
    logger.info(
        _PUBLISH_ACTION_FINISHED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        action_id=_SYNC_ACTION_ID,
        exit_code=exit_code,
        outcome=result.outcome,
        reason=result.reason,
        published_generation=result.published_generation,
        unfinished_publication=result.unfinished_publication,
    )
    return exit_code


def main() -> int:
    """Run the maintenance action for the command line's working project root."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after-sha", required=True)
    parser.add_argument("--before-sha")
    args = parser.parse_args()
    activation_range = ActivationRange(before_sha=args.before_sha, after_sha=args.after_sha)
    return run_sync_action(activation_range, Path.cwd().resolve())


if __name__ == "__main__":
    raise SystemExit(main())
