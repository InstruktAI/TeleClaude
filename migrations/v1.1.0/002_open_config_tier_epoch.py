"""Open the one-time configuration tier advancement epoch."""

from __future__ import annotations

from teleclaude.config.advancement import ADVANCEMENT_STATE_PATH, open_epoch


def check() -> bool:
    """Return whether the epoch has already captured its eligible roots."""
    return ADVANCEMENT_STATE_PATH.exists()


def migrate() -> bool:
    """Open the epoch exactly once through the deployment migration runner."""
    return open_epoch() or check()
