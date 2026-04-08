"""Tests for teleclaude.output_projection.visibility — internal-text detection."""

from __future__ import annotations

import pytest

from teleclaude.output_projection.visibility import is_internal_user_text


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
    def test_normal_user_text_passes(self):
        assert is_internal_user_text("fix the bug please") is False

    @pytest.mark.unit
    def test_leading_whitespace_stripped(self):
        assert is_internal_user_text("  [TeleClaude Test] padded") is True
        assert is_internal_user_text("  Stop hook feedback:\nstuff") is True
