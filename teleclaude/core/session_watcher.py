"""Session watcher service for detecting and monitoring agent sessions.

Monitors configured directories for new agent log files, adopts them into
active TeleClaude sessions, and dispatches events parsed from the logs.
"""

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import TeleClaudeEvents
from teleclaude.core.models import MessageMetadata
from teleclaude.core.parsers import LogParser
from teleclaude.core.summarizer import summarizer

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = logging.getLogger(__name__)


class SessionWatcher:
    """Monitors agent session directories and dispatches events."""

    def __init__(self, client: "AdapterClient") -> None:
        self.client = client
        self._running = False
        self._poll_task: Optional[asyncio.Task[None]] = None
        self._watched_files: Dict[Path, LogParser] = {}  # Path -> Parser
        self._file_positions: Dict[Path, int] = {}  # Path -> byte offset
        self._parsers: Dict[str, LogParser] = {}  # agent_name -> parser instance
        self._agent_map: Dict[Path, str] = {}  # Path -> agent_name

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
        for agent_name, agent_cfg in config.agents.items():
            # Skip if no parser registered for this agent
            parser = self._parsers.get(agent_name)
            if not parser:
                continue

            dir_path = Path(agent_cfg.session_dir).expanduser()
            if not dir_path.exists():
                continue

            pattern = agent_cfg.log_pattern or "*"

            # Find all matching files
            try:
                files = list(dir_path.rglob(pattern))

                for file_path in files:
                    if file_path not in self._watched_files:
                        # New file candidate
                        if parser.can_parse(file_path):
                            await self._try_adopt_session(file_path, agent_name, parser)

            except Exception as e:
                logger.warning("Error scanning directory %s: %s", dir_path, e)

    async def _try_adopt_session(self, file_path: Path, agent_name: str, parser: LogParser) -> None:
        """Try to match a new file to an active TeleClaude session."""
        # Get active sessions for this agent that don't have a log file yet
        sessions = await db.get_active_sessions()

        target_session = None

        # Filter for sessions running this agent and missing native_log_file
        candidates = []
        for session in sessions:
            ux_state = await db.get_ux_state(session.session_id)
            if ux_state.active_agent == agent_name and not ux_state.native_log_file:
                candidates.append(session)

        # Heuristic: Pick most recent candidate
        if candidates:

            def get_session_timestamp(s: "Session") -> float:
                return s.created_at.timestamp() if s.created_at else 0.0

            # Sort by created_at desc
            candidates.sort(key=get_session_timestamp, reverse=True)
            target_session = candidates[0]

        if target_session:
            logger.info(
                "Adopting session log %s for session %s (agent: %s)",
                file_path,
                target_session.session_id[:8],
                agent_name,
            )

            # Extract native session ID if possible
            native_id = parser.extract_session_id(file_path)

            # Update DB
            await db.update_ux_state(
                target_session.session_id,
                native_log_file=str(file_path),
                native_session_id=native_id if native_id else None,
            )

            # Start watching
            self._watched_files[file_path] = parser
            self._agent_map[file_path] = agent_name

            # Set initial position to end of file? Or start?
            # If adoption happens late, we might want to read from start.
            # If adoption happens immediately, start is fine.
            # Let's start from 0 to capture initial events (like start).
            self._file_positions[file_path] = 0

            # Emit session_start event immediately
            await self.client.handle_event(
                TeleClaudeEvents.AGENT_EVENT,  # Generic event name for hooks
                {
                    "event_type": "session_start",
                    "session_id": target_session.session_id,
                    "data": {"session_id": native_id, "transcript_path": str(file_path)},
                },
                MessageMetadata(adapter_type="watcher"),
            )

    async def _tail_files(self) -> None:
        """Read new content from watched files and dispatch events."""
        for file_path, parser in list(self._watched_files.items()):
            if not file_path.exists():
                logger.warning("Watched file %s disappeared", file_path)
                del self._watched_files[file_path]
                del self._file_positions[file_path]
                del self._agent_map[file_path]
                continue

            try:
                # Get current size
                current_size = file_path.stat().st_size
                last_pos = self._file_positions.get(file_path, 0)

                if current_size > last_pos:
                    # New content available
                    with open(file_path, "r", encoding="utf-8") as f:
                        f.seek(last_pos)
                        new_lines = f.readlines()
                        self._file_positions[file_path] = f.tell()

                    # Find TeleClaude session ID for this file
                    # We need to look it up again or cache it?
                    # get_session_by_ux_state logic
                    session = await db.get_session_by_ux_state("native_log_file", str(file_path))
                    if not session:
                        # Orphaned file? Stop watching?
                        # Maybe session closed.
                        # Check if session closed in DB?
                        # But get_session_by_ux_state returns None if not found.
                        # Actually we should check if session is still active.
                        continue

                    for line in new_lines:
                        if not line.strip():
                            continue

                        # Parse line
                        for event in parser.parse_line(line):
                            # Dispatch event
                            # Map parser event types to TeleClaude event types
                            # parser yields LogEvent(event_type, data, timestamp)
                            # We use CLAUDE_EVENT (hook event) as the generic bus for now

                            payload_data = event.data.copy()

                            # Enrich stop events with summary using centralized summarizer
                            if event.event_type == "stop":
                                try:
                                    summary_data = await summarizer.summarize_session(session.session_id)
                                    payload_data.update(summary_data)
                                except Exception as e:
                                    logger.error("Failed to summarize session %s: %s", session.session_id[:8], e)

                            # Add native session ID if available in DB/file
                            # (parser might extract it from content too)

                            await self.client.handle_event(
                                TeleClaudeEvents.AGENT_EVENT,
                                {
                                    "event_type": event.event_type,
                                    "session_id": session.session_id,  # TeleClaude ID
                                    "data": payload_data,
                                },
                                MessageMetadata(adapter_type="watcher"),
                            )

            except Exception as e:
                logger.error("Error tailing file %s: %s", file_path, e)
