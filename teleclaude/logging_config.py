"""TeleClaude logging configuration.

TeleClaude uses the shared InstruktAI logging standard (`instrukt_ai_logging`).

There are no repo-local log path fallbacks: logs are written to the canonical
location (default: `/var/log/instrukt-ai/teleclaude/teleclaude.log`), and
installation is responsible for provisioning the log directory.
Use the `instruktai-python-logs` tool to query logs.
Example log query: `instruktai-python-logs teleclaude --since 10m`.
"""

from __future__ import annotations

import os
from typing import Optional

from instrukt_ai_logging import configure_logging


def setup_logging(level: Optional[str] = None) -> None:
    """Configure TeleClaude logging.

    Args:
        level: Optional override for `TELECLAUDE_LOG_LEVEL`.
    """
    if level:
        os.environ["TELECLAUDE_LOG_LEVEL"] = level

    configure_logging("teleclaude")
