"""Characterization tests for teleclaude.output_projection.conversation_projector."""

from __future__ import annotations

from unittest.mock import call, patch

import pytest

import teleclaude.output_projection.conversation_projector as conversation_projector
from teleclaude.core.agents import AgentName
from teleclaude.output_projection.models import VisibilityPolicy


class TestProjectEntries:
    @pytest.mark.unit
    def test_applies_visibility_rules_and_sanitizes_internal_user_content(self) -> None:
        entries: list[object] = [
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"role": "user", "content": "[TeleClaude System]\n\nhidden"},
            },
            {
                "timestamp": "2024-01-01T00:00:01Z",
                "message": {"role": "user", "content": "hello user"},
            },
            {
                "timestamp": "2024-01-01T00:00:02Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "assistant text"},
                        {"type": "text", "text": "   "},
                        {"type": "input_text", "text": "input text"},
                        {"type": "output_text", "text": "output text"},
                        {"type": "thinking", "thinking": "hidden reasoning"},
                        {"type": "tool_use", "name": "visible-tool", "input": {"x": 1}},
                        {"type": "tool_use", "name": "hidden-tool", "input": {"y": 2}},
                        {"type": "tool_result", "content": "tool output"},
                    ],
                },
            },
            {
                "timestamp": "2024-01-01T00:00:03Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "content": "rerouted output"}],
                },
            },
        ]
        policy = VisibilityPolicy(
            include_tool_results=True,
            visible_tool_names=frozenset({"visible-tool"}),
        )

        blocks = list(conversation_projector.project_entries(entries, policy, file_index=4))

        assert [
            (
                block.block_type,
                block.role,
                block.block.get("type"),
                block.block.get("text"),
                block.block.get("name"),
                block.block.get("content"),
                block.entry_index,
                block.file_index,
            )
            for block in blocks
        ] == [
            ("text", "user", "text", "hello user", None, None, 1, 4),
            ("text", "assistant", "text", "assistant text", None, None, 2, 4),
            ("text", "assistant", "input_text", "input text", None, None, 2, 4),
            ("text", "assistant", "output_text", "output text", None, None, 2, 4),
            ("tool_use", "assistant", "tool_use", None, "visible-tool", None, 2, 4),
            ("tool_result", "assistant", "tool_result", None, None, "tool output", 2, 4),
            ("tool_result", "assistant", "tool_result", None, None, "rerouted output", 3, 4),
        ]

    @pytest.mark.unit
    def test_filters_since_and_emits_compaction_and_reasoning_blocks(self) -> None:
        entries: list[object] = [
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "too old"}]},
            },
            {
                "timestamp": "2024-01-01T00:00:01Z",
                "type": "summary",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "summary"}]},
            },
            {
                "timestamp": "2024-01-01T00:00:02Z",
                "message": {"role": "system", "content": "compaction marker"},
                "parentUuid": "prev-entry",
            },
            {
                "timestamp": "2024-01-01T00:00:03Z",
                "type": "response_item",
                "payload": {
                    "type": "reasoning",
                    "summary": ["step one"],
                    "text": "step two",
                    "content": [{"text": "step two"}],
                },
            },
            {
                "timestamp": "2024-01-01T00:00:04Z",
                "message": {"role": 7, "content": [{"type": "text", "text": "bad role"}]},
            },
        ]
        policy = VisibilityPolicy(include_thinking=True)

        blocks = list(
            conversation_projector.project_entries(
                entries,
                policy,
                since="2024-01-01T00:00:01Z",
                file_index=2,
            )
        )

        assert [
            (block.block_type, block.role, block.timestamp, block.entry_index, block.file_index) for block in blocks
        ] == [
            ("compaction", "system", "2024-01-01T00:00:02Z", 2, 2),
            ("thinking", "assistant", "2024-01-01T00:00:03Z", 3, 2),
        ]
        assert blocks[0].block == {"type": "compaction", "text": "Context compacted"}
        assert blocks[1].block == {"type": "thinking", "thinking": "step one\n\nstep two"}


class TestProjectConversationChain:
    @pytest.mark.unit
    def test_aggregates_blocks_across_files_and_skips_missing_entry_sets(self) -> None:
        file_paths = ["a.jsonl", "b.jsonl", "c.jsonl"]
        entries_a = [
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"role": "user", "content": "first file"},
            }
        ]
        entries_c = [
            {
                "timestamp": "2024-01-01T00:00:02Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "third file"}]},
            }
        ]

        with patch(
            "teleclaude.output_projection.conversation_projector._get_entries_for_agent",
            side_effect=[entries_a, None, entries_c],
        ) as mock_get_entries:
            blocks = conversation_projector.project_conversation_chain(
                file_paths,
                AgentName.CLAUDE,
                VisibilityPolicy(),
                since="2024-01-01T00:00:01Z",
            )

        assert [(block.block.get("text"), block.file_index) for block in blocks] == [("third file", 2)]
        assert mock_get_entries.call_args_list == [
            call("a.jsonl", AgentName.CLAUDE),
            call("b.jsonl", AgentName.CLAUDE),
            call("c.jsonl", AgentName.CLAUDE),
        ]
