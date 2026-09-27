"""Run registered configuration document migrations."""

from __future__ import annotations

import argparse
import sys

from teleclaude.config.migrations._chain import MigrationTrigger
from teleclaude.config.migrations._runner import MigrationOutcome, migrate_registered

_TRIGGERS = (MigrationTrigger.MAINTENANCE.value, MigrationTrigger.INSTALL.value)


def main() -> int:
    """Migrate the documents covered by the selected trigger."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", choices=_TRIGGERS, default=MigrationTrigger.MAINTENANCE.value)
    arguments = parser.parse_args()
    records = migrate_registered(MigrationTrigger(arguments.trigger))
    return int(any(record["outcome"] is MigrationOutcome.FAILED for record in records))


if __name__ == "__main__":
    sys.exit(main())
