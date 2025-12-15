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
        """Extract native session ID from file path."""
        # Codex sessions might be named by UUID
        stem = file_path.stem
        if len(stem) > 8:
            return stem
        return None

    def parse_line(self, line: str) -> Generator[LogEvent, None, None]:
        """Parse a single line from Codex log."""
        try:
            entry_raw: object = json.loads(line)
        except json.JSONDecodeError:
            return

        if not isinstance(entry_raw, dict):
            return

        entry = cast(dict[str, object], entry_raw)

        # Adapt schema based on Codex logs
        # Assuming generic "role" based structure similar to others
        role = entry.get("role")
        if role == "assistant" or role == "model":
            # Check for completion/stop
            # If it's a message from the model, treat it as a potential stop/turn end
            yield LogEvent(
                event_type="stop",
                data={},
                timestamp=time.time(),
            )

            # Check for tool use / notifications
            content_raw = entry.get("content")
            if isinstance(content_raw, list):
                for block_raw in content_raw:
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
