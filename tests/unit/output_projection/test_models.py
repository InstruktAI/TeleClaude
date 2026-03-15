"""Characterization tests for teleclaude.output_projection.models."""

from __future__ import annotations

import pytest

from teleclaude.output_projection.models import (
    PERMISSIVE_POLICY,
    THREADED_CLEAN_POLICY,
    WEB_POLICY,
    ProjectedBlock,
    TerminalLiveProjection,
    VisibilityPolicy,
)


class TestVisibilityPolicy:
    @pytest.mark.unit
    def test_defaults_hide_optional_block_types(self) -> None:
        policy = VisibilityPolicy()

        assert policy.include_tools is False
        assert policy.include_tool_results is False
        assert policy.include_thinking is False
        assert policy.visible_tool_names == frozenset()

    @pytest.mark.unit
    def test_named_policy_constants_pin_expected_visibility(self) -> None:
        assert WEB_POLICY == VisibilityPolicy()
        assert THREADED_CLEAN_POLICY == VisibilityPolicy(
            include_tools=True,
            include_tool_results=False,
            include_thinking=True,
        )
        assert PERMISSIVE_POLICY == VisibilityPolicy(
            include_tools=True,
            include_tool_results=True,
            include_thinking=True,
        )

    @pytest.mark.unit
    def test_is_frozen_dataclass(self) -> None:
        policy = VisibilityPolicy()

        with pytest.raises((AttributeError, TypeError)):
            policy.include_tools = True


class TestProjectionDataclasses:
    @pytest.mark.unit
    def test_projected_block_stores_projection_metadata(self) -> None:
        block = ProjectedBlock(
            block_type="tool_use",
            block={"type": "tool_use", "name": "search", "input": {"q": "deploy"}},
            role="assistant",
            timestamp="2024-01-01T00:00:00Z",
            entry_index=7,
            file_index=2,
        )

        assert block.block_type == "tool_use"
        assert block.block["name"] == "search"
        assert block.role == "assistant"
        assert block.timestamp == "2024-01-01T00:00:00Z"
        assert block.entry_index == 7
        assert block.file_index == 2

    @pytest.mark.unit
    def test_terminal_live_projection_stores_output(self) -> None:
        projection = TerminalLiveProjection(output="clean terminal snapshot")

        assert projection.output == "clean terminal snapshot"
