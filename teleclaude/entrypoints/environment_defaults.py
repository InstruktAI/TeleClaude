"""Create the platform home's machine environment file with local defaults when it is absent."""

from __future__ import annotations

import sys

from instrukt_ai_logging import get_logger

from teleclaude.config._defaults import _DEFAULT_REDIS_URL
from teleclaude.config._environment import read_environment_file, write_environment_values
from teleclaude.logging_config import setup_logging
from teleclaude.paths import ENV_PATH

logger = get_logger("teleclaude.entrypoints.environment_defaults")

_REDIS_CLUSTER_URL_VARIABLE = "REDIS_CLUSTER_URL"
# The cluster Redis variables carry the values the earlier names held, so an existing environment keeps its endpoint.
_EARLIER_REDIS_NAMES: dict[str, str] = {
    "REDIS_URL": _REDIS_CLUSTER_URL_VARIABLE,
    "REDIS_PASSWORD": "REDIS_CLUSTER_PASSWORD",
}
_CLUSTER_NAMES_CARRIED = "installation_environment_cluster_redis_names_carried"
_ENVIRONMENT_DEFAULTS_FINISHED = "installation_environment_defaults_finished"


def ensure_environment_defaults() -> bool:
    """Create local Redis defaults without changing an existing environment file."""
    created = write_environment_values(
        ENV_PATH,
        {_REDIS_CLUSTER_URL_VARIABLE: _DEFAULT_REDIS_URL},
        only_if_missing=True,
    )
    _carry_cluster_redis_names()
    logger.info(_ENVIRONMENT_DEFAULTS_FINISHED, path=str(ENV_PATH), created=created)
    return created


def _carry_cluster_redis_names() -> None:
    """Give each cluster Redis variable the value its earlier name holds, where it has none of its own."""
    environment = read_environment_file(ENV_PATH, interpolate=False)
    carried = {
        current: environment[earlier]
        for earlier, current in _EARLIER_REDIS_NAMES.items()
        if earlier in environment and current not in environment
    }
    if carried:
        write_environment_values(ENV_PATH, carried)
        logger.info(_CLUSTER_NAMES_CARRIED, names=sorted(carried))


def main() -> int:
    """Run the installation environment-default operation."""
    setup_logging()
    ensure_environment_defaults()
    return 0


if __name__ == "__main__":
    sys.exit(main())
