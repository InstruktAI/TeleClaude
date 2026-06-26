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


_CLAUDE_PASTED_TEXT_PREFIX = "[Pasted text "


def classify_prompt_delivery(output: str, text: str, active_agent: str | None) -> PromptDeliveryObservation:
    """Classify whether ``text`` is absent, stuck in live input, or submitted."""
    target = _normalize_text(text).strip()
    if not target:
        return PromptDeliveryObservation(PromptDeliveryState.ABSENT, "")

    agent = resolve_parser_agent(active_agent)
    if agent is AgentName.CODEX:
        live_input, has_submit_boundary = extract_prompt_block(output)
        normalized_live = _normalize_text(live_input).strip()
        if _contains_codex_target(normalized_live, target):
            state = PromptDeliveryState.SUBMITTED if has_submit_boundary else PromptDeliveryState.IN_INPUT
            return PromptDeliveryObservation(state, normalized_live)
        return PromptDeliveryObservation(PromptDeliveryState.ABSENT, normalized_live)

    normalized_output = _normalize_text(output)
    live_region = _extract_marker_live_region(normalized_output, target, agent)
    if agent is AgentName.CLAUDE and _CLAUDE_PASTED_TEXT_PREFIX in live_region:
        if _claude_collapsed_paste_matches_target(live_region, target):
            return PromptDeliveryObservation(PromptDeliveryState.IN_INPUT, live_region.strip())
        return PromptDeliveryObservation(PromptDeliveryState.ABSENT, live_region.strip())
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
    return stripped.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")


def _contains_target(haystack: str, target: str) -> bool:
    return target in haystack


def _contains_codex_target(haystack: str, target: str) -> bool:
    if _contains_target(haystack, target):
        return True
    return _fold_prompt_whitespace(target) in _fold_prompt_whitespace(haystack)


def _fold_prompt_whitespace(text: str) -> str:
    return " ".join(text.split())


def _extract_marker_live_region(output: str, target: str, agent: AgentName) -> str:
    lines = output.rstrip().split("\n")
    if agent is AgentName.GEMINI:
        return _extract_gemini_live_region(lines, target)
    marker = agent.prompt_marker.strip()
    if not marker:
        return ""
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].strip().startswith(marker):
            if agent is AgentName.CLAUDE:
                return _extract_claude_live_input_block(lines[idx:])
            return "\n".join(lines[idx:])
    return ""


def _extract_claude_live_input_block(lines: list[str]) -> str:
    input_lines: list[str] = []
    for line in lines:
        if _is_claude_input_boundary(line):
            break
        input_lines.append(line)
    return "\n".join(input_lines)


def _claude_collapsed_paste_matches_target(live_region: str, target: str) -> bool:
    visible_live = live_region.split(_CLAUDE_PASTED_TEXT_PREFIX, 1)[0]
    visible_lines = _canonical_claude_prompt_lines(visible_live)
    if not visible_lines:
        return False
    target_lines = _canonical_claude_prompt_lines(target)
    return target_lines[: len(visible_lines)] == visible_lines


def _canonical_claude_prompt_lines(text: str) -> list[str]:
    lines: list[str] = []
    marker = AgentName.CLAUDE.prompt_marker.strip()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if marker and line.startswith(marker):
            line = line[len(marker) :].strip()
        if line:
            lines.append(line)
    return lines


def _is_claude_input_boundary(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped) <= {"─"}


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
