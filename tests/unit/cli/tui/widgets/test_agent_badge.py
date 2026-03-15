"""Characterization tests for teleclaude.cli.tui.widgets.agent_badge.

AgentBadge is a minimal Textual Widget whose render() uses resolve_style() to
determine styling. Without a mounted app, the testable surface is limited to
the default reactive value.
"""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.widgets.agent_badge import AgentBadge


@pytest.mark.unit
def test_agent_badge_is_importable() -> None:
    assert AgentBadge is not None


@pytest.mark.unit
def test_agent_badge_default_agent_is_claude() -> None:
    badge = AgentBadge()
    assert badge.agent == "claude"
