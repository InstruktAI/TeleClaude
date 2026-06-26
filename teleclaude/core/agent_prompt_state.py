"""Prompt-state classification for confirmed tmux user-turn delivery."""

from __future__ import annotations

import re
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
_ANSI_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


def classify_prompt_delivery(
    output: str,
    text: str,
    active_agent: str | None,
) -> PromptDeliveryObservation:
    """Classify whether ``text`` is absent, stuck in live input, or submitted."""
    target = _normalize_text(text).strip()
    if not target:
        return PromptDeliveryObservation(PromptDeliveryState.ABSENT, "")

    agent = resolve_parser_agent(active_agent)
    if agent is AgentName.CODEX:
        live_input, has_submit_boundary = extract_prompt_block(output)
        normalized_live = _strip_codex_prompt_chrome(_normalize_text(live_input).strip())
        if _codex_prompt_matches_target(normalized_live, target):
            state = PromptDeliveryState.SUBMITTED if has_submit_boundary else PromptDeliveryState.IN_INPUT
            return PromptDeliveryObservation(state, normalized_live)
        return PromptDeliveryObservation(PromptDeliveryState.ABSENT, normalized_live)

    live_region = _extract_marker_live_region(output, target, agent)
    live_input = _normalize_live_region_input(live_region, agent)
    if agent is AgentName.CLAUDE and _CLAUDE_PASTED_TEXT_PREFIX in live_input:
        return PromptDeliveryObservation(PromptDeliveryState.ABSENT, live_input)
    if _contains_target(live_input, target):
        state = (
            PromptDeliveryState.IN_INPUT
            if _target_is_terminal_in_region(live_input, target, agent)
            else PromptDeliveryState.SUBMITTED
        )
        return PromptDeliveryObservation(state, live_input)
    return PromptDeliveryObservation(PromptDeliveryState.ABSENT, live_input)


def _normalize_text(text: str) -> str:
    stripped = strip_ansi_codes(text or "")
    return stripped.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")


def _contains_target(haystack: str, target: str) -> bool:
    return target in haystack


def _codex_prompt_matches_target(haystack: str, target: str) -> bool:
    return _fold_prompt_whitespace(_strip_codex_prompt_chrome(haystack)) == _fold_prompt_whitespace(target)


def _fold_prompt_whitespace(text: str) -> str:
    return " ".join(text.split())


def _strip_generated_segments(text: str) -> str:
    if "\x1b[" not in text:
        return text

    out: list[str] = []
    active_generated_style = False
    idx = 0
    while idx < len(text):
        if text[idx] == "\x1b":
            match = _ANSI_SGR_RE.match(text, idx)
            if match:
                params = [p for p in match.group(1).split(";") if p]
                if not params or "0" in params:
                    active_generated_style = False
                else:
                    if "22" in params and "2" not in params:
                        active_generated_style = False
                    if "23" in params and "3" not in params:
                        active_generated_style = False
                    if "2" in params or "3" in params:
                        active_generated_style = True
                idx = match.end()
                continue
        if not active_generated_style:
            out.append(text[idx])
        idx += 1
    return "".join(out)


def _strip_codex_prompt_chrome(text: str) -> str:
    lines = [line for line in text.splitlines() if not _is_codex_prompt_chrome_line(line)]
    return "\n".join(lines).strip()


def _is_codex_prompt_chrome_line(line: str) -> bool:
    normalized = _fold_prompt_whitespace(line).lower()
    return ("shift + tab" in normalized and "esc dismiss" in normalized) or (
        normalized.startswith("gpt-") and "\u00b7" in normalized
    )


def _extract_marker_live_region(output: str, target: str, agent: AgentName) -> str:
    lines = output.rstrip().split("\n")
    if agent is AgentName.GEMINI:
        return _extract_gemini_live_region(lines, target)
    marker = agent.prompt_marker.strip()
    if not marker:
        return ""
    for idx in range(len(lines) - 1, -1, -1):
        if strip_ansi_codes(lines[idx].strip()).startswith(marker):
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


def _is_claude_input_boundary(line: str) -> bool:
    stripped = strip_ansi_codes(line).strip()
    return bool(stripped) and set(stripped) <= {"─"}


def _extract_gemini_live_region(lines: list[str], target: str) -> str:
    del target
    footer_idx = -1
    for idx in range(len(lines) - 1, -1, -1):
        if AgentName.GEMINI.prompt_marker in strip_ansi_codes(lines[idx]):
            footer_idx = idx
            break
    if footer_idx >= 0:
        start_idx = footer_idx
        for idx in range(footer_idx - 1, max(-1, footer_idx - 20), -1):
            if strip_ansi_codes(lines[idx]).strip().startswith(">"):
                start_idx = idx
                break
        return "\n".join(lines[start_idx : footer_idx + 1])
    return ""


def _normalize_live_region_input(live_region: str, agent: AgentName) -> str:
    lines: list[str] = []
    for raw_line in live_region.splitlines():
        if _is_prompt_chrome_line(raw_line, agent):
            continue
        input_part = _strip_live_prompt_marker(raw_line, agent)
        input_part = _strip_generated_segments(input_part)
        normalized = _normalize_text(input_part).strip()
        if normalized:
            lines.append(normalized)
    return "\n".join(lines).strip()


def _is_prompt_chrome_line(raw_line: str, agent: AgentName) -> bool:
    stripped = strip_ansi_codes(raw_line).strip()
    if not stripped:
        return True
    if agent is AgentName.GEMINI and stripped == AgentName.GEMINI.prompt_marker:
        return True
    if agent is AgentName.CLAUDE and _is_claude_input_boundary(raw_line):
        return True
    return False


def _strip_live_prompt_marker(raw_line: str, agent: AgentName) -> str:
    marker = ">" if agent is AgentName.GEMINI else agent.prompt_marker.strip()
    if not marker:
        return raw_line
    marker_pos = raw_line.find(marker)
    if marker_pos < 0:
        return raw_line
    if strip_ansi_codes(raw_line[:marker_pos]).strip():
        return raw_line
    return raw_line[marker_pos + len(marker) :]


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
