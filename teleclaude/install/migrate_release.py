"""Run one release's migrations in the install act's stopped window and report which started.

The install act stops the daemon, then runs this entrypoint with the interpreter of the release being
installed. It first records the install as owed its assessment
(``teleclaude.core.reconciliation.installation_assessment``), before any migration starts, so the obligation
outlives the restart whichever release's install act performed the install. It then runs the
ledger-recorded migrations in order — installation migrations, configuration
documents — and then opens every store the daemon opens at startup through the one opening path
(``teleclaude.core.store_opening``), whose core database initialization runs its own ledger and whose
other owners migrate when opened. Every owner signals to the install record, against this release, before
it changes anything; the entrypoint prints what the record collected for the install act.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.config.environment_renames import carry_renamed_environment
from teleclaude.config.migrations._chain import MigrationTrigger
from teleclaude.config.migrations._run import ExitStatus, run_trigger
from teleclaude.core.db import db
from teleclaude.core.migration_signal import MigrationExitCode, bind_install_target, unrecorded_signal_seen
from teleclaude.core.reconciliation.installation import InstallationLayout, MigratedState, read_record
from teleclaude.core.reconciliation.installation_assessment import update_assessment
from teleclaude.core.store_opening import open_stores
from teleclaude.core.todos_db._adapter import close_todos_db_instances
from teleclaude.deployment.migration_runner import migrate_committed_range
from teleclaude.events.db import get_event_db
from teleclaude.install.local_redis import apply_or_fall_back
from teleclaude.logging_config import setup_logging

logger = get_logger(__name__)

_TARGET_OPTION = "--target"
_PREVIOUS_OPTION = "--previous"
_REPOSITORY_OPTION = "--repository"
_MIGRATIONS_FAILED = "installation migrations failed for {target}"
_CONFIGURATION_FAILED = "configuration document migrations ended {status} for {target}"
_STORES_FAILED = "stores did not open for {target}: {projects}"
_STORES_ERROR = "opening the stores for {target} failed: {error}"
_STORES_ERROR_EVENT = "release_migration_stores_failed"
_PROJECT_SEPARATOR = ", "
_OPENED_EVENT = "release_migration_stores_opened"
_UNIT_FAILED_EVENT = "release_migration_failed"
_UNIT_FAILED = "migrating for {target} failed: {error}"
_OWE_FAILED_EVENT = "release_assessment_owe_failed"
_OWE_FAILED = "recording the owed assessment for {target} failed: {error}"


async def _open_and_close_stores(target: str) -> str | None:
    """Open every startup store, then release the connections; the failure reason, or ``None``."""
    try:
        opening = await open_stores()
    except Exception as error:  # supervision boundary: any store's failure is this entrypoint's reported failure
        logger.error(_STORES_ERROR_EVENT, target=target, exc_info=True)
        return _STORES_ERROR.format(target=target, error=error)
    try:
        if opening.failed_projects:
            return _STORES_FAILED.format(
                target=target, projects=_PROJECT_SEPARATOR.join(str(root) for root in opening.failed_projects)
            )
        logger.info(_OPENED_EVENT, target=target)
        return None
    finally:
        await close_todos_db_instances()
        await (await get_event_db()).close()
        await db.close()


def _record_owed_assessment(layout: InstallationLayout, target: str) -> str | None:
    """Record the install of ``target`` as owed its assessment; the failure reason, or ``None``."""
    try:
        update_assessment(lambda record: record.owe(target, datetime.now(UTC)), layout)
    except (OSError, ValidationError) as error:
        logger.error(_OWE_FAILED_EVENT, target=target, exc_info=True)
        return _OWE_FAILED.format(target=target, error=error)
    return None


def _migrate(repository: Path, previous: str | None, target: str) -> str | None:
    """Prepare the machine for the release, run its migrations and open its stores; the failure reason, or ``None``.

    The renamed environment names are carried and the local Redis applied before any migration starts. A local
    Redis that cannot be applied is logged and leaves local events on the cluster Redis; it never fails the install.
    """
    carry_renamed_environment()
    apply_or_fall_back()
    if migrate_committed_range(repository, previous, target) != 0:
        return _MIGRATIONS_FAILED.format(target=target)
    if previous is not None and (status := run_trigger(MigrationTrigger.INSTALL)) is not ExitStatus.SUCCESS:
        return _CONFIGURATION_FAILED.format(target=target, status=status.name.lower())
    return asyncio.run(_open_and_close_stores(target))


def _collected(layout: InstallationLayout, target: str) -> MigratedState:
    """The migrations the record holds for the install window of ``target``."""
    window = read_record(layout).installing
    return window.migrated if window is not None and window.target == target else MigratedState()


def main(arguments: list[str] | None = None) -> int:
    """Migrate for the release named by ``--target`` and print the collected start signals as JSON."""
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_TARGET_OPTION, required=True)
    parser.add_argument(_PREVIOUS_OPTION)
    parser.add_argument(_REPOSITORY_OPTION, type=Path)
    options = parser.parse_args(arguments)
    layout = InstallationLayout()
    repository: Path = options.repository or layout.repository
    target: str = options.target
    failure: str | None = None
    with bind_install_target(target):
        try:
            failure = _record_owed_assessment(layout, target) or _migrate(repository, options.previous, target)
        except Exception as error:  # supervision boundary: every failure of the unit is the entrypoint's reported one
            logger.error(_UNIT_FAILED_EVENT, target=target, exc_info=True)
            failure = _UNIT_FAILED.format(target=target, error=error)
    with suppress(OSError, ValidationError):
        print(_collected(layout, target).model_dump_json())
    if failure is not None:
        print(failure, file=sys.stderr)
    if unrecorded_signal_seen():
        return MigrationExitCode.UNACCOUNTED
    return MigrationExitCode.FAILED if failure is not None else MigrationExitCode.SUCCEEDED


if __name__ == "__main__":
    raise SystemExit(main())
