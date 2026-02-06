"""Polling coordinator for tmux output streaming.

Extracted from daemon.py to reduce file size and improve organization.
Handles polling lifecycle orchestration and event routing to message manager.
"""

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import session_cleanup, tmux_bridge
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    TeleClaudeEvents,
    UserPromptSubmitPayload,
)
from teleclaude.core.output_poller import (
    DirectoryChanged,
    OutputChanged,
    OutputPoller,
    ProcessExited,
)
from teleclaude.core.session_utils import split_project_path_and_subdir
from teleclaude.utils import strip_ansi_codes

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

# Codex input detection - simple marker-based approach
# Detect text after "› " prompt, emit when agent marker appears
CODEX_INPUT_MAX_CHARS = 70  # Field size for last_input

# Codex TUI markers
CODEX_PROMPT_MARKER = "›"  # User input prompt line
# Agent "thinking/working" markers - Codex uses animated symbols
# These indicate agent has started responding (user input complete)
CODEX_AGENT_MARKERS = frozenset(
    {
        "•",  # Bullet - "Working"
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

_ANSI_DIM_RE = re.compile(r"\x1b\[2m")  # Dim text
_ANSI_ITALIC_RE = re.compile(r"\x1b\[3m")  # Italic text


def _strip_ansi(text: str) -> str:
    """Remove all ANSI escape codes from text."""
    return strip_ansi_codes(text)


def _is_suggestion_styled(text: str) -> bool:
    """Check if text contains dim or italic ANSI styling (indicates a suggestion)."""
    return bool(_ANSI_DIM_RE.search(text) or _ANSI_ITALIC_RE.search(text))


@dataclass
class CodexInputState:
    """Per-session state for Codex user input detection.

    Simple marker-based approach:
    - Track text seen after "› " prompt marker
    - When agent marker appears, emit the captured input
    - Fast-poll after idle→active transition for quicker detection
    """

    last_prompt_input: str = ""  # Last seen text after › prompt
    last_output_change_time: float = 0.0  # For idle detection
    fast_poll_task: "asyncio.Task[None] | None" = None  # Running fast-poll task


# Fast poll settings
FAST_POLL_INTERVAL_S = 0.1  # 100ms between polls
FAST_POLL_TIMEOUT_S = 10.0  # Give up after 10 seconds
IDLE_THRESHOLD_S = 3.0  # Session is idle after 3s of no output change


# Per-session Codex input tracking state
_codex_input_state: dict[str, CodexInputState] = {}


def _find_prompt_input(output: str) -> str:
    """Find user input text after the › prompt marker.

    Returns empty string if:
    - No › line found
    - Text after › is suggestion-styled (dim/italic)
    - No text after ›
    """
    lines = output.rstrip().split("\n")

    # Search from end to find the most recent prompt line
    for line in reversed(lines[-20:]):
        clean_line = _strip_ansi(line.strip())
        if clean_line.startswith(CODEX_PROMPT_MARKER):
            # Get raw text after marker (preserves ANSI for styling check)
            marker_pos = line.find(CODEX_PROMPT_MARKER)
            if marker_pos == -1:
                continue
            raw_after = line[marker_pos + len(CODEX_PROMPT_MARKER) :]

            # Skip if suggestion-styled (dim/italic)
            if _is_suggestion_styled(raw_after):
                logger.debug(
                    "[CODEX] Skipping suggestion-styled text: %r",
                    _strip_ansi(raw_after).strip()[:30],
                )
                continue

            # Extract clean text
            text = _strip_ansi(raw_after).strip()
            if text:
                return text[:CODEX_INPUT_MAX_CHARS]

    return ""


def _has_agent_marker(output: str) -> bool:
    """Check if agent is responding (agent marker in recent lines)."""
    lines = output.rstrip().split("\n")
    for line in lines[-10:]:
        clean_line = _strip_ansi(line.strip())
        if clean_line and clean_line[0] in CODEX_AGENT_MARKERS:
            return True
    return False


async def _fast_poll_for_marker(session_id: str, captured_input: str) -> None:
    """Fast-poll tmux for agent marker after user input detected.

    Polls every 100ms until agent marker found or timeout.
    Emits user_prompt_submit when marker detected.
    """
    tmux_name = f"tc_{session_id[:8]}"
    start_time = time.time()

    logger.debug(
        "[CODEX %s] Starting fast poll for agent marker, input: %r",
        session_id[:8],
        captured_input[:30],
    )

    try:
        while time.time() - start_time < FAST_POLL_TIMEOUT_S:
            output = await tmux_bridge.capture_pane(tmux_name)
            if _has_agent_marker(output):
                logger.info(
                    "Fast poll detected agent marker for Codex session %s: %d chars: %r",
                    session_id[:8],
                    len(captured_input),
                    captured_input[:50],
                )

                payload = UserPromptSubmitPayload(
                    prompt=captured_input,
                    session_id=session_id,
                    raw={"synthetic": True, "source": "codex_fast_poll"},
                )
                context = AgentEventContext(
                    session_id=session_id,
                    event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
                    data=payload,
                )
                event_bus.emit(TeleClaudeEvents.AGENT_EVENT, context)

                # Clear state after emit
                state = _codex_input_state.get(session_id)
                if state:
                    state.last_prompt_input = ""
                return

            await asyncio.sleep(FAST_POLL_INTERVAL_S)

        logger.debug(
            "[CODEX %s] Fast poll timeout after %.1fs",
            session_id[:8],
            FAST_POLL_TIMEOUT_S,
        )
    except asyncio.CancelledError:
        logger.debug("[CODEX %s] Fast poll cancelled", session_id[:8])
    except Exception as e:
        logger.error("[CODEX %s] Fast poll error: %s", session_id[:8], e, exc_info=True)
    finally:
        # Clear task reference
        state = _codex_input_state.get(session_id)
        if state:
            state.fast_poll_task = None


async def _maybe_emit_codex_input(
    session_id: str,
    active_agent: str | None,
    current_output: str,
    output_changed: bool,
) -> None:
    """Detect and emit synthetic user_prompt_submit for Codex sessions.

    Two detection paths:
    1. Normal: When agent marker appears in regular polling, emit captured input
    2. Fast-poll: When session goes idle→active with input, start 100ms polling

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

    # Find current prompt input (text after ›)
    current_input = _find_prompt_input(current_output)

    # Check if agent is responding
    agent_responding = _has_agent_marker(current_output)

    if agent_responding:
        # Cancel fast poll if running (we'll emit from here)
        if state.fast_poll_task and not state.fast_poll_task.done():
            state.fast_poll_task.cancel()
            state.fast_poll_task = None

        # Agent started responding - emit what we captured
        if state.last_prompt_input:
            logger.info(
                "Emitting synthetic user_prompt_submit for Codex session %s: %d chars: %r",
                session_id[:8],
                len(state.last_prompt_input),
                state.last_prompt_input[:50],
            )

            payload = UserPromptSubmitPayload(
                prompt=state.last_prompt_input,
                session_id=session_id,
                raw={"synthetic": True, "source": "codex_output_polling"},
            )
            context = AgentEventContext(
                session_id=session_id,
                event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
                data=payload,
            )
            event_bus.emit(TeleClaudeEvents.AGENT_EVENT, context)

            # Clear state after emit
            state.last_prompt_input = ""
        else:
            logger.debug("[CODEX %s] Agent marker found but no input to emit", session_id[:8])

        # Update last change time
        state.last_output_change_time = current_time
    else:
        # No agent marker - track current input and check for idle→active
        if current_input:
            if current_input != state.last_prompt_input:
                logger.debug(
                    "[CODEX %s] Tracking input: %r",
                    session_id[:8],
                    current_input[:50],
                )
            state.last_prompt_input = current_input

            # Check if this is idle→active transition (user started typing after idle)
            time_since_last = current_time - state.last_output_change_time
            was_idle = time_since_last >= IDLE_THRESHOLD_S
            fast_poll_running = state.fast_poll_task and not state.fast_poll_task.done()

            if was_idle and not fast_poll_running:
                logger.debug(
                    "[CODEX %s] Idle→active transition detected (idle %.1fs), starting fast poll",
                    session_id[:8],
                    time_since_last,
                )
                state.fast_poll_task = asyncio.create_task(_fast_poll_for_marker(session_id, current_input))

        # Update last change time only when output actually changed
        if output_changed:
            state.last_output_change_time = current_time


def _cleanup_codex_input_state(session_id: str) -> None:
    """Clean up Codex input tracking state when session ends."""
    state = _codex_input_state.pop(session_id, None)
    if state and state.fast_poll_task and not state.fast_poll_task.done():
        state.fast_poll_task.cancel()


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

                # Detect user input for Codex sessions (no hook support)
                # Fire-and-forget: best-effort, doesn't block polling loop
                async def _codex_input_wrapper() -> None:
                    try:
                        await _maybe_emit_codex_input(
                            session_id=event.session_id,
                            active_agent=session.active_agent,
                            current_output=clean_output,
                            output_changed=True,  # OutputChanged event means output changed
                        )
                    except Exception as e:
                        logger.error("[CODEX] Error in input detection: %s", e, exc_info=True)

                asyncio.create_task(_codex_input_wrapper())

                # Unified output handling - ALL sessions use send_output_update
                start_time = time.time()
                logger.debug("[COORDINATOR %s] Calling send_output_update...", session_id[:8])
                await adapter_client.send_output_update(
                    session,
                    clean_output,
                    event.started_at,
                    event.last_changed_at,
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
