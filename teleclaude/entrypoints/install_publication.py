"""Publish the installed checkout's committed documentation and artifacts."""

from __future__ import annotations

import sys
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.logging_config import setup_logging
from teleclaude.sync import (
    HomePublicationOutcome,
    PublicationMode,
    PublicationSource,
    publish_homes,
)

logger = get_logger("teleclaude.entrypoints.install_publication")

_ROOT_RELATIVE_PATH = Path(".")
_PUBLISHED_HOME_LINE = "{home}: published"
_UNCHANGED_HOME_LINE = "{home}: unchanged"
_SKIPPED_HOME_LINE = "{home}: skipped ({error})"
_FAILED_HOME_LINE = "{home}: failed ({error})"
_PUBLICATION_FAILED = "Installed checkout publication failed: {error}"
_INSTALL_PUBLICATION_FINISHED_EVENT = "install_publication_finished"
_FAILED_EXIT_CODE = 1
_SUCCEEDED_EXIT_CODE = 0
_OUTCOME_LINES = {
    HomePublicationOutcome.PUBLISHED: _PUBLISHED_HOME_LINE,
    HomePublicationOutcome.UNCHANGED: _UNCHANGED_HOME_LINE,
    HomePublicationOutcome.SKIPPED: _SKIPPED_HOME_LINE,
    HomePublicationOutcome.FAILED: _FAILED_HOME_LINE,
}


def run_install_publication(project_root: Path) -> int:
    """Publish the installed checkout's home and report every home outcome."""
    run = publish_homes(
        project_root,
        PublicationMode.OWED,
        directory=_ROOT_RELATIVE_PATH,
        required_home=_ROOT_RELATIVE_PATH,
        source=PublicationSource.INSTALLED_COMMIT,
    )
    for result in run.homes:
        message = _OUTCOME_LINES[result.outcome]
        if result.outcome in (HomePublicationOutcome.SKIPPED, HomePublicationOutcome.FAILED):
            message = message.format(home=result.home.root.as_posix(), error=result.error)
        else:
            message = message.format(home=result.home.root.as_posix())
        print(message)
    if run.error is not None:
        print(_PUBLICATION_FAILED.format(error=run.error), file=sys.stderr)

    exit_code = _FAILED_EXIT_CODE if run.exit_code else _SUCCEEDED_EXIT_CODE
    outcomes = {outcome.value: sum(item.outcome is outcome for item in run.homes) for outcome in HomePublicationOutcome}
    logger.info(
        _INSTALL_PUBLICATION_FINISHED_EVENT,
        exit_code=exit_code,
        tip=run.tip,
        outcomes=outcomes,
        error=run.error,
    )
    return exit_code


def main() -> int:
    """Run install-time publication for the current checkout."""
    setup_logging()
    return run_install_publication(Path.cwd().resolve())


if __name__ == "__main__":
    sys.exit(main())
