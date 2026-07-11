"""TeleClaude logging configuration.

TeleClaude uses the shared InstruktAI logging standard (`instrukt_ai_logging`).

There are no repo-local log path fallbacks: logs are written to the canonical
location (default: `~/.local/state/instrukt-ai/teleclaude/teleclaude.log`, or
under `$XDG_STATE_HOME` when set), and the shared logger ensures the directory.
Use the `instrukt-ai-logs` tool to query logs.
Example log query: `instrukt-ai-logs teleclaude --since 10m`.
"""

from __future__ import annotations

import logging
import os

from instrukt_ai_logging import configure_logging

# Sibling top-level packages whose loggers should share the app log level.
_SIBLING_PACKAGES = ("teleclaude.events",)


def setup_logging(level: str | None = None, *, source: str | None = None) -> None:
    """Configure TeleClaude logging.

    Args:
        level: Optional override for `TELECLAUDE_LOG_LEVEL`.
        source: Logical identity of the producing process within the teleclaude
            app. Default writes to `teleclaude.log` (the daemon). Sibling
            processes pass their own bare stem (e.g. `source="docs-watch"`,
            `source="cron"`) so each writes to its own `<source>.log` file
            under `~/.local/state/instrukt-ai/teleclaude/` (or
            `$XDG_STATE_HOME`). The `instrukt-ai-logs` CLI merges across all
            files.
    """
    if level:
        os.environ["TELECLAUDE_LOG_LEVEL"] = level

    if source is not None:
        configure_logging("teleclaude", source=source)
    else:
        configure_logging("teleclaude")

    # teleclaude.events is a separate top-level package — configure_logging only
    # sets the "teleclaude" logger to INFO. Without this, teleclaude.events.*
    # loggers inherit root level (WARNING) and all INFO/DEBUG output is silenced.
    app_level = logging.getLogger("teleclaude").level
    for pkg in _SIBLING_PACKAGES:
        logging.getLogger(pkg).setLevel(app_level)
