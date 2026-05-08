"""Tests for teleclaude.output_projection.visibility — internal-text detection."""

from __future__ import annotations

import pytest

from teleclaude.output_projection.visibility import (
    is_agent_cli_internal_text,
    is_internal_user_text,
)


class TestIsInternalUserText:
    @pytest.mark.unit
    def test_teleclaude_system_prefix(self):
        assert is_internal_user_text("[TeleClaude Checkpoint] something") is True

    @pytest.mark.unit
    def test_stop_hook_feedback(self):
        text = "Stop hook feedback:\n[TeleClaude Checkpoint] - Context-aware checkpoint\n\nChanged: daemon code"
        assert is_internal_user_text(text) is True

    @pytest.mark.unit
    def test_pretooluse_hook_feedback(self):
        assert is_internal_user_text("PreToolUse hook feedback:\nblocked") is True

    @pytest.mark.unit
    def test_task_notification_wrapper(self):
        assert is_internal_user_text("<task-notification>content</task-notification>") is True

    @pytest.mark.unit
    def test_system_reminder_wrapper(self):
        assert is_internal_user_text("<system-reminder>content</system-reminder>") is True

    @pytest.mark.unit
    def test_generic_xml_prefix_is_internal(self):
        text = '<hook_prompt hook_run_id="stop:2:/Users/Morriz/.codex/hooks.json">[TeleClaude Checkpoint] - Context-aware checkpoint'
        assert is_internal_user_text(text) is True

    @pytest.mark.unit
    def test_normal_user_text_passes(self):
        assert is_internal_user_text("fix the bug please") is False

    @pytest.mark.unit
    def test_leading_whitespace_stripped(self):
        assert is_internal_user_text("  [TeleClaude Test] padded") is True
        assert is_internal_user_text("  Stop hook feedback:\nstuff") is True
        assert is_internal_user_text('  <hook_prompt hook_run_id="stop:2">wrapped') is True


class TestIsAgentCliInternalText:
    """``is_agent_cli_internal_text`` strips agent-CLI runtime artifacts only.

    Bracket-prefixed identity headers (``[TeleClaude …]``, ``[Orchestrator …]``)
    are NOT classified as internal — brackets are receiver-side identity markers
    and must survive projection so peer mirrors and human-facing renders can
    show them. The wider ``is_internal_user_text`` adds the ``[TeleClaude``
    rule for hook-receiver checkpoint-reset semantics."""

    @pytest.mark.unit
    def test_teleclaude_bracket_is_not_agent_cli_internal(self):
        """Bracket markers are identity headers, not delete cues. The projector
        must keep them so peers see who sent what."""
        assert is_agent_cli_internal_text("[TeleClaude - Linked output (s) on h]\n\nbody") is False

    @pytest.mark.unit
    def test_orchestrator_bracket_is_not_agent_cli_internal(self):
        assert is_agent_cli_internal_text("[Orchestrator (orch) on local]\n\nbody") is False

    @pytest.mark.unit
    def test_hook_feedback_prefix_is_agent_cli_internal(self):
        assert is_agent_cli_internal_text("Stop hook feedback:\n…") is True

    @pytest.mark.unit
    def test_system_reminder_wrapper_is_agent_cli_internal(self):
        assert is_agent_cli_internal_text("<system-reminder>x</system-reminder>") is True

    @pytest.mark.unit
    def test_xml_style_prefix_is_agent_cli_internal(self):
        assert is_agent_cli_internal_text('<hook_prompt id="1">…') is True

    @pytest.mark.unit
    def test_plain_user_text_is_not_agent_cli_internal(self):
        assert is_agent_cli_internal_text("fix the bug please") is False
