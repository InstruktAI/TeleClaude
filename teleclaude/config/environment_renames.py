"""Machine environment names the schema renamed, carried to their current names before anything reads them.

A configuration migration that points a reference at a renamed variable leaves it unresolved on a computer whose
environment still holds only the earlier name. Every install carries such values before the configuration migrations
run, so the renamed reference resolves to what the earlier one did.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.config._environment import read_environment_file, write_environment_values
from teleclaude.paths import ENV_PATH

logger = get_logger(__name__)

#: Each earlier environment name and the schema-derived name that replaced it.
RENAMED_ENVIRONMENT_NAMES: Final[dict[str, str]] = {
    # The cluster Redis moved from `redis` to `redis.cluster` (configuration schema 28).
    "REDIS_URL": "REDIS_CLUSTER_URL",
    "REDIS_PASSWORD": "REDIS_CLUSTER_PASSWORD",
}
_CARRIED_EVENT: Final = "environment_renamed_names_carried"


def carry_renamed_environment(path: Path = ENV_PATH) -> tuple[str, ...]:
    """Give each current name the value its earlier name holds, where it has none of its own; the names carried."""
    environment = read_environment_file(path, interpolate=False)
    carried = {
        current: environment[earlier]
        for earlier, current in RENAMED_ENVIRONMENT_NAMES.items()
        if earlier in environment and current not in environment
    }
    if carried:
        write_environment_values(path, carried)
        logger.info(_CARRIED_EVENT, names=sorted(carried))
    return tuple(sorted(carried))
