"""Create the platform home's machine environment file, owner-only, and carry renamed variable names into it."""

from __future__ import annotations

import sys

from instrukt_ai_logging import get_logger

from teleclaude.config._environment import write_environment_values
from teleclaude.config.environment_renames import carry_renamed_environment
from teleclaude.logging_config import setup_logging
from teleclaude.paths import ENV_PATH

logger = get_logger("teleclaude.entrypoints.environment_defaults")

# The machine environment holds secrets, so only its owner may read it.
_OWNER_ONLY_MODE = 0o600
_ENVIRONMENT_DEFAULTS_FINISHED = "installation_environment_defaults_finished"


def ensure_environment_defaults() -> bool:
    """Create an empty environment file when absent and carry renamed names; an existing file keeps its values."""
    created = write_environment_values(ENV_PATH, {}, creation_mode=_OWNER_ONLY_MODE, only_if_missing=True)
    carry_renamed_environment()
    logger.info(_ENVIRONMENT_DEFAULTS_FINISHED, path=str(ENV_PATH), created=created)
    return created


def main() -> int:
    """Run the installation environment-default operation."""
    setup_logging()
    ensure_environment_defaults()
    return 0


if __name__ == "__main__":
    sys.exit(main())
