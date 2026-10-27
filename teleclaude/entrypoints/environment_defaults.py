"""Create the platform home's machine environment file with local defaults when it is absent."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.config._defaults import _DEFAULT_REDIS_URL
from teleclaude.config._environment import write_environment_values
from teleclaude.config.environment_renames import carry_renamed_environment
from teleclaude.paths import ENV_PATH

logger = get_logger("teleclaude.entrypoints.environment_defaults")

_REDIS_CLUSTER_URL_VARIABLE = "REDIS_CLUSTER_URL"
_ENVIRONMENT_DEFAULTS_FINISHED = "installation_environment_defaults_finished"


def ensure_environment_defaults() -> bool:
    """Create local Redis defaults without changing an existing environment file."""
    created = write_environment_values(
        ENV_PATH,
        {_REDIS_CLUSTER_URL_VARIABLE: _DEFAULT_REDIS_URL},
        only_if_missing=True,
    )
    carry_renamed_environment()
    logger.info(_ENVIRONMENT_DEFAULTS_FINISHED, path=str(ENV_PATH), created=created)
    return created
