"""The starts of a todo's driver that are inside this computer's admission section.

One record per (canonical project root, slug), holding the session that start is creating or
claiming. The record lives in this process only. It is written and dropped by
:func:`driver_start_section` and read by :func:`is_starting`, below the modules that judge a claim,
so a computer can answer that a session is mid-start without importing the start lane.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.todos_db._exceptions import DriverStartBusy

logger = get_logger(__name__)

_START_REFUSED_BUSY_EVENT = "driver start refused while another start is in progress"
STARTS_IN_FLIGHT: dict[tuple[Path, str], str] = {}


def start_key(project_path: str | Path, slug: str) -> tuple[Path, str]:
    """Return the registry key of a todo's start: its canonical project root and slug."""
    return resolve_project_root(project_path), slug


def is_starting(project_path: str | Path, slug: str, session_id: str) -> bool:
    """Return whether a start of ``session_id`` for this todo is inside an admission section here."""
    return STARTS_IN_FLIGHT.get(start_key(project_path, slug)) == session_id


@asynccontextmanager
async def driver_start_section(
    project_path: str | Path,
    slug: str,
    *,
    starting_session_id: str,
) -> AsyncIterator[None]:
    """Hold the one-start-at-a-time section for a todo while a start creates or claims its orchestrator.

    Keyed by the canonical project root and slug, whatever lane is asked for: the
    holder check admits one driver per todo. Entering never waits. A free key records
    ``starting_session_id`` and enters; a key held by another start raises
    :class:`DriverStartBusy` naming the session that start is creating or claiming.
    Leaving drops the record on success and on exception, so a failed start leaves
    nothing behind. The record lives in this process only; the registry check-and-set
    has no await in it, so on the daemon's event loop it is atomic. The caller
    re-checks the slug's holder inside the section and creates or claims before leaving.
    """
    key = start_key(project_path, slug)
    in_flight = STARTS_IN_FLIGHT.get(key)
    if in_flight is not None:
        busy = DriverStartBusy(slug=slug, in_flight=in_flight)
        logger.warning(
            _START_REFUSED_BUSY_EVENT,
            project=str(key[0]),
            slug=slug,
            in_flight=in_flight,
            starting_session_id=starting_session_id,
        )
        raise busy
    STARTS_IN_FLIGHT[key] = starting_session_id
    try:
        yield
    finally:
        del STARTS_IN_FLIGHT[key]
