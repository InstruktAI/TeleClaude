"""Prompt-delivery pane classification guards."""

from __future__ import annotations

import pytest

from teleclaude.core.agent_prompt_state import PromptDeliveryState, classify_prompt_delivery
from teleclaude.core.agents import AgentName

pytestmark = [pytest.mark.functional]

_TARGET = "fixed restart stimulus"


def test_codex_scrollback_target_with_empty_live_prompt_is_absent() -> None:
    codex_prompt = AgentName.CODEX.prompt_marker.strip()
    output = "\n".join(
        [
            f"{codex_prompt} {_TARGET}",
            "\u2022 old response",
            f"{codex_prompt} ",
        ]
    )

    observation = classify_prompt_delivery(output, _TARGET, AgentName.CODEX.value)

    assert observation.state == PromptDeliveryState.ABSENT
    assert not observation.live_input


def test_codex_current_prompt_boundary_is_submitted_hint() -> None:
    codex_prompt = AgentName.CODEX.prompt_marker.strip()
    output = "\n".join(
        [
            f"{codex_prompt} {_TARGET}",
            "\u2022 thinking",
        ]
    )

    observation = classify_prompt_delivery(output, _TARGET, AgentName.CODEX.value)

    assert observation.state == PromptDeliveryState.SUBMITTED
    assert observation.live_input == _TARGET


def test_claude_scrollback_target_with_empty_live_prompt_is_absent() -> None:
    output = "\n".join(
        [
            f"{AgentName.CLAUDE.prompt_marker} {_TARGET}",
            "old response",
            f"{AgentName.CLAUDE.prompt_marker} ",
        ]
    )

    observation = classify_prompt_delivery(output, _TARGET, AgentName.CLAUDE.value)

    assert observation.state == PromptDeliveryState.ABSENT
