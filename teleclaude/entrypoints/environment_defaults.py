"""Create the checkout environment file with local defaults when it is absent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config._defaults import _DEFAULT_REDIS_URL
from teleclaude.config._environment import write_environment_values
from teleclaude.logging_config import setup_logging
from teleclaude.paths import REPO_ROOT, ConfigFileName

logger = get_logger("teleclaude.entrypoints.environment_defaults")

_REDIS_URL_VARIABLE = "REDIS_URL"
_ENVIRONMENT_DEFAULTS_FINISHED = "installation_environment_defaults_finished"
_ROOT_OPTION = "--root"


def ensure_environment_defaults(project_root: Path = REPO_ROOT) -> bool:
    """Create local Redis defaults without changing an existing environment file."""
    environment_path = project_root.expanduser().resolve() / ConfigFileName.ENV
    created = write_environment_values(
        environment_path,
        {_REDIS_URL_VARIABLE: _DEFAULT_REDIS_URL},
        only_if_missing=True,
    )
    logger.info(_ENVIRONMENT_DEFAULTS_FINISHED, path=str(environment_path), created=created)
    return created


def main() -> int:
    """Run the installation environment-default operation."""
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument(_ROOT_OPTION, type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    ensure_environment_defaults(args.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
