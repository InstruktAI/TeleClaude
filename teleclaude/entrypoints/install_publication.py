"""Publish an installed release's committed documentation and agent artifacts where no platform checkout does.

A machine with a registered checkout of the platform's own project receives its documentation and agent
artifacts from that checkout's commits, so an install publishes none of them over it. A machine without
one receives them from the release it installs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.logging_config import setup_logging
from teleclaude.services.project_catalog.service import get_project_catalog_service
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
_INSTALL_PUBLICATION_DEFERRED_EVENT = "install_publication_deferred"
_CHECKOUT_PUBLISHES_LINE = (
    "{root}: the registered platform checkout publishes the platform's documentation and agent artifacts"
)
_FAILED_EXIT_CODE = 1
_SUCCEEDED_EXIT_CODE = 0
_OUTCOME_LINES = {
    HomePublicationOutcome.PUBLISHED: _PUBLISHED_HOME_LINE,
    HomePublicationOutcome.UNCHANGED: _UNCHANGED_HOME_LINE,
    HomePublicationOutcome.SKIPPED: _SKIPPED_HOME_LINE,
    HomePublicationOutcome.FAILED: _FAILED_HOME_LINE,
}


def run_install_publication(release_root: Path) -> int:
    """Publish the platform's published half from the installed release at ``release_root`` and report every home outcome.

    Where a registered platform checkout publishes the platform's documentation and agent artifacts,
    nothing is owed: the install succeeds without publishing them over that checkout's.
    """
    checkout = get_project_catalog_service().get_platform_project()
    if checkout is not None:
        print(_CHECKOUT_PUBLISHES_LINE.format(root=checkout.root.as_posix()))
        logger.info(_INSTALL_PUBLICATION_DEFERRED_EVENT, checkout=checkout.root.as_posix())
        return _SUCCEEDED_EXIT_CODE
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
