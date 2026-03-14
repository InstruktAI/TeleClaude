"""Characterization tests for teleclaude.core.tool_access."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.core.tool_access import (
    ToolSpec,
    filter_tool_names,
    filter_tool_specs,
    get_allowed_tools,
    get_excluded_tools,
)

# is_command_allowed is imported locally inside each function in tool_access.py,
# so the correct patch target is the source module, not tool_access itself.
_PATCH_IS_ALLOWED = "teleclaude.cli.telec.is_command_allowed"


class TestFilterToolNames:
    @pytest.mark.unit
    def test_empty_tool_list_returns_empty(self):
        result = filter_tool_names("worker", [])
        assert result == []

    @pytest.mark.unit
    def test_allowed_tools_pass_through(self):
        tools = ["telec sessions list", "telec sessions start"]
        with patch(_PATCH_IS_ALLOWED, return_value=True):
            result = filter_tool_names("worker", tools)
        assert result == tools

    @pytest.mark.unit
    def test_denied_tools_filtered_out(self):
        tools = ["telec sessions list", "telec sessions start"]
        with patch(_PATCH_IS_ALLOWED, return_value=False):
            result = filter_tool_names("worker", tools)
        assert result == []


class TestFilterToolSpecs:
    @pytest.mark.unit
    def test_allowed_specs_pass_through(self):
        specs: list[ToolSpec] = [{"name": "telec sessions list"}]
        with patch(_PATCH_IS_ALLOWED, return_value=True):
            result = filter_tool_specs("worker", specs)
        assert result == specs

    @pytest.mark.unit
    def test_denied_specs_filtered_out(self):
        specs: list[ToolSpec] = [{"name": "telec sessions list"}]
        with patch(_PATCH_IS_ALLOWED, return_value=False):
            result = filter_tool_specs("worker", specs)
        assert result == []


class TestGetAllowedTools:
    @pytest.mark.unit
    def test_allowed_tools_returned(self):
        tools = ["telec sessions list"]
        with patch(_PATCH_IS_ALLOWED, return_value=True):
            result = get_allowed_tools("worker", tools)
        assert result == tools

    @pytest.mark.unit
    def test_denied_tools_excluded(self):
        tools = ["telec sessions list"]
        with patch(_PATCH_IS_ALLOWED, return_value=False):
            result = get_allowed_tools("worker", tools)
        assert result == []


class TestGetExcludedTools:
    @pytest.mark.unit
    def test_returns_set(self):
        with patch("teleclaude.core.tool_access._collect_gated_paths", return_value=[]):
            result = get_excluded_tools("worker")
        assert isinstance(result, set)

    @pytest.mark.unit
    def test_gated_paths_excluded_when_denied(self):
        with (
            patch("teleclaude.core.tool_access._collect_gated_paths", return_value=["auth login"]),
            patch(_PATCH_IS_ALLOWED, return_value=False),
        ):
            result = get_excluded_tools("worker")
        assert "telec auth login" in result
