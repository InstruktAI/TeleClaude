"""Run registered configuration document migrations.

A run ends with the `ExitStatus` that names its result (`teleclaude.config.migrations._run`).
"""

from __future__ import annotations

import argparse
import sys

from teleclaude.config.migrations._chain import MigrationTrigger
from teleclaude.config.migrations._run import run_trigger
from teleclaude.logging_config import setup_logging

_TRIGGERS = (MigrationTrigger.MAINTENANCE.value, MigrationTrigger.INSTALL.value)


def main() -> int:
    """Migrate the documents covered by the selected trigger."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", choices=_TRIGGERS, default=MigrationTrigger.MAINTENANCE.value)
    arguments = parser.parse_args()
    setup_logging()
    return run_trigger(MigrationTrigger(arguments.trigger))


if __name__ == "__main__":
    sys.exit(main())
