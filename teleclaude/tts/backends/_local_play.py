"""Shared local audio-file playback via the system `afplay` binary."""

from __future__ import annotations

import subprocess
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_AFPLAY_TIMEOUT_S = 300


def play_file(path: Path) -> bool:
    """Play a local audio file through `afplay`, returning whether playback succeeded."""
    try:
        result = subprocess.run(
            ["afplay", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=_AFPLAY_TIMEOUT_S,
        )
    except FileNotFoundError:
        logger.debug("afplay command not found (not on macOS?)")
        return False
    if result.returncode:
        logger.error("afplay failed for %s: %s", path, (result.stderr or result.stdout).strip())
        return False
    return True
