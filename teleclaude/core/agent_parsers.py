"""Implementations of LogParser for specific agents."""

# mypy: disable-error-code="misc"

import json
import time
from pathlib import Path
from typing import Generator, Optional, cast

from instrukt_ai_logging import get_logger

from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core.parsers import LogEvent, LogParser

logger = get_logger(__name__)


class CodexParser(LogParser):
    """Parser for Codex logs (JSONL)."""

    def can_parse(self, file_path: Path) -> bool:
        """Check if file matches Codex log pattern.

        guard: allow-string-compare
        """
        return file_path.suffix == ".jsonl"

    def extract_session_id(self, file_path: Path) -> Optional[str]:
        """Extract native session ID from file.

        guard: allow-string-compare
        """
        # Scan for session_meta to avoid missing it if not the first line yet.
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if isinstance(data, dict) and data.get("type") == "session_meta":
                        payload = data.get("payload")
                        if isinstance(payload, dict):
                            return str(payload["id"])
        except Exception:
            pass

        # Fallback to filename
        stem = file_path.stem
        # rollout-YYYY-MM-DD-UUID
        parts = stem.split("-")
        if len(parts) > 5:
            # Assume last part or heuristic
            return stem

        return None

    def parse_line(self, line: str) -> Generator[LogEvent, None, None]:
        """Parse a single line from Codex log.

        guard: allow-string-compare
        """
        entry_raw = json.loads(line)
        entry = cast(dict[str, object], entry_raw)  # noqa: loose-dict - External JSONL entry

        entry_type = entry["type"]
        if entry_type == "event_msg":
            payload = cast(dict[str, object], entry["payload"])  # noqa: loose-dict - External JSONL payload
            payload_type = payload["type"]
            if payload_type == "agent_message":
                yield LogEvent(
                    event_type="stop",
                    data={},
                    timestamp=time.time(),
                )
                return

        # Handle response_item
        if entry_type == "response_item":
            payload = cast(dict[str, object], entry["payload"])  # noqa: loose-dict - External JSONL payload
            if payload["type"] != "message":
                return
            role = cast(str, payload["role"])
            content = cast(list[object], payload["content"])

            if role in ("assistant", "model"):
                # Check for tool use / notifications
                for block_raw in content:
                    block = cast(dict[str, object], block_raw)  # noqa: loose-dict - External JSONL block
                    if block["type"] == "tool_use":
                        tool_name = str(block["name"])
                        # Generic input request detection
                        if "question" in tool_name.lower() or "input" in tool_name.lower():
                            yield LogEvent(
                                event_type="notification",
                                data={"message": str(block)},
                                timestamp=time.time(),
                            )

    def extract_last_turn(self, file_path: Path) -> str:
        """Extract text content of last model turn.

        guard: allow-string-compare
        """
        last_assistant_texts: list[str] = []
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)

                if entry["type"] != "response_item":
                    continue

                payload = cast(dict[str, object], entry["payload"])  # noqa: loose-dict - External JSONL payload
                if payload["type"] != "message":
                    continue
                role = cast(str, payload["role"])
                content = cast(list[object], payload["content"])

                if role in ("assistant", "model"):
                    assistant_texts: list[str] = []
                    for block_raw in content:
                        block = cast(dict[str, object], block_raw)  # noqa: loose-dict - External JSONL block
                        if block["type"] == "output_text":
                            text = cast(str, block["text"])
                            if text:
                                assistant_texts.append(text)
                    if assistant_texts:
                        last_assistant_texts = assistant_texts

        combined = "\n\n".join(last_assistant_texts)
        if len(combined) > UI_MESSAGE_MAX_CHARS:
            combined = combined[-UI_MESSAGE_MAX_CHARS:]
        return combined

    @staticmethod
    def _extract_output_text(content: list[object]) -> str:
        """Extract text blocks from codex content.

        guard: allow-string-compare
        """
        texts: list[str] = []
        for block_raw in content:
            block = cast(dict[str, object], block_raw)  # noqa: loose-dict - External JSONL block
            if block["type"] == "output_text":
                text = cast(str, block["text"])
                if text:
                    texts.append(text)
        return "\n\n".join(texts)
