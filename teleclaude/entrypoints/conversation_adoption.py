"""Name the computers the master-routing cutover waits for, on the mesh master.

Run on the mesh master once every Discord- or WhatsApp-enabled computer runs
endpoint routing: ``python -m teleclaude.entrypoints.conversation_adoption
--sources <A,B,…>``. Until every named computer has exported its open
conversation sessions, every computer keeps handling those adapters'
conversations on its own, as before master routing, and nobody sends the
temporarily-unavailable reply. Once they have, the master activates and the
cutover runs to its start (``teleclaude.core.inbound.cutover``). Re-running with
a corrected list is the one way to change the expected set; a computer that
already answered keeps its answer.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.core.db import get_db

logger = get_logger(__name__)

_SOURCES_FLAG: Final = "--sources"
_SOURCES_HELP: Final = "Comma-separated names of every computer that runs Discord or WhatsApp"
_SOURCE_SEPARATOR: Final = ","
_DESCRIPTION: Final = "Record the expected sources of the mesh master's conversation bindings."
_NOT_MASTER_ERROR: Final = "conversation adoption runs on the mesh master; this computer is not it"
_NO_SOURCES_ERROR: Final = "at least one source computer is required"
_RECORDED_EVENT: Final = "conversation_adoption_sources_recorded"
_RECORDED_LINE: Final = "Recorded adoption sources: {sources}"


def _parse_sources(raw: str) -> list[str]:
    return sorted({name.strip() for name in raw.split(_SOURCE_SEPARATOR) if name.strip()})


async def _record(sources: Sequence[str]) -> None:
    database = await get_db()
    await database.record_conversation_adoption_sources(sources)
    logger.info(_RECORDED_EVENT, sources=list(sources))


def main(argv: Sequence[str] | None = None) -> None:
    """Record the expected adoption sources on this mesh master."""
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument(_SOURCES_FLAG, required=True, help=_SOURCES_HELP)
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    if not config.computer.is_master:
        parser.error(_NOT_MASTER_ERROR)
    sources = _parse_sources(arguments.sources)
    if not sources:
        parser.error(_NO_SOURCES_ERROR)
    asyncio.run(_record(sources))
    print(_RECORDED_LINE.format(sources=_SOURCE_SEPARATOR.join(sources)))


if __name__ == "__main__":
    main()
