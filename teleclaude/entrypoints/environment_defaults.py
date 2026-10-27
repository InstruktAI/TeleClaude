"""Create the platform home's machine environment file with local defaults when it is absent."""

from __future__ import annotations

import sys

from instrukt_ai_logging import get_logger

from teleclaude.config._defaults import _DEFAULT_LOCAL_REDIS_URL, _DEFAULT_REDIS_URL
from teleclaude.config._environment import write_environment_values
from teleclaude.logging_config import setup_logging
from teleclaude.paths import ENV_PATH

logger = get_logger("teleclaude.entrypoints.environment_defaults")

_REDIS_CLUSTER_URL_VARIABLE = "REDIS_CLUSTER_URL"
_REDIS_LOCAL_URL_VARIABLE = "REDIS_LOCAL_URL"
_ENVIRONMENT_DEFAULTS_FINISHED = "installation_environment_defaults_finished"


def ensure_environment_defaults() -> bool:
    """Create local Redis defaults without changing an existing environment file."""
    created = write_environment_values(
        ENV_PATH,
        {_REDIS_CLUSTER_URL_VARIABLE: _DEFAULT_REDIS_URL, _REDIS_LOCAL_URL_VARIABLE: _DEFAULT_LOCAL_REDIS_URL},
        only_if_missing=True,
    )
    logger.info(_ENVIRONMENT_DEFAULTS_FINISHED, path=str(ENV_PATH), created=created)
    return created


def main() -> int:
    """Run the installation environment-default operation."""
    setup_logging()
    ensure_environment_defaults()
    return 0


if __name__ == "__main__":
    sys.exit(main())
