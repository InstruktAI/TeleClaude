"""Codex prompt extraction and synthetic submit detection.

This module owns Codex-specific prompt parsing from tmux pane output.
`polling_coordinator` should only integrate it, not implement its details.
"""

import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from instrukt_ai_logging import get_logger

from teleclaude.core.events import AgentEventContext, AgentHookEvents, UserPromptSubmitPayload
from teleclaude.utils import strip_ansi_codes

logger = get_logger(__name__)

CODEX_INPUT_MAX_CHARS = 4000
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

_PASTED_CONTENT_PLACEHOLDER_RE = re.compile(r"^\[Pasted Content \d+ chars\]$")
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


def _is_codex_prompt_placeholder(prompt: str) -> bool:
    return bool(_PASTED_CONTENT_PLACEHOLDER_RE.fullmatch((prompt or "").strip()))


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


@dataclass
class CodexInputState:
    """Per-session state for Codex user input detection."""

    last_prompt_input: str = ""
    last_emitted_prompt: str = ""
    last_output_change_time: float = 0.0
    submitted_for_current_response: bool = False
    has_authoritative_seed: bool = False


_codex_input_state: dict[str, CodexInputState] = {}


def seed_codex_prompt_from_message(session_id: str, prompt_text: str) -> None:
    """Seed Codex prompt buffer from authoritative user message dispatch."""
    text = prompt_text.strip()
    if not text:
        return

    state = _codex_input_state.get(session_id)
    if state is None:
        state = CodexInputState()
        state.last_output_change_time = time.time()
        _codex_input_state[session_id] = state

    clipped = text[:CODEX_INPUT_MAX_CHARS]
    if clipped != state.last_prompt_input:
        logger.debug("[CODEX %s] Seeded prompt from dispatch: %r", session_id, clipped[:50])

    state.last_prompt_input = clipped
    state.submitted_for_current_response = False
    state.has_authoritative_seed = True


def cleanup_codex_prompt_state(session_id: str) -> None:
    _codex_input_state.pop(session_id, None)


def _extract_prompt_block(output: str) -> tuple[str, bool]:
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
        logger.debug("[CODEX] Skipping suggestion-styled text: %r", _strip_ansi(raw_after).strip()[:30])
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
    return text[:CODEX_INPUT_MAX_CHARS], has_submit_boundary


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
    lines = output.rstrip().split("\n")
    for line in reversed(lines[-10:]):
        clean_line = _strip_ansi(line).strip()
        if not clean_line:
            continue
        if clean_line.startswith(CODEX_PROMPT_MARKER):
            return True
        if clean_line.startswith("?") and "shortcut" in clean_line.lower():
            continue
        if clean_line[0] in CODEX_AGENT_MARKERS:
            return False
    return False


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


def _find_recent_tool_action(output: str) -> tuple[str, str, str] | None:
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
            if action_word and tail.startswith(action_word):
                detail = tail[len(action_word) :].strip()

            if not detail:
                for continuation_idx in range(idx + 1, min(len(lines), idx + 4)):
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


def _is_live_agent_responding(output: str) -> bool:
    lines = output.rstrip().split("\n")
    return any(_is_live_agent_marker_line(line) for line in lines[-10:])


async def maybe_emit_codex_input(
    session_id: str,
    active_agent: str | None,
    current_output: str,
    output_changed: bool,
    emit_agent_event: Callable[[AgentEventContext], Awaitable[None]],
    *,
    on_submit_emitted: Callable[[str], None] | None = None,
) -> None:
    """Detect and emit synthetic `USER_PROMPT_SUBMIT` events for Codex sessions."""
    if active_agent != "codex":
        return

    state = _codex_input_state.get(session_id)
    if state is None:
        state = CodexInputState()
        state.last_output_change_time = time.time()
        _codex_input_state[session_id] = state

    current_time = time.time()
    current_input, has_submit_boundary = _extract_prompt_block(current_output)
    prompt_visible = _has_live_prompt_marker(current_output)
    recent_tool_action_match = _find_recent_tool_action(current_output)
    recent_tool_action = recent_tool_action_match[0] if recent_tool_action_match else None
    agent_responding = _is_live_agent_responding(current_output) or (
        recent_tool_action is not None and not prompt_visible
    )

    async def _emit_captured_input(source: str) -> bool:
        if not state.last_prompt_input:
            return False
        if _is_codex_prompt_placeholder(state.last_prompt_input):
            logger.debug(
                "[CODEX %s] Ignoring synthetic placeholder prompt: %r",
                session_id,
                state.last_prompt_input[:50],
            )
            return False
        logger.info(
            "Emitting synthetic user_prompt_submit for Codex session %s: %d chars: %r",
            session_id,
            len(state.last_prompt_input),
            state.last_prompt_input[:50],
        )
        payload = UserPromptSubmitPayload(
            prompt=state.last_prompt_input,
            session_id=session_id,
            raw={"synthetic": True, "source": source},
        )
        await emit_agent_event(
            AgentEventContext(
                session_id=session_id,
                event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
                data=payload,
            )
        )
        if on_submit_emitted:
            on_submit_emitted(session_id)
        state.last_emitted_prompt = state.last_prompt_input
        state.last_prompt_input = ""
        state.has_authoritative_seed = False
        return True

    if current_input:
        if current_input != state.last_prompt_input:
            logger.debug("[CODEX %s] Tracking input: %r", session_id, current_input[:50])

        overwrite_seeded_with_shorter = (
            state.has_authoritative_seed
            and bool(state.last_prompt_input)
            and len(current_input) < len(state.last_prompt_input)
        )
        if overwrite_seeded_with_shorter:
            logger.debug(
                "[CODEX %s] Keeping authoritative seeded prompt over shorter snapshot (%d < %d)",
                session_id,
                len(current_input),
                len(state.last_prompt_input),
            )
        else:
            state.last_prompt_input = current_input
            state.has_authoritative_seed = False

    strict_boundary = bool(current_input and has_submit_boundary)
    transition_boundary = agent_responding and not current_input and bool(state.last_prompt_input)
    if strict_boundary and not state.submitted_for_current_response:
        emitted = await _emit_captured_input("codex_output_polling")
        if emitted:
            state.submitted_for_current_response = True
    elif agent_responding and not state.submitted_for_current_response:
        emitted = False
        if transition_boundary:
            emitted = await _emit_captured_input("codex_marker_transition")
        elif not current_input:
            logger.debug("[CODEX %s] Agent marker found but no input to emit", session_id)

        if emitted:
            state.submitted_for_current_response = True

    if not agent_responding and not strict_boundary:
        state.submitted_for_current_response = False

    if output_changed:
        state.last_output_change_time = current_time


__all__ = [
    "_find_prompt_input",
    "_has_agent_marker",
    "cleanup_codex_prompt_state",
    "maybe_emit_codex_input",
    "seed_codex_prompt_from_message",
]
