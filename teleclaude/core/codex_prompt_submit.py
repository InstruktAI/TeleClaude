"""Codex prompt and tool-lane parsing helpers for polling-driven effects."""

import re

from instrukt_ai_logging import get_logger

from teleclaude.utils import strip_ansi_codes

logger = get_logger(__name__)

CODEX_PROMPT_MARKER = "›"
CODEX_PROMPT_LIVE_DISTANCE = 4
CODEX_TOOL_ACTION_LOOKBACK_LINES = 120

CODEX_AGENT_MARKERS = frozenset(
    {
        "•",
        "◦",
        "✶",
        "✦",
        "✧",
        "✴",
        "✸",
        "✹",
        "✺",
        "★",
        "☆",
        "●",
        "○",
        "◆",
        "◇",
    }
)

_ANSI_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
_ANSI_BOLD_TOKEN_RE = re.compile(r"\x1b\[[0-9;]*1m([A-Za-z][A-Za-z_-]{1,40})\x1b\[[0-9;]*m")
_ACTION_WORD_RE = re.compile(r"^([A-Za-z][A-Za-z_-]{1,40})")
_TREE_CONTINUATION_PREFIX_RE = re.compile(r"^(?:[│┃┆┊|]+\s*|[├└]\s*)+")
_CODEX_TOOL_ACTION_WORDS = frozenset(
    {
        "Applied",
        "Called",
        "Created",
        "Deleted",
        "Edited",
        "Explored",
        "Listed",
        "Moved",
        "Opened",
        "Ran",
        "Read",
        "Searched",
        "Updated",
        "Wrote",
    }
)


def _strip_ansi(text: str) -> str:
    return strip_ansi_codes(text)


def _has_sgr_param(text: str, target: str) -> bool:
    for match in _ANSI_SGR_RE.finditer(text):
        params = [p for p in match.group(1).split(";") if p]
        if target in params:
            return True
    return False


def _is_suggestion_styled(text: str) -> bool:
    return _has_sgr_param(text, "2") or _has_sgr_param(text, "3")


def _strip_suggestion_segments(text: str) -> str:
    if "\x1b[" not in text:
        return text

    out: list[str] = []
    active_suggestion_style = False
    idx = 0
    while idx < len(text):
        if text[idx] == "\x1b":
            match = _ANSI_SGR_RE.match(text, idx)
            if match:
                params = [p for p in match.group(1).split(";") if p]
                if not params or "0" in params:
                    active_suggestion_style = False
                else:
                    if "22" in params and "2" not in params:
                        active_suggestion_style = False
                    if "23" in params and "3" not in params:
                        active_suggestion_style = False
                    if "2" in params or "3" in params:
                        active_suggestion_style = True
                idx = match.end()
                continue
        if not active_suggestion_style:
            out.append(text[idx])
        idx += 1
    return "".join(out)


def _extract_prompt_block(output: str) -> tuple[str, bool]:  # pylint: disable=too-many-branches,too-many-locals,too-many-return-statements
    """Extract the current prompt block and whether a submit boundary follows it."""
    lines = output.rstrip().split("\n")
    if not lines:
        return "", False

    start_index = max(0, len(lines) - 60)
    prompt_idx = -1
    for idx in range(len(lines) - 1, start_index - 1, -1):
        clean_line = _strip_ansi(lines[idx].strip())
        if clean_line.startswith(CODEX_PROMPT_MARKER):
            prompt_idx = idx
            break

    if prompt_idx < 0:
        return "", False

    prompt_line = lines[prompt_idx]
    marker_pos = prompt_line.find(CODEX_PROMPT_MARKER)
    if marker_pos == -1:
        return "", False

    raw_after = prompt_line[marker_pos + len(CODEX_PROMPT_MARKER) :]
    raw_after_without_suggestion = _strip_suggestion_segments(raw_after)
    if _is_suggestion_styled(raw_after) and not _strip_ansi(raw_after_without_suggestion).strip():
        logger.trace("[CODEX] Skipping suggestion-styled text: %r", _strip_ansi(raw_after).strip()[:30])
        return "", False

    parts: list[str] = []
    first = _strip_ansi(raw_after_without_suggestion).strip()
    if first:
        parts.append(first)

    has_submit_boundary = False
    for line in lines[prompt_idx + 1 :]:
        clean_line = _strip_ansi(line)
        stripped = clean_line.strip()
        if _is_live_agent_marker_line(line):
            has_submit_boundary = True
            break
        if _is_compact_dimmed_agent_boundary_line(line):
            has_submit_boundary = True
            break
        if stripped and stripped[0] in CODEX_AGENT_MARKERS:
            continue
        if stripped.startswith(CODEX_PROMPT_MARKER):
            break
        line_without_suggestion = _strip_suggestion_segments(line)
        if _is_suggestion_styled(line) and not _strip_ansi(line_without_suggestion).strip():
            continue
        parts.append(_strip_ansi(line_without_suggestion).rstrip())

    if (len(lines) - 1 - prompt_idx) >= CODEX_PROMPT_LIVE_DISTANCE:
        return "", False

    text = "\n".join(parts).strip()
    if not text:
        return "", has_submit_boundary
    return text, has_submit_boundary


def _find_recent_tool_action(output: str) -> tuple[str, str, str] | None:  # pyright: ignore[reportUnusedFunction]
    lines = output.rstrip().split("\n")
    start_index = max(0, len(lines) - CODEX_TOOL_ACTION_LOOKBACK_LINES)
    for idx in range(len(lines) - 1, start_index - 1, -1):
        raw_line = lines[idx]
        clean_line = _strip_ansi(raw_line).strip()
        if not clean_line or clean_line[0] not in CODEX_AGENT_MARKERS:
            continue
        tail = clean_line[1:].strip()
        if not tail:
            continue
        match = _ACTION_WORD_RE.match(tail)
        action_word = match.group(1) if match else None
        bold_match = _ANSI_BOLD_TOKEN_RE.search(raw_line)
        bold_word = bold_match.group(1) if bold_match else None

        def _preview_for(action: str) -> str:
            detail = ""
            if action_word and tail.startswith(action_word):  # pylint: disable=cell-var-from-loop
                detail = tail[len(action_word) :].strip()  # pylint: disable=cell-var-from-loop

            if not detail:
                for continuation_idx in range(idx + 1, min(len(lines), idx + 4)):  # pylint: disable=cell-var-from-loop
                    continuation = _strip_ansi(lines[continuation_idx]).strip()
                    if not continuation:
                        continue
                    if continuation.startswith(CODEX_PROMPT_MARKER):
                        break
                    if continuation[0] in CODEX_AGENT_MARKERS:
                        break
                    continuation = _TREE_CONTINUATION_PREFIX_RE.sub("", continuation).strip()
                    if continuation:
                        detail = continuation
                        break

            detail = _TREE_CONTINUATION_PREFIX_RE.sub("", detail).strip()
            return f"{action} {detail}".strip() if detail else action

        if action_word in _CODEX_TOOL_ACTION_WORDS:
            return action_word, clean_line, _preview_for(action_word)
        if bold_word and (bold_word in _CODEX_TOOL_ACTION_WORDS or bold_word == action_word):
            return bold_word, clean_line, _preview_for(bold_word)
    return None


def _is_live_agent_responding(output: str) -> bool:  # pyright: ignore[reportUnusedFunction]
    lines = output.rstrip().split("\n")
    return any(_is_live_agent_marker_line(line) for line in lines[-10:])


def _find_prompt_input(output: str) -> str:
    text, _ = _extract_prompt_block(output)
    return text


def _has_agent_marker(output: str) -> bool:
    lines = output.rstrip().split("\n")
    for line in lines[-10:]:
        clean_line = _strip_ansi(line.strip())
        if clean_line and clean_line[0] in CODEX_AGENT_MARKERS:
            return True
    return False


def _has_live_prompt_marker(output: str) -> bool:
    return _find_live_prompt_line_index(output) is not None


def _find_live_prompt_line_index(output: str) -> int | None:
    lines = output.rstrip().split("\n")
    start_index = max(0, len(lines) - 10)
    for idx in range(len(lines) - 1, start_index - 1, -1):
        line = lines[idx]
        clean_line = _strip_ansi(line).strip()
        if not clean_line:
            continue
        if clean_line.startswith(CODEX_PROMPT_MARKER):
            return idx
        if clean_line.startswith("?") and "shortcut" in clean_line.lower():
            continue
        if clean_line[0] in CODEX_AGENT_MARKERS:
            return None
    return None


def has_live_prompt_marker(output: str) -> bool:
    """Public readiness helper for detecting a live Codex prompt."""
    return _has_live_prompt_marker(output)


def find_live_prompt_line_index(output: str) -> int | None:
    """Return the visible line index of the last live Codex prompt, if present."""
    return _find_live_prompt_line_index(output)


def _is_live_agent_marker_line(line: str) -> bool:
    clean_line = _strip_ansi(line).strip()
    if not clean_line or clean_line[0] not in CODEX_AGENT_MARKERS:
        return False
    tail = clean_line[1:].strip()
    if not tail:
        return True
    normalized = tail.lower()
    if "esc to interrupt" in normalized:
        return True
    if normalized.startswith(("working", "thinking", "sublimating", "planning", "analyzing")):
        return True
    return False


def _is_compact_dimmed_agent_boundary_line(line: str) -> bool:
    clean_line = _strip_ansi(line).strip()
    if not clean_line or clean_line[0] not in CODEX_AGENT_MARKERS:
        return False

    marker = clean_line[0]
    marker_pos = line.find(marker)
    if marker_pos < 0:
        return False
    prefix = line[:marker_pos]
    if not _has_sgr_param(prefix, "2"):
        return False

    tail = clean_line[1:].strip()
    if not tail:
        return True
    return len(tail) <= 24 and len(tail.split()) <= 4


__all__ = [
    "_find_prompt_input",
    "_has_agent_marker",
]
