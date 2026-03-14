"""Characterization tests for teleclaude.core.agents."""

from __future__ import annotations

import pytest

from teleclaude.core.agents import (
    AgentName,
    get_known_agents,
    is_agent_title,
    normalize_agent_name,
    resolve_parser_agent,
)


class TestAgentName:
    @pytest.mark.unit
    def test_claude_value(self):
        assert AgentName.CLAUDE.value == "claude"

    @pytest.mark.unit
    def test_codex_value(self):
        assert AgentName.CODEX.value == "codex"

    @pytest.mark.unit
    def test_gemini_value(self):
        assert AgentName.GEMINI.value == "gemini"

    @pytest.mark.unit
    def test_from_str_claude(self):
        assert AgentName.from_str("claude") == AgentName.CLAUDE

    @pytest.mark.unit
    def test_from_str_is_case_insensitive(self):
        assert AgentName.from_str("CLAUDE") == AgentName.CLAUDE
        assert AgentName.from_str("  Codex  ") == AgentName.CODEX

    @pytest.mark.unit
    def test_from_str_unknown_raises(self):
        with pytest.raises(ValueError):
            AgentName.from_str("unknown_agent")

    @pytest.mark.unit
    def test_choices_returns_tuple_of_strings(self):
        choices = AgentName.choices()
        assert isinstance(choices, tuple)
        assert "claude" in choices
        assert "codex" in choices
        assert "gemini" in choices


class TestGetKnownAgents:
    @pytest.mark.unit
    def test_returns_tuple(self):
        agents = get_known_agents()
        assert isinstance(agents, tuple)

    @pytest.mark.unit
    def test_contains_expected_agents(self):
        agents = get_known_agents()
        assert "claude" in agents
        assert "codex" in agents
        assert "gemini" in agents


class TestResolveParserAgent:
    @pytest.mark.unit
    def test_none_returns_claude(self):
        assert resolve_parser_agent(None) == AgentName.CLAUDE

    @pytest.mark.unit
    def test_empty_string_returns_claude(self):
        assert resolve_parser_agent("") == AgentName.CLAUDE

    @pytest.mark.unit
    def test_known_agent_resolved(self):
        assert resolve_parser_agent("codex") == AgentName.CODEX

    @pytest.mark.unit
    def test_unknown_value_returns_claude(self):
        assert resolve_parser_agent("unknown_xyz") == AgentName.CLAUDE


class TestNormalizeAgentName:
    @pytest.mark.unit
    def test_valid_name_returns_canonical(self):
        assert normalize_agent_name("claude") == "claude"

    @pytest.mark.unit
    def test_case_insensitive(self):
        assert normalize_agent_name("GEMINI") == "gemini"

    @pytest.mark.unit
    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            normalize_agent_name("not_an_agent")


class TestIsAgentTitle:
    @pytest.mark.unit
    def test_title_with_claude_returns_true(self):
        assert is_agent_title("claude code") is True

    @pytest.mark.unit
    def test_title_with_codex_returns_true(self):
        assert is_agent_title("codex session") is True

    @pytest.mark.unit
    def test_unrelated_title_returns_false(self):
        assert is_agent_title("bash terminal") is False

    @pytest.mark.unit
    def test_empty_title_returns_false(self):
        assert is_agent_title("") is False
