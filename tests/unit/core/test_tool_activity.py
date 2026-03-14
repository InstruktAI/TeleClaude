"""Characterization tests for teleclaude.core.tool_activity."""

from __future__ import annotations

import pytest

from teleclaude.core.tool_activity import (
    TOOL_ACTIVITY_PREVIEW_MAX_CHARS,
    build_tool_preview,
    extract_tool_name,
    truncate_tool_preview,
)


class TestTruncateToolPreview:
    @pytest.mark.unit
    def test_none_returns_none(self):
        assert truncate_tool_preview(None) is None

    @pytest.mark.unit
    def test_empty_string_returns_none(self):
        assert truncate_tool_preview("") is None

    @pytest.mark.unit
    def test_whitespace_only_returns_none(self):
        assert truncate_tool_preview("   ") is None

    @pytest.mark.unit
    def test_short_text_returned_as_is(self):
        result = truncate_tool_preview("Read file.txt")
        assert result == "Read file.txt"

    @pytest.mark.unit
    def test_text_truncated_at_max_chars(self):
        long_text = "x" * (TOOL_ACTIVITY_PREVIEW_MAX_CHARS + 50)
        result = truncate_tool_preview(long_text)
        assert result is not None
        assert len(result) <= TOOL_ACTIVITY_PREVIEW_MAX_CHARS

    @pytest.mark.unit
    def test_tree_prefix_stripped(self):
        result = truncate_tool_preview("│ Read file.txt")
        assert result is not None
        assert "│" not in result


class TestExtractToolName:
    @pytest.mark.unit
    def test_none_payload_returns_none(self):
        assert extract_tool_name(None) is None

    @pytest.mark.unit
    def test_empty_payload_returns_none(self):
        assert extract_tool_name({}) is None

    @pytest.mark.unit
    def test_tool_name_extracted(self):
        result = extract_tool_name({"tool_name": "Bash"})
        assert result == "Bash"

    @pytest.mark.unit
    def test_tool_name_camel_case_also_accepted(self):
        result = extract_tool_name({"toolName": "Read"})
        assert result == "Read"


class TestBuildToolPreview:
    @pytest.mark.unit
    def test_none_inputs_return_none(self):
        result = build_tool_preview(tool_name=None, raw_payload=None)
        assert result is None

    @pytest.mark.unit
    def test_tool_name_only_returns_truncated_name(self):
        result = build_tool_preview(tool_name="Bash", raw_payload=None)
        assert result == "Bash"

    @pytest.mark.unit
    def test_payload_tool_preview_field_used(self):
        result = build_tool_preview(
            tool_name="Bash",
            raw_payload={"tool_preview": "ls -la"},
        )
        assert result is not None
        assert "ls -la" in result

    @pytest.mark.unit
    def test_payload_tool_input_command_used(self):
        result = build_tool_preview(
            tool_name="Bash",
            raw_payload={"tool_input": {"command": "ls -la /tmp"}},
        )
        assert result == "Bash ls -la /tmp"

    @pytest.mark.unit
    def test_next_work_invocation_normalized(self):
        result = build_tool_preview(
            tool_name="next_work",
            raw_payload={"tool_name": "next_work", "tool_input": {"slug": "my-feature"}},
        )
        assert result == "telec todo work my-feature"
