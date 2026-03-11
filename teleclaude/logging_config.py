"""TeleClaude logging configuration.

TeleClaude uses the shared InstruktAI logging standard (`instrukt_ai_logging`).

There are no repo-local log path fallbacks: logs are written to the canonical
location (default: `/var/log/instrukt-ai/teleclaude/teleclaude.log`), and
installation is responsible for provisioning the log directory.
Use the `instrukt-ai-logs` tool to query logs.
Example log query: `instrukt-ai-logs teleclaude --since 10m`.
"""

from __future__ import annotations

import logging
import os

from instrukt_ai_logging import configure_logging

# Sibling top-level packages whose loggers should share the app log level.
_SIBLING_PACKAGES = ("teleclaude.events",)


def setup_logging(level: str | None = None) -> None:
    """Configure TeleClaude logging.

    Args:
        level: Optional override for `TELECLAUDE_LOG_LEVEL`.
    """
    if level:
        os.environ["TELECLAUDE_LOG_LEVEL"] = level

    configure_logging("teleclaude")

    # teleclaude.events is a separate top-level package — configure_logging only
    # sets the "teleclaude" logger to INFO. Without this, teleclaude.events.*
    # loggers inherit root level (WARNING) and all INFO/DEBUG output is silenced.
    app_level = logging.getLogger("teleclaude").level
    for pkg in _SIBLING_PACKAGES:
        logging.getLogger(pkg).setLevel(app_level)
