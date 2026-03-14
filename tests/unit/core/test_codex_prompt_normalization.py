"""Characterization tests for teleclaude.core.codex_prompt_normalization."""

from __future__ import annotations

import pytest

from teleclaude.core.codex_prompt_normalization import normalize_codex_next_command


class TestNormalizeCodexNextCommand:
    @pytest.mark.unit
    def test_empty_text_returns_empty(self):
        result = normalize_codex_next_command("codex", "")
        assert result == ""

    @pytest.mark.unit
    def test_non_codex_agent_returns_unchanged(self):
        result = normalize_codex_next_command("claude", "/next-build my-slug")
        assert result == "/next-build my-slug"

    @pytest.mark.unit
    def test_none_agent_returns_unchanged(self):
        result = normalize_codex_next_command(None, "/next-build my-slug")
        assert result == "/next-build my-slug"

    @pytest.mark.unit
    def test_codex_next_command_gets_prompts_prefix(self):
        result = normalize_codex_next_command("codex", "/next-build my-slug")
        assert result == "/prompts:next-build my-slug"

    @pytest.mark.unit
    def test_codex_next_build_normalized(self):
        result = normalize_codex_next_command("codex", "/next-build my-slug")
        assert "/prompts:next-build" in result

    @pytest.mark.unit
    def test_codex_already_normalized_unchanged(self):
        result = normalize_codex_next_command("codex", "/prompts:next-build my-slug")
        assert result == "/prompts:next-build my-slug"

    @pytest.mark.unit
    def test_codex_non_next_command_unchanged(self):
        result = normalize_codex_next_command("codex", "/other-command arg")
        assert result == "/other-command arg"

    @pytest.mark.unit
    def test_codex_agent_name_case_insensitive(self):
        result = normalize_codex_next_command("CODEX", "/next-build")
        assert "/prompts:next-build" in result
