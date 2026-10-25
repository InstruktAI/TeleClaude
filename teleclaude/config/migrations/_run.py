"""Run registered configuration document migrations for one trigger and report each failure.

A run ends with the `ExitStatus` that names its result; a withheld run is one that stored nothing because
it would publish a version the running daemon cannot read, and it ends distinguishably from a failed one.
"""

from __future__ import annotations

import sys
from enum import IntEnum

from teleclaude.config.migrations._chain import MigrationTrigger
from teleclaude.config.migrations._records import MigrationOutcome
from teleclaude.config.migrations._runner import migrate_registered
from teleclaude.constants import API_SOCKET_PATH
from teleclaude.runtime.daemon_shutdown_control import read_migration_reach

_FAILED_MIGRATION_DIAGNOSTIC = (
    "Configuration migration failed: subject={subject_kind} source={subject_source} "
    "version={from_version}->{to_version} reason={reason}\n"
)
_FAILED_MIGRATION_DIAGNOSTIC_DETAIL = "  {diagnostic}\n"
_FAILED_RECORD_MISSING_REASON = "Failed migration record has no failure reason"
_WITHHELD_MIGRATION_DIAGNOSTIC = (
    "Configuration migration withheld: {count} document(s) stay at their stored version; {reason}\n"
)


class ExitStatus(IntEnum):
    """Exit statuses the entrypoint publishes; argparse owns the usage-error status."""

    SUCCESS = 0
    FAILED = 1
    WITHHELD = 3


def run_trigger(trigger: MigrationTrigger) -> ExitStatus:
    """Migrate the documents covered by ``trigger`` and write each failed or withheld document's diagnostic."""
    records = migrate_registered(trigger, read_migration_reach(API_SOCKET_PATH))
    for record in records:
        if record["outcome"] is not MigrationOutcome.FAILED:
            continue
        reason = record["reason"]
        if reason is None:
            raise RuntimeError(_FAILED_RECORD_MISSING_REASON)
        sys.stderr.write(
            _FAILED_MIGRATION_DIAGNOSTIC.format(
                subject_kind=record["subject_kind"],
                subject_source=record["subject_source"],
                from_version=record["from_version"],
                to_version=record["to_version"],
                reason=reason.value,
            )
        )
        if record["diagnostic"] is not None:
            sys.stderr.write(_FAILED_MIGRATION_DIAGNOSTIC_DETAIL.format(diagnostic=record["diagnostic"]))
    if any(record["outcome"] is MigrationOutcome.FAILED for record in records):
        return ExitStatus.FAILED
    withheld = [record for record in records if record["outcome"] is MigrationOutcome.WITHHELD]
    if withheld:
        sys.stderr.write(_WITHHELD_MIGRATION_DIAGNOSTIC.format(count=len(withheld), reason=withheld[0]["diagnostic"]))
        return ExitStatus.WITHHELD
    return ExitStatus.SUCCESS
