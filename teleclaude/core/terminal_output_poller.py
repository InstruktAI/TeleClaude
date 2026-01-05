"""Terminal TUI output polling for non-tmux sessions.

Consumes a raw ANSI output log and renders screen snapshots using a VT emulator.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import AsyncIterator

from instrukt_ai_logging import get_logger

from teleclaude.core import terminal_bridge
from teleclaude.core.output_poller import OutputChanged, ProcessExited
from teleclaude.core.terminal_output_reader import TerminalOutputReader, parse_terminal_size

logger = get_logger(__name__)


class TerminalOutputPoller:
    """Poller that renders terminal screen snapshots from a raw output log."""

    def __init__(self, poll_interval: float = 1.0) -> None:
        self._poll_interval = poll_interval

    async def poll(  # pylint: disable=too-many-locals
        self,
        session_id: str,
        log_file: Path,
        terminal_size: str,
        pid: int | None,
    ) -> AsyncIterator[OutputChanged | ProcessExited]:
        cols, rows = parse_terminal_size(terminal_size)
        reader = TerminalOutputReader(log_file, cols, rows)

        started_at = time.time()
        last_changed_at = started_at
        last_output: str = ""
        while True:
            rendered = reader.read()
            if rendered is not None:
                last_output = rendered
                last_changed_at = time.time()
                yield OutputChanged(
                    session_id=session_id,
                    output=rendered,
                    started_at=started_at,
                    last_changed_at=last_changed_at,
                )

            if pid is not None and not terminal_bridge.pid_is_alive(pid):
                yield ProcessExited(
                    session_id=session_id,
                    exit_code=None,
                    final_output=last_output,
                    started_at=started_at,
                )
                break

            await asyncio.sleep(self._poll_interval)
