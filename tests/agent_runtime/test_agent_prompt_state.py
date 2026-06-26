"""Prompt-state classification for agent TUI input panes."""

from __future__ import annotations

from teleclaude.core.agent_prompt_state import PromptDeliveryState, classify_prompt_delivery
from teleclaude.core.agents import AgentName


def test_claude_collapsed_paste_placeholder_counts_as_live_input() -> None:
    target = (
        "/next-prepare per-domain-symlink-single-owner\n\n"
        "ADDITIONAL CONTEXT:\n"
        "human_in_loop: false\n"
        "additional lines hidden by Claude"
    )
    output = f"""
 ▐▛███▜▌   Claude Code v2.1.193
────────────────────────────────────────────────────────────────
{AgentName.CLAUDE.prompt_marker} /next-prepare per-domain-symlink-single-owner

  ADDITIONAL CONTEXT:
  human_in_loop: false
  [Pasted text #2 +4 lines]
────────────────────────────────────────────────────────────────
  Model: Opus 4.8
"""

    observation = classify_prompt_delivery(output, target, "claude")

    assert observation.state is PromptDeliveryState.IN_INPUT


def test_claude_collapsed_paste_placeholder_from_previous_prompt_is_ignored() -> None:
    target = "/next-prepare per-domain-symlink-single-owner\n\nADDITIONAL CONTEXT:\nhuman_in_loop: false"
    output = f"""
{AgentName.CLAUDE.prompt_marker} /next-prepare old
  [Pasted text #1 +3 lines]
────────────────────────────────────────────────────────────────
old response
{AgentName.CLAUDE.prompt_marker}
────────────────────────────────────────────────────────────────
"""

    observation = classify_prompt_delivery(output, target, "claude")

    assert observation.state is PromptDeliveryState.ABSENT
