"""Polling coordinator for tmux output streaming.

Extracted from daemon.py to reduce file size and improve organization.
Handles polling lifecycle orchestration and event routing to message manager.
"""

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import session_cleanup, tmux_bridge
from teleclaude.core.db import db
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    AgentOutputPayload,
    UserPromptSubmitPayload,
)
from teleclaude.core.output_poller import (
    DirectoryChanged,
    OutputChanged,
    OutputPoller,
    ProcessExited,
)
from teleclaude.core.session_utils import split_project_path_and_subdir
from teleclaude.core.tool_activity import truncate_tool_preview
from teleclaude.utils import strip_ansi_codes

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

# Codex input detection - marker-pair approach
# Capture input block after "›" prompt and emit when submit boundary marker appears.
CODEX_INPUT_MAX_CHARS = 4000

# Codex TUI markers
CODEX_PROMPT_MARKER = "›"  # User input prompt line
CODEX_PROMPT_LIVE_DISTANCE = 4  # Prompt marker must be close to bottom unless submit boundary is found
CODEX_TOOL_ACTION_LOOKBACK_LINES = 120
# Agent "thinking/working" markers - Codex uses animated symbols
# These indicate agent has started responding (user input complete)
CODEX_AGENT_MARKERS = frozenset(
    {
        "•",  # Bullet - "Working"
        "◦",  # White bullet - "Planning/Diagnosing ... (esc to interrupt)"
        "✶",  # Six-pointed star - "Sublimating"
        "✦",  # Black four-pointed star
        "✧",  # White four-pointed star
        "✴",  # Eight-pointed black star
        "✸",  # Heavy eight-pointed star
        "✹",  # Twelve-pointed star
        "✺",  # Sixteen-pointed star
        "★",  # Black star
        "☆",  # White star
        "●",  # Black circle
        "○",  # White circle
        "◆",  # Black diamond
        "◇",  # White diamond
    }
)

_ANSI_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
_ANSI_BOLD_TOKEN_RE = re.compile(r"\x1b\[[0-9;]*1m([A-Za-z][A-Za-z_-]{1,40})\x1b\[[0-9;]*m")
_ACTION_WORD_RE = re.compile(r"^([A-Za-z][A-Za-z_-]{1,40})")

# Visible Codex action verbs in tmux output (bold in UI) that imply tool usage.
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
    """Remove all ANSI escape codes from text."""
    return strip_ansi_codes(text)


def _has_sgr_param(text: str, target: str) -> bool:
    """Return True when any SGR sequence contains the exact parameter."""
    for match in _ANSI_SGR_RE.finditer(text):
        params = [p for p in match.group(1).split(";") if p]
        if target in params:
            return True
    return False


def _is_suggestion_styled(text: str) -> bool:
    """Check if text contains dim or italic SGR styling (indicates a suggestion)."""
    return _has_sgr_param(text, "2") or _has_sgr_param(text, "3")


def _strip_suggestion_segments(text: str) -> str:
    """Remove only dim/italic-styled text segments (autocomplete suggestions)."""
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
    """Per-session state for Codex user input detection.

    Marker-boundary approach:
    - Track text seen after "› " prompt marker
    - Emit only when prompt text is no longer visible and output boundary indicates submit
    """

    last_prompt_input: str = ""  # Last seen text after › prompt
    last_emitted_prompt: str = ""  # Last emitted synthetic prompt (duplicate guard)
    last_output_change_time: float = 0.0
    submitted_for_current_response: bool = False  # Prevent duplicate emits during same response phase


@dataclass
class CodexTurnState:
    """Per-session state for synthetic codex turn/tool events."""

    turn_active: bool = False
    in_tool: bool = False
    prompt_visible_last: bool = False
    initialized: bool = False
    last_tool_signature: str = ""


# Per-session Codex input tracking state
_codex_input_state: dict[str, CodexInputState] = {}
_codex_turn_state: dict[str, CodexTurnState] = {}


def _mark_codex_turn_started(session_id: str) -> None:
    """Mark a Codex turn as active when user submit is inferred."""
    state = _codex_turn_state.get(session_id)
    if state is None:
        state = CodexTurnState()
        _codex_turn_state[session_id] = state
    state.turn_active = True


def seed_codex_prompt_from_message(session_id: str, prompt_text: str) -> None:
    """Seed Codex prompt buffer from authoritative user message dispatch.

    This hardens synthetic submit detection when prompt text is not visible in
    captured tmux snapshots (e.g. fast transitions), while emission still
    requires marker-based response boundaries.
    """
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
        logger.debug(
            "[CODEX %s] Seeded prompt from dispatch: %r",
            session_id[:8],
            clipped[:50],
        )

    state.last_prompt_input = clipped
    # New dispatched message starts a fresh turn-candidate.
    state.submitted_for_current_response = False


def _extract_prompt_block(output: str) -> tuple[str, bool]:
    """Extract prompt block and whether a submit boundary marker is present below it.

    Returns:
        (prompt_text, has_submit_boundary)
    """
    lines = output.rstrip().split("\n")
    if not lines:
        return "", False

    # Find the most recent prompt marker near the live bottom region.
    start_index = max(0, len(lines) - 60)
    prompt_idx = -1
    for idx in range(len(lines) - 1, start_index - 1, -1):
        line = lines[idx]
        clean_line = _strip_ansi(line.strip())
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
        logger.debug(
            "[CODEX] Skipping suggestion-styled text: %r",
            _strip_ansi(raw_after).strip()[:30],
        )
        return "", False

    parts: list[str] = []
    first = _strip_ansi(raw_after_without_suggestion).strip()
    if first:
        parts.append(first)

    has_submit_boundary = False
    for line in lines[prompt_idx + 1 :]:
        clean_line = _strip_ansi(line)
        stripped = clean_line.strip()
        # Live status/spinner marker is an authoritative submit boundary.
        if _is_live_agent_marker_line(line):
            has_submit_boundary = True
            break
        # Some fast turns skip spinner/status and go straight to a compact assistant
        # marker line (e.g. "• hi"). Treat those as boundaries when marker is dimmed.
        if _is_compact_dimmed_agent_boundary_line(line):
            has_submit_boundary = True
            break
        # Other marker lines below prompt are treated as stale scrollback.
        if stripped and stripped[0] in CODEX_AGENT_MARKERS:
            continue
        if stripped.startswith(CODEX_PROMPT_MARKER):
            # New prompt marker means previous block ended.
            break
        line_without_suggestion = _strip_suggestion_segments(line)
        if _is_suggestion_styled(line) and not _strip_ansi(line_without_suggestion).strip():
            continue
        parts.append(_strip_ansi(line_without_suggestion).rstrip())

    # Ignore stale scrollback prompt markers that are too far above live bottom
    # unless we already detected a submit boundary marker below this prompt block.
    if not has_submit_boundary and (len(lines) - 1 - prompt_idx) >= CODEX_PROMPT_LIVE_DISTANCE:
        return "", False

    text = "\n".join(parts).strip()
    if not text:
        return "", has_submit_boundary
    return text[:CODEX_INPUT_MAX_CHARS], has_submit_boundary


def _find_prompt_input(output: str) -> str:  # pyright: ignore[reportUnusedFunction]  # used in tests
    """Backward-compatible helper for tests/callers expecting prompt text only."""
    text, _ = _extract_prompt_block(output)
    return text


def _has_agent_marker(output: str) -> bool:  # pyright: ignore[reportUnusedFunction]  # used in tests
    """Check if agent is responding (agent marker in recent lines)."""
    lines = output.rstrip().split("\n")
    for line in lines[-10:]:
        clean_line = _strip_ansi(line.strip())
        if clean_line and clean_line[0] in CODEX_AGENT_MARKERS:
            return True
    return False


def _has_live_prompt_marker(output: str) -> bool:
    """Return True when a live prompt marker is visible at the pane bottom."""
    lines = output.rstrip().split("\n")
    for line in reversed(lines[-10:]):
        clean_line = _strip_ansi(line).strip()
        if not clean_line:
            continue
        if clean_line.startswith(CODEX_PROMPT_MARKER):
            return True
        # Codex UI footer hints can appear below the prompt and should be ignored.
        if clean_line.startswith("?") and "shortcut" in clean_line.lower():
            continue
        if clean_line[0] in CODEX_AGENT_MARKERS:
            return False
    return False


def _is_live_agent_marker_line(line: str) -> bool:
    """Return True for short spinner/status lines, not full assistant bullet text."""
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
    """Return True for compact assistant lines that reliably mark response start."""
    clean_line = _strip_ansi(line).strip()
    if not clean_line or clean_line[0] not in CODEX_AGENT_MARKERS:
        return False

    marker = clean_line[0]
    marker_pos = line.find(marker)
    if marker_pos < 0:
        return False
    prefix = line[:marker_pos]
    # Codex renders agent marker glyphs dimmed. Require that signature to avoid
    # treating stale/plain scrollback bullets as submit boundaries.
    if not _has_sgr_param(prefix, "2"):
        return False

    tail = clean_line[1:].strip()
    if not tail:
        return True
    # Accept concise assistant openings (e.g. "• hi", "• done", "• Ran ...").
    return len(tail) <= 24 and len(tail.split()) <= 4


def _find_recent_tool_action(output: str) -> tuple[str, str, str] | None:
    """Find recent visible tool action and return (action_word, signature, preview)."""
    lines = output.rstrip().split("\n")
    for raw_line in reversed(lines[-CODEX_TOOL_ACTION_LOOKBACK_LINES:]):
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
        if action_word in _CODEX_TOOL_ACTION_WORDS:
            return action_word, clean_line, tail
        if bold_word and (bold_word in _CODEX_TOOL_ACTION_WORDS or bold_word == action_word):
            return bold_word, clean_line, tail
    return None


def _is_live_agent_responding(output: str) -> bool:
    """Return True when visible pane effects indicate the agent is actively responding."""
    lines = output.rstrip().split("\n")
    return any(_is_live_agent_marker_line(line) for line in lines[-10:])


async def _emit_synthetic_codex_event(
    session_id: str,
    event_type: str,
    emit_agent_event: Callable[[AgentEventContext], Awaitable[None]],
    *,
    tool_name: str | None = None,
    tool_preview: str | None = None,
) -> None:
    """Emit a synthetic Codex event through the regular agent event handler."""
    raw = {
        "synthetic": True,
        "source": "codex_output_effects",
    }
    if tool_name:
        raw["tool_name"] = tool_name
    if tool_preview:
        raw["tool_preview"] = truncate_tool_preview(tool_preview)

    if event_type == AgentHookEvents.TOOL_USE:
        payload = AgentOutputPayload(raw=raw)
    elif event_type == AgentHookEvents.TOOL_DONE:
        payload = AgentOutputPayload(raw=raw)
    else:
        return

    await emit_agent_event(
        AgentEventContext(
            session_id=session_id,
            event_type=event_type,
            data=payload,
        )
    )


async def _maybe_emit_codex_turn_events(
    session_id: str,
    active_agent: str | None,
    current_output: str,
    emit_agent_event: Callable[[AgentEventContext], Awaitable[None]],
    *,
    enable_synthetic_turn_events: bool,
) -> None:
    """Infer synthetic tool events from visible Codex terminal effects."""
    if active_agent != "codex" or not enable_synthetic_turn_events:
        return

    state = _codex_turn_state.get(session_id)
    if state is None:
        state = CodexTurnState()
        _codex_turn_state[session_id] = state

    prompt_visible = _has_live_prompt_marker(current_output)
    responding = _is_live_agent_responding(current_output)
    tool_match = _find_recent_tool_action(current_output)
    raw_tool_action = tool_match[0] if tool_match else None
    raw_tool_signature = tool_match[1] if tool_match else ""
    raw_tool_preview = tool_match[2] if tool_match else ""
    if not state.initialized:
        state.initialized = True
        state.prompt_visible_last = prompt_visible
        if prompt_visible and raw_tool_signature:
            # Baseline stale scrollback on first sight to avoid startup false positives.
            state.last_tool_signature = raw_tool_signature

    is_new_tool_signature = bool(raw_tool_signature and raw_tool_signature != state.last_tool_signature)
    # Prompt-visible snapshots are common; ignore known stale signatures but allow new ones.
    if prompt_visible and not is_new_tool_signature:
        tool_action = None
    else:
        tool_action = raw_tool_action

    # Track tool lane transitions while prompt is not visible.
    if tool_action:
        if is_new_tool_signature:
            state.last_tool_signature = raw_tool_signature
        state.turn_active = True
        if not state.in_tool:
            await _emit_synthetic_codex_event(
                session_id,
                AgentHookEvents.TOOL_USE,
                emit_agent_event,
                tool_name=tool_action,
                tool_preview=raw_tool_preview,
            )
            state.in_tool = True
    elif state.in_tool:
        await _emit_synthetic_codex_event(
            session_id,
            AgentHookEvents.TOOL_DONE,
            emit_agent_event,
        )
        state.in_tool = False

    # Any live spinner/status marker means turn is still active.
    if responding:
        state.turn_active = True
        state.prompt_visible_last = False
        return

    # Prompt visible + not responding => authoritative tool-lane end.
    # Do NOT emit synthetic agent_stop; Codex stop is hook-authoritative.
    if prompt_visible:
        should_finalize_tool_lane = (
            state.turn_active or state.in_tool or ((not state.prompt_visible_last) and raw_tool_action is not None)
        )
        if should_finalize_tool_lane:
            if state.in_tool:
                await _emit_synthetic_codex_event(
                    session_id,
                    AgentHookEvents.TOOL_DONE,
                    emit_agent_event,
                )
        state.turn_active = False
        state.in_tool = False
        state.prompt_visible_last = True
        return

    state.prompt_visible_last = False
    if tool_action:
        state.turn_active = True
        return


async def _maybe_emit_codex_input(
    session_id: str,
    active_agent: str | None,
    current_output: str,
    output_changed: bool,
    emit_agent_event: Callable[[AgentEventContext], Awaitable[None]],
) -> None:
    """Detect and emit synthetic user_prompt_submit for Codex sessions.

    Detection path:
    1. Marker boundary: agent marker appears and prompt text has cleared

    Args:
        session_id: Session ID
        active_agent: Current agent type
        current_output: Current tmux output
        output_changed: Whether output changed since last poll
    """
    if active_agent != "codex":
        return

    state = _codex_input_state.get(session_id)
    if state is None:
        state = CodexInputState()
        state.last_output_change_time = time.time()
        _codex_input_state[session_id] = state

    current_time = time.time()

    # Contract: prompt submit comes only from strict marker boundaries inside output.
    current_input, has_submit_boundary = _extract_prompt_block(current_output)

    # Check if agent is responding using live status markers only.
    # Fallback to live tool action lines when prompt is no longer visible.
    prompt_visible = _has_live_prompt_marker(current_output)
    recent_tool_action_match = _find_recent_tool_action(current_output)
    recent_tool_action = recent_tool_action_match[0] if recent_tool_action_match else None
    agent_responding = _is_live_agent_responding(current_output) or (
        recent_tool_action is not None and not prompt_visible
    )

    async def _emit_captured_input(source: str) -> bool:
        if not state.last_prompt_input:
            return False
        logger.info(
            "Emitting synthetic user_prompt_submit for Codex session %s: %d chars: %r",
            session_id[:8],
            len(state.last_prompt_input),
            state.last_prompt_input[:50],
        )
        payload = UserPromptSubmitPayload(
            prompt=state.last_prompt_input,
            session_id=session_id,
            raw={"synthetic": True, "source": source},
        )
        context = AgentEventContext(
            session_id=session_id,
            event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
            data=payload,
        )
        await emit_agent_event(context)
        _mark_codex_turn_started(session_id)
        state.last_emitted_prompt = state.last_prompt_input
        state.last_prompt_input = ""
        return True

    if current_input and current_input != state.last_prompt_input:
        logger.debug(
            "[CODEX %s] Tracking input: %r",
            session_id[:8],
            current_input[:50],
        )
    if current_input:
        state.last_prompt_input = current_input

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
            logger.debug("[CODEX %s] Agent marker found but no input to emit", session_id[:8])

        if emitted:
            state.submitted_for_current_response = True

    if not agent_responding and not strict_boundary:
        state.submitted_for_current_response = False

    # Update last change time only when output actually changed
    if output_changed:
        state.last_output_change_time = current_time


def _cleanup_codex_input_state(session_id: str) -> None:
    """Clean up Codex input tracking state when session ends."""
    _codex_input_state.pop(session_id, None)
    _codex_turn_state.pop(session_id, None)


_active_pollers: set[str] = set()
_poller_lock = asyncio.Lock()


async def is_polling(session_id: str) -> bool:
    """Check if a poller task is active for the session (in-memory only)."""
    async with _poller_lock:
        return session_id in _active_pollers


async def _register_polling(session_id: str) -> bool:
    """Register a poller task if one isn't active. Returns True if registered."""
    async with _poller_lock:
        if session_id in _active_pollers:
            return False
        _active_pollers.add(session_id)
        return True


async def _unregister_polling(session_id: str) -> None:
    """Unregister a poller task."""
    async with _poller_lock:
        _active_pollers.discard(session_id)


async def schedule_polling(
    session_id: str,
    tmux_session_name: str,
    output_poller: OutputPoller,
    adapter_client: "AdapterClient",
    get_output_file: Callable[[str], Path],
) -> bool:
    """Schedule polling in the background with an in-memory guard.

    Returns True if scheduled, False if a poller is already active.
    """
    if not await _register_polling(session_id):
        logger.warning(
            "Polling already active for session %s, ignoring duplicate request",
            session_id[:8],
        )
        return False

    asyncio.create_task(
        poll_and_send_output(
            session_id=session_id,
            tmux_session_name=tmux_session_name,
            output_poller=output_poller,
            adapter_client=adapter_client,
            get_output_file=get_output_file,
            _skip_register=True,
        )
    )
    return True


async def poll_and_send_output(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    session_id: str,
    tmux_session_name: str,
    output_poller: OutputPoller,
    adapter_client: "AdapterClient",
    get_output_file: Callable[[str], Path],
    _skip_register: bool = False,
) -> None:
    """Poll tmux output and send to all adapters for session.

    Pure orchestration - consumes events from poller, delegates to message manager.
    SINGLE RESPONSIBILITY: Owns the polling lifecycle for a session.

    Args:
        session_id: Session ID
        tmux_session_name: tmux session name
        output_poller: Output poller instance
        adapter_client: AdapterClient instance (broadcasts to all adapters)
        get_output_file: Function to get output file path for session
    """
    if not _skip_register:
        if not await _register_polling(session_id):
            logger.warning(
                "Polling already active for session %s, ignoring duplicate request",
                session_id[:8],
            )
            return

    # Get output file
    output_file = get_output_file(session_id)
    try:
        # Consume events from pure poller
        async for event in output_poller.poll(session_id, tmux_session_name, output_file):
            if isinstance(event, OutputChanged):
                logger.debug(
                    "[COORDINATOR %s] Received OutputChanged event from poller",
                    session_id[:8],
                )
                # Output is a rendered TUI snapshot (poller reads from raw stream)
                clean_output = event.output

                # Fetch session once for all operations
                session = await db.get_session(event.session_id)
                if not session:
                    logger.debug(
                        "Session %s missing during polling output; stopping poller",
                        event.session_id[:8],
                    )
                    return

                logger.trace(
                    "[COORDINATOR %s] Fetched session for output: digest=%s",
                    event.session_id[:8],
                    session.last_output_digest,
                )

                # Detect user input for Codex sessions (no hook support).
                # Keep this inline to avoid spawning unbounded background tasks
                # on high-frequency output updates.
                emit_handler = adapter_client.agent_event_handler
                if emit_handler:
                    try:
                        # Codex synthetic tool events come from visible terminal effects
                        # regardless of native session bindings.
                        synth_turn_events_enabled = (session.active_agent or "").lower() == "codex"
                        await _maybe_emit_codex_turn_events(
                            session_id=event.session_id,
                            active_agent=session.active_agent,
                            current_output=clean_output,
                            emit_agent_event=emit_handler,
                            enable_synthetic_turn_events=synth_turn_events_enabled,
                        )
                        await _maybe_emit_codex_input(
                            session_id=event.session_id,
                            active_agent=session.active_agent,
                            current_output=clean_output,
                            output_changed=True,  # OutputChanged event means output changed
                            emit_agent_event=emit_handler,
                        )
                    except Exception as e:
                        logger.error("[CODEX] Error in input detection: %s", e, exc_info=True)

                # Unified output handling - ALL sessions use send_output_update
                start_time = time.time()
                logger.debug("[COORDINATOR %s] Calling send_output_update...", session_id[:8])
                await adapter_client.send_output_update(
                    session,
                    clean_output,
                    event.started_at,
                    event.last_changed_at,
                )
                coordinator = getattr(adapter_client, "agent_coordinator", None)
                if coordinator:
                    try:
                        await coordinator.trigger_incremental_output(event.session_id)
                    except Exception:
                        logger.warning(
                            "Poller-triggered incremental output failed for %s",
                            event.session_id[:8],
                            exc_info=True,
                        )
                elapsed = time.time() - start_time
                logger.debug(
                    "[COORDINATOR %s] send_output_update completed in %.2fs",
                    session_id[:8],
                    elapsed,
                )

            elif isinstance(event, DirectoryChanged):
                # Directory changed - update session (db dispatcher handles title update)
                trusted_dirs = [d.path for d in config.computer.get_all_trusted_dirs()]
                project_path, subdir = split_project_path_and_subdir(event.new_path, trusted_dirs)
                await db.update_session(event.session_id, project_path=project_path, subdir=subdir)

            elif isinstance(event, ProcessExited):
                # Process exited - output is already clean from file
                clean_final_output = event.final_output

                # Fetch session once for all operations
                session = await db.get_session(event.session_id)
                if not session:
                    logger.debug(
                        "Session %s missing during process exit; stopping poller",
                        event.session_id[:8],
                    )
                    return

                # Unified output handling - ALL sessions use send_output_update
                if event.exit_code is not None:
                    # Exit with code - send final message via AdapterClient
                    await adapter_client.send_output_update(
                        session,
                        clean_final_output,
                        event.started_at,  # Use actual start time from poller
                        time.time(),
                        is_final=True,
                        exit_code=event.exit_code,
                    )
                    tmux_alive = True
                    if session.tmux_session_name:
                        tmux_alive = await tmux_bridge.session_exists(
                            session.tmux_session_name,
                            log_missing=False,
                        )
                    if not tmux_alive:
                        await session_cleanup.terminate_session(
                            event.session_id,
                            adapter_client,
                            reason="tmux_exited",
                            session=session,
                            kill_tmux=False,
                        )
                        logger.info(
                            "Terminated session %s after tmux exit (exit code: %d)",
                            event.session_id[:8],
                            event.exit_code,
                        )
                    else:
                        logger.info(
                            "Polling stopped for %s (exit code: %d), output file kept for downloads",
                            event.session_id[:8],
                            event.exit_code,
                        )
                else:
                    # Tmux session disappeared (no exit code). Do NOT terminate:
                    # allow auto-heal to recreate tmux and resume the session.
                    logger.warning(
                        "Tmux session missing for %s; leaving session active for auto-heal",
                        event.session_id[:8],
                    )
    except Exception as exc:
        logger.error("Polling failed for session %s: %s", session_id[:8], exc)
        try:
            await adapter_client.send_error_feedback(
                session_id,
                f"Polling error: {exc}",
            )
        except Exception as feedback_exc:
            logger.error(
                "Failed to send error feedback for session %s: %s",
                session_id[:8],
                feedback_exc,
            )
        raise

    finally:
        # Cleanup state
        await _unregister_polling(session_id)
        _cleanup_codex_input_state(session_id)
        # NOTE: Don't clear pending_deletions here - let _pre_handle_user_input handle deletion on next input
        # NOTE: Keep output_message_id in DB - it's reused for all commands in the session
        # Only cleared when session closes (/exit command)

        logger.debug("Polling ended for session %s", session_id[:8])
