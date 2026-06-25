"""Prompt-state classification for confirmed tmux user-turn delivery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from teleclaude.core.agents import AgentName, resolve_parser_agent
from teleclaude.core.codex_prompt_submit import extract_prompt_block
from teleclaude.utils import strip_ansi_codes


class PromptDeliveryState(StrEnum):
    """Observed delivery state for a target user-turn payload."""

    ABSENT = "absent"
    IN_INPUT = "in_input"
    SUBMITTED = "submitted"


@dataclass(frozen=True)
class PromptDeliveryObservation:
    """Classified pane state for a target user-turn payload."""

    state: PromptDeliveryState
    live_input: str


def classify_prompt_delivery(output: str, text: str, active_agent: str | None) -> PromptDeliveryObservation:
    """Classify whether ``text`` is absent, stuck in live input, or submitted."""
    target = _normalize_text(text).strip()
    if not target:
        return PromptDeliveryObservation(PromptDeliveryState.ABSENT, "")

    agent = resolve_parser_agent(active_agent)
    if agent is AgentName.CODEX:
        live_input, has_submit_boundary = extract_prompt_block(output)
        normalized_live = _normalize_text(live_input).strip()
        if _contains_target(normalized_live, target):
            state = PromptDeliveryState.SUBMITTED if has_submit_boundary else PromptDeliveryState.IN_INPUT
            return PromptDeliveryObservation(state, normalized_live)
        return PromptDeliveryObservation(PromptDeliveryState.ABSENT, normalized_live)

    normalized_output = _normalize_text(output)
    live_region = _extract_marker_live_region(normalized_output, target, agent)
    if _contains_target(live_region, target):
        state = (
            PromptDeliveryState.IN_INPUT
            if _target_is_terminal_in_region(live_region, target, agent)
            else PromptDeliveryState.SUBMITTED
        )
        return PromptDeliveryObservation(state, live_region.strip())
    return PromptDeliveryObservation(PromptDeliveryState.ABSENT, live_region.strip())


def _normalize_text(text: str) -> str:
    stripped = strip_ansi_codes(text or "")
    return stripped.replace("\r\n", "\n").replace("\r", "\n")


def _contains_target(haystack: str, target: str) -> bool:
    return target in haystack


def _extract_marker_live_region(output: str, target: str, agent: AgentName) -> str:
    lines = output.rstrip().split("\n")
    if agent is AgentName.GEMINI:
        return _extract_gemini_live_region(lines, target)
    marker = agent.prompt_marker.strip()
    if not marker:
        return ""
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].strip().startswith(marker):
            return "\n".join(lines[idx:])
    return ""


def _extract_gemini_live_region(lines: list[str], target: str) -> str:
    del target
    footer_idx = -1
    for idx in range(len(lines) - 1, -1, -1):
        if AgentName.GEMINI.prompt_marker in lines[idx]:
            footer_idx = idx
            break
    if footer_idx >= 0:
        return "\n".join(lines[max(0, footer_idx - 20) : footer_idx + 1])
    return ""


def _target_is_terminal_in_region(region: str, target: str, agent: AgentName) -> bool:
    target_idx = region.rfind(target)
    if target_idx < 0:
        return False
    after_target = region[target_idx + len(target) :]
    return _only_prompt_chrome(after_target, agent)


def _only_prompt_chrome(text: str, agent: AgentName) -> bool:
    marker = agent.prompt_marker.strip()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if marker and marker in stripped:
            continue
        return False
    return True
