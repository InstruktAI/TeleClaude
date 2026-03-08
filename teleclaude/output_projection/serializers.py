"""Serializers over the canonical projection route.

Convert ProjectedBlock objects to different output formats:
- StructuredMessage (for /sessions/{id}/messages API)

Future consumers (mirror, search) adopt the same contract via
project_conversation_chain() + to_structured_message().
"""

from __future__ import annotations

import json

from teleclaude.output_projection.models import ProjectedBlock
from teleclaude.utils.transcript import StructuredMessage


def to_structured_message(block: ProjectedBlock) -> StructuredMessage:
    """Convert a projected block to a StructuredMessage for the API response.

    Replaces the per-consumer text extraction logic that was scattered across
    extract_messages_from_chain() and convert_entry(). Downstream consumers
    call this serializer after applying their visibility policy.

    Args:
        block: A visibility-filtered projected block.

    Returns:
        StructuredMessage suitable for /sessions/{id}/messages response.
    """
    if block.block_type == "text":
        text = str(block.block.get("text", ""))
    elif block.block_type == "thinking":
        text = str(block.block.get("thinking", ""))
    elif block.block_type == "tool_use":
        tool_name = str(block.block.get("name", "unknown"))
        tool_input = block.block.get("input", {})
        text = f"{tool_name}: {json.dumps(tool_input)}"
    elif block.block_type == "tool_result":
        text = str(block.block.get("content", ""))
    elif block.block_type == "compaction":
        text = str(block.block.get("text", "Context compacted"))
    else:
        text = ""

    return StructuredMessage(
        role=block.role,
        type=block.block_type,
        text=text,
        timestamp=block.timestamp,
        entry_index=block.entry_index,
        file_index=block.file_index,
    )
