"""Codex watcher for detecting and monitoring Codex session logs."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.agent_parsers import CodexParser
from teleclaude.core.db import Db, db
from teleclaude.core.events import AgentHookEvents, TeleClaudeEvents
from teleclaude.core.models import MessageMetadata

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)
CODEX_BIND_BACKFILL_BYTES = 65536


class CodexWatcher:
    """Monitors Codex session directories and dispatches events."""

    def __init__(self, client: "AdapterClient", db_handle: Db | None = None) -> None:
        self.client = client
        self._db = db_handle if db_handle is not None else db
        self._running = False
        self._poll_task: Optional[asyncio.Task[None]] = None
        self._parser = CodexParser()
        self._watched_files: set[Path] = set()
        self._file_positions: dict[Path, int] = {}
        self._log_timestamps: dict[Path, float] = {}

    async def start(self) -> None:
        """Start the Codex watcher."""
        if self._running:
            return
        self._running = True
        await self._rehydrate_watched_files()
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("CodexWatcher started")

    async def stop(self) -> None:
        """Stop the Codex watcher."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("CodexWatcher stopped")

    async def _rehydrate_watched_files(self) -> None:
        """Re-attach to existing Codex sessions with known log files after restart."""
        sessions = await self._db.get_active_sessions()
        for session in sessions:
            if session.active_agent != "codex" or not session.native_log_file:
                continue

            file_path = Path(session.native_log_file).expanduser()
            if file_path in self._watched_files:
                continue

            self._watched_files.add(file_path)
            self._file_positions[file_path] = file_path.stat().st_size

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._scan_directory()
                await self._tail_files()
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error("Error in CodexWatcher poll loop: %s", e)
                await asyncio.sleep(5.0)

    async def _scan_directory(self) -> None:
        """Scan the Codex session directory for new session files."""
        agent_cfg = config.agents["codex"]
        dir_path = Path(agent_cfg.session_dir).expanduser()
        pattern = agent_cfg.log_pattern or "*.jsonl"
        files = [f for f in dir_path.rglob(pattern) if f.is_file()]
        if not files:
            return

        codex_sessions: list["Session"] = []
        for session in await self._db.get_active_sessions():
            if session.active_agent == "codex":
                codex_sessions.append(session)

        if not codex_sessions:
            return

        # Sort by creation time so earlier sessions get first pick of files
        def get_created_at(item: "Session") -> datetime:
            return item.created_at if item.created_at else datetime.min

        codex_sessions.sort(key=get_created_at)

        # Build map of files claimed by each session
        claimed_files: dict[str, str] = {}  # file_path -> session_id
        for session in codex_sessions:
            if session.native_log_file:
                claimed_files[session.native_log_file] = session.session_id

        # Process each session with exclusive file selection
        for session in codex_sessions:
            current_file = session.native_log_file

            # Get files available to this session (not claimed by OTHER sessions)
            available_files = [
                f for f in files if str(f) not in claimed_files or claimed_files[str(f)] == session.session_id
            ]
            if not available_files:
                continue

            best_file = self._select_best_log(available_files, session)

            if not current_file:
                logger.info(
                    "CodexWatcher scan: binding session %s to %s",
                    session.session_id[:8],
                    best_file,
                )
                await self._bind_session_log(session, best_file, emit_start=True)
                claimed_files[str(best_file)] = session.session_id
            elif current_file != str(best_file):
                logger.info(
                    "CodexWatcher scan: rebinding session %s from %s to %s",
                    session.session_id[:8],
                    current_file,
                    best_file,
                )
                claimed_files.pop(current_file, None)
                await self._bind_session_log(session, best_file, emit_start=False)
                claimed_files[str(best_file)] = session.session_id
            elif best_file not in self._watched_files:
                logger.info(
                    "CodexWatcher scan: attaching session %s to %s",
                    session.session_id[:8],
                    best_file,
                )
                await self._bind_session_log(session, best_file, emit_start=False)

    def _select_best_log(self, files: list[Path], session: "Session") -> Path:
        """Select the best Codex log file for a session based on session start time."""
        if not files:
            raise ValueError("No Codex logs available to bind")

        if not session.created_at:
            return files[0]

        target_ts = session.created_at.timestamp()
        best_file = files[0]
        best_delta = abs(self._get_log_timestamp(best_file) - target_ts)
        for path in files[1:]:
            delta = abs(self._get_log_timestamp(path) - target_ts)
            if delta < best_delta:
                best_delta = delta
                best_file = path
        return best_file

    def _get_log_timestamp(self, file_path: Path) -> float:
        """Extract the session_meta timestamp for a Codex log file."""
        cached = self._log_timestamps.get(file_path)
        if cached is not None:
            return cached

        with open(file_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                data = cast(dict[str, object], json.loads(line))  # noqa: loose-dict - External JSONL data
                if data.get("type") != "session_meta":
                    continue
                payload = cast(dict[str, object], data["payload"])  # noqa: loose-dict - External JSONL payload
                timestamp = payload["timestamp"]
                ts_value = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).timestamp()
                self._log_timestamps[file_path] = ts_value
                return ts_value

        raise ValueError(f"Codex log {file_path} missing session_meta timestamp")

    async def _bind_session_log(
        self,
        session: "Session",
        file_path: Path,
        *,
        emit_start: bool,
    ) -> None:
        """Bind a session to a log file and update watcher state."""
        logger.info("Binding Codex log %s to session %s", file_path, session.session_id[:8])
        all_sessions = await self._db.list_sessions()
        for other in all_sessions:
            if other.session_id == session.session_id:
                continue
            if other.native_log_file == str(file_path):
                await self._db.update_session(
                    other.session_id,
                    native_log_file=None,
                    native_session_id=None,
                )

        native_id = self._parser.extract_session_id(file_path)
        if not native_id:
            raise ValueError(f"Session log {file_path} missing native_session_id for Codex")

        previous_log = session.native_log_file
        if previous_log:
            previous_path = Path(previous_log).expanduser()
            self._watched_files.discard(previous_path)
            self._file_positions.pop(previous_path, None)

        await self._db.update_session(
            session.session_id,
            native_log_file=str(file_path),
            native_session_id=native_id,
        )

        self._watched_files.add(file_path)
        file_size = file_path.stat().st_size
        backfill = min(CODEX_BIND_BACKFILL_BYTES, file_size)
        self._file_positions[file_path] = file_size - backfill

        if emit_start:
            await self.client.handle_event(
                TeleClaudeEvents.AGENT_EVENT,
                {
                    "event_type": AgentHookEvents.AGENT_SESSION_START,
                    "session_id": session.session_id,
                    "data": {"session_id": native_id, "transcript_path": str(file_path)},
                },
                MessageMetadata(adapter_type="watcher"),
            )

    async def _tail_files(self) -> None:
        """Read new content from watched files and dispatch events."""
        for file_path in list(self._watched_files):
            if not file_path.exists():
                logger.warning("Watched Codex log %s disappeared", file_path)
                self._watched_files.discard(file_path)
                self._file_positions.pop(file_path, None)
                continue

            try:
                current_size = file_path.stat().st_size
                last_pos = self._file_positions.get(file_path, 0)

                if current_size <= last_pos:
                    continue

                with open(file_path, "r", encoding="utf-8") as f:
                    f.seek(last_pos)
                    new_lines = f.readlines()
                    self._file_positions[file_path] = f.tell()

                session = None
                active_sessions = await self._db.list_sessions()
                for candidate in active_sessions:
                    if candidate.native_log_file == str(file_path):
                        session = candidate
                        break

                if not session:
                    logger.warning("CodexWatcher tail: no active session for %s", file_path)
                    self._watched_files.discard(file_path)
                    self._file_positions.pop(file_path, None)
                    continue

                emitted = 0
                entry_type_counts: dict[str, int] = {}
                event_msg_counts: dict[str, int] = {}
                for line in new_lines:
                    if not line.strip():
                        continue

                    try:
                        entry = cast(dict[str, object], json.loads(line))  # noqa: loose-dict - External JSONL entry
                        entry_type = str(entry.get("type"))
                        entry_type_counts[entry_type] = entry_type_counts.get(entry_type, 0) + 1
                        if entry_type == "event_msg":
                            payload = cast(dict[str, object], entry.get("payload", {}))  # noqa: loose-dict - External JSONL payload
                            payload_type = str(payload.get("type"))
                            event_msg_counts[payload_type] = event_msg_counts.get(payload_type, 0) + 1

                        # Parse and emit events (only if JSON parsing succeeded)
                        for event in self._parser.parse_line(line):
                            payload_data = event.data.copy()
                            if not session.native_session_id:
                                raise ValueError(f"Session {session.session_id[:8]} missing native_session_id")
                            payload_data["session_id"] = session.native_session_id
                            payload_data["transcript_path"] = str(file_path)

                            await self.client.handle_event(
                                TeleClaudeEvents.AGENT_EVENT,
                                {
                                    "event_type": event.event_type,
                                    "session_id": session.session_id,
                                    "data": payload_data,
                                },
                                MessageMetadata(adapter_type="watcher"),
                            )
                            emitted += 1
                    except json.JSONDecodeError:
                        # Expected for partial lines after backfill seek
                        entry_type_counts["parse_error"] = entry_type_counts.get("parse_error", 0) + 1

                if emitted:
                    logger.info(
                        "CodexWatcher tail: emitted %d event(s) for session %s from %s (entries=%s event_msgs=%s)",
                        emitted,
                        session.session_id[:8],
                        file_path,
                        entry_type_counts,
                        event_msg_counts,
                    )

            except Exception as e:
                logger.error("Error tailing Codex log %s: %s", file_path, e)
