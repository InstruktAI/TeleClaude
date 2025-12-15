"""Session watcher service for detecting and monitoring agent sessions.

Monitors configured directories for new agent log files, adopts them into
active TeleClaude sessions, and dispatches events parsed from the logs.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional

from teleclaude.core.parsers import LogParser

logger = logging.getLogger(__name__)


class SessionWatcher:
    """Monitors agent session directories and dispatches events."""

    def __init__(self) -> None:
        self._running = False
        self._poll_task: Optional[asyncio.Task[None]] = None
        self._watched_files: Dict[Path, LogParser] = {}
        self._file_positions: Dict[Path, int] = {}
        self._parsers: Dict[str, LogParser] = {}  # agent_name -> parser instance

    def register_parser(self, agent_name: str, parser: LogParser) -> None:
        """Register a log parser for a specific agent."""
        self._parsers[agent_name] = parser

    async def start(self) -> None:
        """Start the session watcher."""
        if self._running:
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("SessionWatcher started")

    async def stop(self) -> None:
        """Stop the session watcher."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("SessionWatcher stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._scan_directories()
                await self._tail_files()
                await asyncio.sleep(1.0)  # Poll every second
            except Exception as e:
                logger.error("Error in SessionWatcher poll loop: %s", e)
                await asyncio.sleep(5.0)  # Backoff on error

    async def _scan_directories(self) -> None:
        """Scan configured directories for new session files."""
        # TODO: Implement scanning logic
        pass

    async def _tail_files(self) -> None:
        """Read new content from watched files and dispatch events."""
        # TODO: Implement tailing logic
        pass
