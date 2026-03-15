"""Characterization tests for teleclaude.helpers.agent_types."""

from __future__ import annotations

import pytest

from teleclaude.helpers.agent_types import AgentName, ThinkingMode


def test_agent_name_choices_match_declared_enum_order() -> None:
    assert AgentName.choices() == ("claude", "gemini", "codex")


def test_agent_name_from_str_normalizes_whitespace_and_case() -> None:
    assert AgentName.from_str("  GeMiNi  ") is AgentName.GEMINI


def test_agent_name_members_compare_as_strings() -> None:
    assert isinstance(AgentName.CLAUDE, str)
    assert AgentName.CLAUDE == "claude"  # type: ignore[comparison-overlap]


def test_agent_name_from_str_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        AgentName.from_str("cursor")


def test_thinking_mode_choices_match_declared_enum_order() -> None:
    assert ThinkingMode.choices() == ("fast", "med", "slow", "deep")


def test_thinking_mode_from_str_normalizes_whitespace_and_case() -> None:
    assert ThinkingMode.from_str("  SLoW  ") is ThinkingMode.SLOW


def test_thinking_mode_members_compare_as_strings() -> None:
    assert isinstance(ThinkingMode.DEEP, str)
    assert ThinkingMode.DEEP == "deep"  # type: ignore[comparison-overlap]


def test_thinking_mode_from_str_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        ThinkingMode.from_str("turbo")
