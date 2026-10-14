"""Execute the ``sync`` maintenance action: publish a recorded range, or rebuild the invocation home."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import ActivationRange
from teleclaude.core.integration.activation_registration import _SYNC_ACTION_ID
from teleclaude.core.integration.post_commit_maintenance import activation_range_action_paths
from teleclaude.logging_config import setup_logging
from teleclaude.quality.scope import resolve_dirty_paths
from teleclaude.sync import HomePublicationOutcome, PublicationMode, PublicationRunFailure, publish_homes

logger = get_logger(__name__)

_PUBLISH_RANGE_NOT_OWED = "The recorded range is not eligible for the sync maintenance action."
_PUBLISH_ACTION_FINISHED_EVENT = "recorded_publication_action_finished"
_HOME_FLAG = "--home"
_PUBLISH_SUCCEEDED = 0
_PUBLISH_FAILED = 1
_PUBLISH_HOME_FINISHED_EVENT = "on_demand_publication_action_finished"
_PUBLISH_HOME_NOT_COMMITTED = "The invocation home is not present in the committed main tip: {directory}"
_PUBLISH_RUN_FAILED = "telec sync failed: {error}"
_UNCOMMITTED_HOME_NOTICE = "Uncommitted changes under the invocation home were not published."
_OUTCOME_LINES = {
    HomePublicationOutcome.PUBLISHED: "{home}: published",
    HomePublicationOutcome.UNCHANGED: "{home}: unchanged",
    HomePublicationOutcome.SKIPPED: "{home}: skipped ({error})",
    HomePublicationOutcome.FAILED: "{home}: failed ({error})",
}
_DIAGNOSTIC_ERROR_LINE = "  {cause}"


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


def run_home_sync_action(home: Path, project_root: Path) -> int:
    """Rebuild the invocation home and the homes nested beneath it from the committed main tip.

    ``home`` is the invocation home's path within the repository. Uncommitted edits are
    never published; the output names the ones under the home so they are not mistaken
    for published.
    """
    if any(Path(dirty.path).is_relative_to(home) for dirty in resolve_dirty_paths(project_root)):
        print(_UNCOMMITTED_HOME_NOTICE)
    run = publish_homes(project_root, PublicationMode.REBUILD, directory=home, required_home=home)
    exit_code = _PUBLISH_SUCCEEDED
    if run.failure is PublicationRunFailure.HOME_NOT_COMMITTED:
        print(_PUBLISH_HOME_NOT_COMMITTED.format(directory=project_root / home), file=sys.stderr)
        exit_code = _PUBLISH_FAILED
    elif run.error is not None:
        print(_PUBLISH_RUN_FAILED.format(error=run.error), file=sys.stderr)
        exit_code = _PUBLISH_FAILED
    else:
        for result in run.homes:
            print(_OUTCOME_LINES[result.outcome].format(home=result.home.root.as_posix(), error=result.error))
            if result.diagnostic_error is not None:
                print(_DIAGNOSTIC_ERROR_LINE.format(cause=result.diagnostic_error))
        if run.exit_code:
            exit_code = _PUBLISH_FAILED
    logger.info(
        _PUBLISH_HOME_FINISHED_EVENT,
        action_id=_SYNC_ACTION_ID,
        exit_code=exit_code,
        tip=run.tip,
        home=home.as_posix(),
        error=run.error,
    )
    return exit_code


def main() -> int:
    """Run the maintenance action for the command line's working project root."""
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after-sha", required=True)
    parser.add_argument("--before-sha")
    parser.add_argument(_HOME_FLAG)
    args = parser.parse_args()
    project_root = Path.cwd().resolve()
    if args.home is not None:
        return run_home_sync_action(Path(args.home), project_root)
    activation_range = ActivationRange(before_sha=args.before_sha, after_sha=args.after_sha)
    return run_sync_action(activation_range, project_root)


if __name__ == "__main__":
    raise SystemExit(main())
