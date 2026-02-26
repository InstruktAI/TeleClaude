"""Tests for structured message extraction (session-messages-api)."""

from __future__ import annotations

import json
from pathlib import Path

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import (
    extract_messages_from_chain,
    extract_structured_messages,
)


def _write_jsonl(path: Path, entries: list[dict]) -> str:  # type: ignore[type-arg]
    """Write JSONL entries to a temp file and return the path string."""
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return str(path)


# ---------------------------------------------------------------------------
# Fixtures: sample JSONL entries
# ---------------------------------------------------------------------------

CLAUDE_USER_ENTRY = {
    "type": "human",
    "timestamp": "2026-02-10T10:00:00Z",
    "message": {
        "role": "user",
        "content": "Hello, how are you?",
    },
}

CLAUDE_ASSISTANT_ENTRY = {
    "type": "assistant",
    "timestamp": "2026-02-10T10:00:05Z",
    "message": {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "I'm doing well, thanks!"},
        ],
    },
}

CLAUDE_TOOL_USE_ENTRY = {
    "type": "assistant",
    "timestamp": "2026-02-10T10:00:10Z",
    "message": {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/test.py"}},
        ],
    },
}

CLAUDE_TOOL_RESULT_ENTRY = {
    "type": "human",
    "timestamp": "2026-02-10T10:00:11Z",
    "message": {
        "role": "user",
        "content": [
            {"type": "tool_result", "content": "print('hello')"},
        ],
    },
}

CLAUDE_THINKING_ENTRY = {
    "type": "assistant",
    "timestamp": "2026-02-10T10:00:08Z",
    "message": {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "Let me consider this..."},
        ],
    },
}

CLAUDE_COMPACTION_ENTRY = {
    "type": "system",
    "timestamp": "2026-02-10T10:05:00Z",
    "parentUuid": "abc-123",
    "message": {
        "role": "system",
        "content": "Context was compacted.",
    },
}

CLAUDE_SYSTEM_START_ENTRY = {
    "type": "system",
    "timestamp": "2026-02-10T09:59:00Z",
    "message": {
        "role": "system",
        "content": "Session started.",
    },
}


# ---------------------------------------------------------------------------
# Tests: extract_structured_messages
# ---------------------------------------------------------------------------


class TestExtractStructuredMessages:
    """Tests for extract_structured_messages."""

    def test_basic_user_and_assistant(self, tmp_path: Path) -> None:
        """Extract simple user/assistant text messages."""
        path = _write_jsonl(tmp_path / "transcript.jsonl", [CLAUDE_USER_ENTRY, CLAUDE_ASSISTANT_ENTRY])
        messages = extract_structured_messages(path, AgentName.CLAUDE)

        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].type == "text"
        assert "Hello" in messages[0].text
        assert messages[1].role == "assistant"
        assert messages[1].type == "text"
        assert "doing well" in messages[1].text

    def test_tool_entries_excluded_by_default(self, tmp_path: Path) -> None:
        """Tool entries are excluded when include_tools=False (default)."""
        path = _write_jsonl(
            tmp_path / "transcript.jsonl",
            [CLAUDE_USER_ENTRY, CLAUDE_TOOL_USE_ENTRY, CLAUDE_TOOL_RESULT_ENTRY],
        )
        messages = extract_structured_messages(path, AgentName.CLAUDE)

        # Only the user text message should appear
        assert len(messages) == 1
        assert messages[0].role == "user"

    def test_tool_entries_included(self, tmp_path: Path) -> None:
        """Tool entries are included when include_tools=True."""
        path = _write_jsonl(
            tmp_path / "transcript.jsonl",
            [CLAUDE_USER_ENTRY, CLAUDE_TOOL_USE_ENTRY, CLAUDE_TOOL_RESULT_ENTRY],
        )
        messages = extract_structured_messages(path, AgentName.CLAUDE, include_tools=True)

        tool_uses = [m for m in messages if m.type == "tool_use"]
        tool_results = [m for m in messages if m.type == "tool_result"]
        assert len(tool_uses) == 1
        assert "Read" in tool_uses[0].text
        assert len(tool_results) == 1

    def test_thinking_excluded_by_default(self, tmp_path: Path) -> None:
        """Thinking entries are excluded when include_thinking=False (default)."""
        path = _write_jsonl(
            tmp_path / "transcript.jsonl",
            [CLAUDE_USER_ENTRY, CLAUDE_THINKING_ENTRY, CLAUDE_ASSISTANT_ENTRY],
        )
        messages = extract_structured_messages(path, AgentName.CLAUDE)

        thinking_msgs = [m for m in messages if m.type == "thinking"]
        assert len(thinking_msgs) == 0

    def test_thinking_included(self, tmp_path: Path) -> None:
        """Thinking entries are included when include_thinking=True."""
        path = _write_jsonl(
            tmp_path / "transcript.jsonl",
            [CLAUDE_USER_ENTRY, CLAUDE_THINKING_ENTRY, CLAUDE_ASSISTANT_ENTRY],
        )
        messages = extract_structured_messages(path, AgentName.CLAUDE, include_thinking=True)

        thinking_msgs = [m for m in messages if m.type == "thinking"]
        assert len(thinking_msgs) == 1
        assert "consider" in thinking_msgs[0].text

    def test_codex_reasoning_normalized_as_thinking(self, tmp_path: Path) -> None:
        """Codex response_item reasoning payloads normalize into thinking messages."""
        entries = [
            {
                "type": "response_item",
                "timestamp": "2026-02-10T10:00:00Z",
                "payload": {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "Plan A"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-02-10T10:00:01Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Done"}],
                },
            },
        ]
        path = _write_jsonl(tmp_path / "codex.jsonl", entries)
        messages = extract_structured_messages(path, AgentName.CODEX, include_thinking=True)

        thinking_msgs = [m for m in messages if m.type == "thinking"]
        text_msgs = [m for m in messages if m.type == "text"]
        assert len(thinking_msgs) == 1
        assert "Plan A" in thinking_msgs[0].text
        assert any("Done" in m.text for m in text_msgs)

    def test_compaction_detection(self, tmp_path: Path) -> None:
        """System entries with parentUuid after index 0 are compaction events."""
        path = _write_jsonl(
            tmp_path / "transcript.jsonl",
            [CLAUDE_SYSTEM_START_ENTRY, CLAUDE_USER_ENTRY, CLAUDE_COMPACTION_ENTRY, CLAUDE_ASSISTANT_ENTRY],
        )
        messages = extract_structured_messages(path, AgentName.CLAUDE)

        compaction_msgs = [m for m in messages if m.type == "compaction"]
        assert len(compaction_msgs) == 1
        assert compaction_msgs[0].role == "system"
        assert compaction_msgs[0].text == "Context compacted"

    def test_since_filter(self, tmp_path: Path) -> None:
        """The since parameter filters to only newer messages."""
        path = _write_jsonl(
            tmp_path / "transcript.jsonl",
            [CLAUDE_USER_ENTRY, CLAUDE_ASSISTANT_ENTRY],
        )
        # since timestamp is after user entry but before assistant entry
        messages = extract_structured_messages(
            path,
            AgentName.CLAUDE,
            since="2026-02-10T10:00:03Z",
        )

        assert len(messages) == 1
        assert messages[0].role == "assistant"

    def test_missing_file_returns_empty(self) -> None:
        """Missing transcript file returns empty list."""
        messages = extract_structured_messages("/nonexistent/path.jsonl", AgentName.CLAUDE)
        assert messages == []

    def test_entry_index_increments(self, tmp_path: Path) -> None:
        """Each message has the correct entry_index from the source file."""
        path = _write_jsonl(
            tmp_path / "transcript.jsonl",
            [CLAUDE_USER_ENTRY, CLAUDE_ASSISTANT_ENTRY],
        )
        messages = extract_structured_messages(path, AgentName.CLAUDE)

        assert messages[0].entry_index == 0
        assert messages[1].entry_index == 1

    def test_to_dict(self, tmp_path: Path) -> None:
        """StructuredMessage.to_dict produces expected structure."""
        path = _write_jsonl(tmp_path / "transcript.jsonl", [CLAUDE_USER_ENTRY])
        messages = extract_structured_messages(path, AgentName.CLAUDE)

        d = messages[0].to_dict()
        assert d["role"] == "user"
        assert d["type"] == "text"
        assert "timestamp" in d
        assert "entry_index" in d
        assert "file_index" in d


# ---------------------------------------------------------------------------
# Tests: extract_messages_from_chain
# ---------------------------------------------------------------------------


class TestExtractMessagesFromChain:
    """Tests for multi-file stitching."""

    def test_single_file_chain(self, tmp_path: Path) -> None:
        """Chain with one file works identically to single extraction."""
        path = _write_jsonl(
            tmp_path / "transcript.jsonl",
            [CLAUDE_USER_ENTRY, CLAUDE_ASSISTANT_ENTRY],
        )
        messages = extract_messages_from_chain([path], AgentName.CLAUDE)

        assert len(messages) == 2
        assert all(m["file_index"] == 0 for m in messages)

    def test_multi_file_stitching(self, tmp_path: Path) -> None:
        """Messages from multiple files are stitched with correct file_index."""
        path1 = _write_jsonl(tmp_path / "file1.jsonl", [CLAUDE_USER_ENTRY])
        path2 = _write_jsonl(tmp_path / "file2.jsonl", [CLAUDE_ASSISTANT_ENTRY])

        messages = extract_messages_from_chain([path1, path2], AgentName.CLAUDE)

        assert len(messages) == 2
        assert messages[0]["file_index"] == 0
        assert messages[0]["role"] == "user"
        assert messages[1]["file_index"] == 1
        assert messages[1]["role"] == "assistant"

    def test_empty_chain(self) -> None:
        """Empty file chain returns empty list."""
        messages = extract_messages_from_chain([], AgentName.CLAUDE)
        assert messages == []

    def test_missing_file_in_chain_skipped(self, tmp_path: Path) -> None:
        """Missing files in chain produce empty results for that file, not errors."""
        path1 = _write_jsonl(tmp_path / "file1.jsonl", [CLAUDE_USER_ENTRY])
        messages = extract_messages_from_chain(
            [path1, "/nonexistent/file2.jsonl"],
            AgentName.CLAUDE,
        )

        assert len(messages) == 1
        assert messages[0]["file_index"] == 0


# ---------------------------------------------------------------------------
# Tests: transcript_files chain in receiver
# ---------------------------------------------------------------------------


class TestTranscriptFilesChain:
    """Tests for transcript file chain accumulation in the receiver."""

    def test_chain_accumulation(self) -> None:
        """Verify chain logic: when native_log_file changes, old path is preserved."""
        # This tests the JSON chain logic directly (without DB)
        chain: list[str] = []
        old_path = "/path/to/old.jsonl"
        new_path = "/path/to/new.jsonl"

        # Simulate the chain accumulation from receiver.py
        if old_path not in chain:
            chain.append(old_path)
        chain_json = json.dumps(chain)

        assert chain_json == json.dumps([old_path])
        assert new_path not in chain

    def test_chain_deduplication(self) -> None:
        """Same path appended twice does not create duplicates."""
        chain = ["/path/to/file1.jsonl"]
        old_path = "/path/to/file1.jsonl"

        if old_path not in chain:
            chain.append(old_path)

        assert len(chain) == 1
