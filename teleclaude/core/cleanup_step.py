"""Containment of ordinary cleanup failures."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_CLEANUP_STEP_FAILED = "Cleanup step failed; continuing cleanup"


@contextmanager
def cleanup_step(component: str) -> Iterator[None]:
    """Report an ordinary component-cleanup fault without deciding lifecycle admission or settlement."""
    try:
        yield
    except Exception:
        logger.exception(_CLEANUP_STEP_FAILED, component=component)
