"""Binary live-composer occupancy classification for tmux delivery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from teleclaude.core.agents import AgentName, resolve_parser_agent
from teleclaude.utils import strip_ansi_codes


class PromptDeliveryState(StrEnum):
    """Whether the active agent composer can safely receive a submitted turn."""

    EMPTY = "empty"
    OCCUPIED = "occupied"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class PromptDeliveryObservation:
    """Content-independent live-composer occupancy observation."""

    state: PromptDeliveryState


_ANSI_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


def classify_prompt_delivery(
    output: str,
    active_agent: str | None,
) -> PromptDeliveryObservation:
    """Classify only whether any operator-authored composer input exists."""
    agent = resolve_parser_agent(active_agent)
    live_region = _extract_marker_live_region(output, agent)
    if not live_region:
        return PromptDeliveryObservation(PromptDeliveryState.AMBIGUOUS)
    if _live_region_has_input(live_region, agent):
        return PromptDeliveryObservation(PromptDeliveryState.OCCUPIED)
    return PromptDeliveryObservation(PromptDeliveryState.EMPTY)


def _normalize_text(text: str) -> str:
    stripped = strip_ansi_codes(text or "")
    return stripped.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")


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


def _is_codex_prompt_chrome_line(line: str) -> bool:
    normalized = _fold_prompt_whitespace(line).lower()
    return ("shift + tab" in normalized and "esc dismiss" in normalized) or (
        normalized.startswith("gpt-") and "\u00b7" in normalized
    )


def _extract_marker_live_region(output: str, agent: AgentName) -> str:
    lines = output.rstrip().split("\n")
    if agent is AgentName.CODEX:
        return _extract_codex_live_region(lines)
    if agent is AgentName.GEMINI:
        return _extract_gemini_live_region(lines)
    if agent is AgentName.DEEPSEEK:
        return _extract_deepseek_live_region(lines)
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
        input_lines.append(line)
        if _is_claude_input_boundary(line):
            break
    return "\n".join(input_lines)


def _is_claude_input_boundary(line: str) -> bool:
    stripped = strip_ansi_codes(line).strip()
    return bool(stripped) and set(stripped) <= {"─"}


def _extract_codex_live_region(lines: list[str]) -> str:
    marker = AgentName.CODEX.prompt_marker.strip()
    if not marker:
        return ""
    for idx in range(len(lines) - 1, -1, -1):
        if strip_ansi_codes(lines[idx].strip()).startswith(marker):
            return _extract_codex_live_input_block(lines[idx:])
    return ""


def _extract_codex_live_input_block(lines: list[str]) -> str:
    input_lines: list[str] = []
    marker = AgentName.CODEX.prompt_marker.strip()
    previous_was_blank = False
    for idx, line in enumerate(lines):
        if idx > 0 and _is_codex_prompt_chrome_line(line):
            input_lines.append(line)
            break
        normalized = strip_ansi_codes(line).strip()
        if idx > 0 and previous_was_blank and "\x1b[" in line and normalized.count("\u00b7") >= 2:
            break
        if idx > 0 and marker and strip_ansi_codes(line.strip()).startswith(marker):
            input_lines.append(line)
            break
        input_lines.append(line)
        previous_was_blank = not normalized
    return "\n".join(input_lines)


def _extract_deepseek_live_region(lines: list[str]) -> str:
    """Extract the DSH input area: the bottom-most prompt-marker line (U+276F)
    plus any continuation lines, stopping at the horizontal-rule border below
    the input box. The DSH TUI renders status/hint lines beneath that border;
    they must not be treated as live input.
    """
    marker = AgentName.DEEPSEEK.prompt_marker.strip()
    if not marker:
        return ""
    for idx in range(len(lines) - 1, -1, -1):
        if strip_ansi_codes(lines[idx].strip()).startswith(marker):
            input_lines: list[str] = []
            for line in lines[idx:]:
                if input_lines and _is_horizontal_rule_line(line):
                    break
                input_lines.append(line)
            return "\n".join(input_lines)
    return ""


def _extract_gemini_live_region(lines: list[str]) -> str:
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
    return _extract_gemini_bordered_live_region(lines)


def _extract_gemini_bordered_live_region(lines: list[str]) -> str:
    for idx in range(len(lines) - 1, -1, -1):
        if not strip_ansi_codes(lines[idx]).strip().startswith(">"):
            continue
        has_border_above = idx > 0 and _is_horizontal_rule_line(lines[idx - 1])
        has_border_below = idx + 1 < len(lines) and _is_horizontal_rule_line(lines[idx + 1])
        if not has_border_above and not has_border_below:
            continue
        end_idx = idx + 1
        while end_idx < len(lines):
            stripped = strip_ansi_codes(lines[end_idx]).strip()
            if _is_horizontal_rule_line(lines[end_idx]) or AgentName.GEMINI.prompt_marker in stripped:
                end_idx += 1
                break
            end_idx += 1
        return "\n".join(lines[idx:end_idx])
    return ""


def _live_region_has_input(live_region: str, agent: AgentName) -> bool:
    """Return whether the marker-bounded composer contains any non-chrome text."""
    for raw_line in live_region.splitlines():
        if _is_prompt_chrome_line(raw_line, agent):
            continue
        input_part = _strip_live_prompt_marker(raw_line, agent)
        input_part = _strip_generated_segments(input_part)
        if _normalize_text(input_part).strip():
            return True
    return False


def _is_prompt_chrome_line(raw_line: str, agent: AgentName) -> bool:
    stripped = strip_ansi_codes(raw_line).strip()
    if not stripped:
        return True
    if _is_horizontal_rule_line(raw_line):
        return True
    if agent is AgentName.GEMINI and stripped == AgentName.GEMINI.prompt_marker:
        return True
    if agent is AgentName.CODEX and _is_codex_prompt_chrome_line(raw_line):
        return True
    if agent is AgentName.CLAUDE and _is_claude_input_boundary(raw_line):
        return True
    return False


def _is_horizontal_rule_line(raw_line: str) -> bool:
    stripped = strip_ansi_codes(raw_line).strip()
    return bool(stripped) and set(stripped) <= {"─"}


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
