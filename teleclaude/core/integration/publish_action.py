"""Execute the range-bound ``sync`` maintenance action."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import ActivationRange
from teleclaude.core.integration.post_commit_maintenance import (
    _SYNC_ACTION_ID,
    activation_range_action_paths,
)
from teleclaude.sync import HomePublicationOutcome, PublicationMode, publish_homes

logger = get_logger(__name__)

_PUBLISH_RANGE_NOT_OWED = "The recorded range is not eligible for the sync maintenance action."
_PUBLISH_ACTION_FINISHED_EVENT = "recorded_publication_action_finished"
_PUBLISH_SUCCEEDED = 0
_PUBLISH_FAILED = 1


def run_sync_action(activation_range: ActivationRange, project_root: Path) -> int:
    """Publish only a literal range whose main-only maintenance owes ``sync``."""
    changed_paths = activation_range_action_paths(project_root, activation_range, _SYNC_ACTION_ID)
    if changed_paths is None:
        print(_PUBLISH_RANGE_NOT_OWED, file=sys.stderr)
        return _PUBLISH_FAILED
    run = publish_homes(project_root, PublicationMode.OWED, changed_paths=list(changed_paths))
    exit_code = _PUBLISH_FAILED if run.exit_code else _PUBLISH_SUCCEEDED
    outcomes = {outcome.value: sum(item.outcome is outcome for item in run.homes) for outcome in HomePublicationOutcome}
    logger.info(
        _PUBLISH_ACTION_FINISHED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        action_id=_SYNC_ACTION_ID,
        exit_code=exit_code,
        tip=run.tip,
        outcomes=outcomes,
        error=run.error,
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
