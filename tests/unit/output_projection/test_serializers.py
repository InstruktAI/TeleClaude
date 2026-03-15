"""Characterization tests for teleclaude.output_projection.serializers."""

from __future__ import annotations

import pytest

from teleclaude.output_projection.models import ProjectedBlock
from teleclaude.output_projection.serializers import to_structured_message


@pytest.mark.unit
@pytest.mark.parametrize(
    ("block", "expected_text"),
    [
        (
            ProjectedBlock(
                block_type="text",
                block={"type": "text", "text": "assistant reply"},
                role="assistant",
                timestamp="2024-01-01T00:00:00Z",
                entry_index=1,
                file_index=0,
            ),
            "assistant reply",
        ),
        (
            ProjectedBlock(
                block_type="thinking",
                block={"type": "thinking", "thinking": "reasoning"},
                role="assistant",
                timestamp="2024-01-01T00:00:00Z",
                entry_index=1,
                file_index=0,
            ),
            "reasoning",
        ),
        (
            ProjectedBlock(
                block_type="tool_use",
                block={"type": "tool_use", "name": "search", "input": {"q": "deploy"}},
                role="assistant",
                timestamp="2024-01-01T00:00:00Z",
                entry_index=1,
                file_index=0,
            ),
            'search: {"q": "deploy"}',
        ),
        (
            ProjectedBlock(
                block_type="tool_result",
                block={"type": "tool_result", "content": "done"},
                role="assistant",
                timestamp="2024-01-01T00:00:00Z",
                entry_index=1,
                file_index=0,
            ),
            "done",
        ),
        (
            ProjectedBlock(
                block_type="compaction",
                block={"type": "compaction"},
                role="system",
                timestamp="2024-01-01T00:00:00Z",
                entry_index=1,
                file_index=0,
            ),
            "Context compacted",
        ),
        (
            ProjectedBlock(
                block_type="unknown",
                block={},
                role="assistant",
                timestamp="2024-01-01T00:00:00Z",
                entry_index=1,
                file_index=0,
            ),
            "",
        ),
    ],
)
def test_to_structured_message_maps_block_types_to_text(block: ProjectedBlock, expected_text: str) -> None:
    message = to_structured_message(block)

    assert message.role == block.role
    assert message.type == block.block_type
    assert message.text == expected_text
    assert message.timestamp == block.timestamp
    assert message.entry_index == block.entry_index
    assert message.file_index == block.file_index
