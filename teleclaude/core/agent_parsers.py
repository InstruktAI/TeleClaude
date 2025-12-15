"""Implementations of LogParser for specific agents."""

import json
import logging
import time
from pathlib import Path
from typing import Generator, Optional, cast

from teleclaude.core.parsers import LogEvent, LogParser

logger = logging.getLogger(__name__)


class CodexParser(LogParser):
    """Parser for Codex logs (JSONL)."""

    def can_parse(self, file_path: Path) -> bool:
        """Check if file matches Codex log pattern."""
        return file_path.suffix == ".jsonl"

    def extract_session_id(self, file_path: Path) -> Optional[str]:
        """Extract native session ID from file."""
        # Try reading first line for session_meta
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                first_line = f.readline()
                if first_line:
                    data = json.loads(first_line)
                    if isinstance(data, dict) and data.get("type") == "session_meta":
                        payload = data.get("payload")
                        if isinstance(payload, dict):
                            return str(payload.get("id"))
        except Exception:
            pass

        # Fallback to filename
        stem = file_path.stem
        # rollout-YYYY-MM-DD-UUID
        parts = stem.split("-")
        if len(parts) > 5:
            # Assume last part or heuristic
            # But session_meta is reliable.
            pass

        return None

    def parse_line(self, line: str) -> Generator[LogEvent, None, None]:
        """Parse a single line from Codex log."""
        try:
            entry_raw = json.loads(line)
        except json.JSONDecodeError:
            return

        if not isinstance(entry_raw, dict):
            return

        entry = cast(dict[str, object], entry_raw)

        # Handle response_item
        entry_type = entry.get("type")
        if isinstance(entry_type, str) and entry_type == "response_item":
            payload_raw = entry.get("payload")
            if isinstance(payload_raw, dict):
                payload = cast(dict[str, object], payload_raw)
                role = payload.get("role")

                if role == "assistant" or role == "model":
                    # Check for completion/stop
                    yield LogEvent(
                        event_type="stop",
                        data={},
                        timestamp=time.time(),
                    )

                    # Check for tool use / notifications
                    content = payload.get("content")
                    if isinstance(content, list):
                        for block_raw in content:
                            if isinstance(block_raw, dict):
                                block = cast(dict[str, object], block_raw)
                                if block.get("type") == "tool_use":
                                    tool_name = str(block.get("name", ""))
                                    # Generic input request detection
                                    if "question" in tool_name.lower() or "input" in tool_name.lower():
                                        yield LogEvent(
                                            event_type="notification",
                                            data={"message": "Codex requests input", "original_message": str(block)},
                                            timestamp=time.time(),
                                        )
