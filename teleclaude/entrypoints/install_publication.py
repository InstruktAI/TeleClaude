"""Publish an installed release's committed documentation and agent artifacts."""

from __future__ import annotations

import argparse
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
_PUBLICATION_FAILED = "Installed release publication failed: {error}"
_RELEASE_OPTION = "--release"
_INSTALL_PUBLICATION_FINISHED_EVENT = "install_publication_finished"
_FAILED_EXIT_CODE = 1
_SUCCEEDED_EXIT_CODE = 0
_OUTCOME_LINES = {
    HomePublicationOutcome.PUBLISHED: _PUBLISHED_HOME_LINE,
    HomePublicationOutcome.UNCHANGED: _UNCHANGED_HOME_LINE,
    HomePublicationOutcome.SKIPPED: _SKIPPED_HOME_LINE,
    HomePublicationOutcome.FAILED: _FAILED_HOME_LINE,
}


def run_install_publication(release_root: Path) -> int:
    """Publish the platform's published half from the installed release at ``release_root`` and report every home outcome."""
    run = publish_homes(
        release_root,
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


def main(arguments: list[str] | None = None) -> int:
    """Run install-time publication for the release named by ``--release``, never for the caller's directory."""
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_RELEASE_OPTION, type=Path, required=True)
    options = parser.parse_args(arguments)
    return run_install_publication(options.release.resolve())


if __name__ == "__main__":
    sys.exit(main())
