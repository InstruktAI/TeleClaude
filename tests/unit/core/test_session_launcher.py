"""Characterization tests for teleclaude.core.session_launcher."""

from __future__ import annotations

import pytest

from teleclaude.core.models import SessionLaunchIntent, SessionLaunchKind

# Public API (create_session, create_agent_session) is async with infrastructure deps;
# _intent_to_auto_command is the pure logic under test.
from teleclaude.core.session_launcher import _intent_to_auto_command


class TestIntentToAutoCommand:
    @pytest.mark.unit
    def test_empty_kind_returns_none(self):
        intent = SessionLaunchIntent(kind=SessionLaunchKind.EMPTY)
        result = _intent_to_auto_command(intent)
        assert result is None

    @pytest.mark.unit
    def test_agent_kind_with_complete_intent_returns_command(self):
        intent = SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT,
            agent="claude",
            thinking_mode="slow",
        )
        result = _intent_to_auto_command(intent)
        assert result is not None
        assert "claude" in result
        assert "slow" in result

    @pytest.mark.unit
    def test_agent_kind_missing_thinking_mode_returns_none(self):
        intent = SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT,
            agent="claude",
            thinking_mode=None,
        )
        result = _intent_to_auto_command(intent)
        assert result is None

    @pytest.mark.unit
    def test_agent_then_message_builds_quoted_command(self):
        intent = SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
            agent="claude",
            thinking_mode="fast",
            message="hello world",
        )
        result = _intent_to_auto_command(intent)
        assert result is not None
        assert "agent_then_message" in result
        # shlex.quote wraps the message in single quotes
        assert "'hello world'" in result

    @pytest.mark.unit
    def test_agent_resume_with_session_includes_native_id(self):
        intent = SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_RESUME,
            agent="codex",
            native_session_id="native-abc",
        )
        result = _intent_to_auto_command(intent)
        assert result is not None
        assert "agent_resume" in result
        assert "native-abc" in result

    @pytest.mark.unit
    def test_agent_resume_without_native_id_returns_command(self):
        intent = SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_RESUME,
            agent="claude",
        )
        result = _intent_to_auto_command(intent)
        assert result is not None
        assert "agent_resume" in result
        assert "claude" in result
