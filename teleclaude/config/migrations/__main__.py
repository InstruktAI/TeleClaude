"""Run registered configuration document migrations."""

from __future__ import annotations

import argparse
import sys

from teleclaude.config.migrations._chain import MigrationTrigger
from teleclaude.config.migrations._records import MigrationOutcome
from teleclaude.config.migrations._runner import migrate_registered

_TRIGGERS = (MigrationTrigger.MAINTENANCE.value, MigrationTrigger.INSTALL.value)
_FAILED_MIGRATION_DIAGNOSTIC = (
    "Configuration migration failed: subject={subject_kind} source={subject_source} "
    "version={from_version}->{to_version} reason={reason}\n"
)
_FAILED_MIGRATION_DIAGNOSTIC_DETAIL = "  {diagnostic}\n"
_FAILED_RECORD_MISSING_REASON = "Failed migration record has no failure reason"


def main() -> int:
    """Migrate the documents covered by the selected trigger."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", choices=_TRIGGERS, default=MigrationTrigger.MAINTENANCE.value)
    arguments = parser.parse_args()
    records = migrate_registered(MigrationTrigger(arguments.trigger))
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
    return int(any(record["outcome"] is MigrationOutcome.FAILED for record in records))


if __name__ == "__main__":
    sys.exit(main())
