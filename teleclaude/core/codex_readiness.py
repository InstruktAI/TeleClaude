"""Codex-only pane-quiet readiness detector.

Codex CLI v0.130+ does not reliably fire its native ``SessionStart`` hook on
cold ``thread_spawn`` — when the hook does fire, it arrives combined with the
first ``user_prompt_submit`` instead of at launch. The daemon's bootstrap
gate waits for ``AGENT_READY`` (emitted by the session_start handler), so the
60-second deadline expires and the queued message is dropped.

This module fills the gap with an out-of-band pane-quiet detector: scan the
tmux pane for Codex's live prompt marker ``›`` near the bottom of the view,
and verify the region above it stays stable for a brief quiet period. When
detected, the bootstrap synthesizes a ``session_start`` event itself so the
rest of the pipeline proceeds unchanged.

Salvaged from ``teleclaude/core/codex_prompt_submit.py`` (removed in
``eea6c62e8``) — only the live-prompt scan, not the tool-lane / agent-marker
parsing that became obsolete when native PreToolUse hooks landed.
"""

from __future__ import annotations

import asyncio
import hashlib
import time

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.utils import strip_ansi_codes

logger = get_logger(__name__)

CODEX_PROMPT_MARKER = "›"
# How close to the bottom of the pane the prompt line must be to count as live.
# Codex renders status lines (agent reasoning, model name) below the input
# prompt while a turn is running; a `›` buried more than this many lines from
# the bottom is from a previous turn, not the current input prompt.
CODEX_PROMPT_LIVE_DISTANCE = 4


def _find_codex_prompt_line(output: str) -> int | None:
    """Return the 0-based line index of the live Codex prompt marker, or None.

    Scans bottom-up for the last line whose first non-whitespace ANSI-stripped
    character is ``›``. Returns the index only when that line is within
    ``CODEX_PROMPT_LIVE_DISTANCE`` of the bottom — otherwise the marker is
    historical, not the live input prompt.
    """
    lines = output.split("\n")
    for idx in range(len(lines) - 1, -1, -1):
        stripped = strip_ansi_codes(lines[idx]).strip()
        if not stripped:
            continue
        if stripped.startswith(CODEX_PROMPT_MARKER):
            if (len(lines) - 1 - idx) >= CODEX_PROMPT_LIVE_DISTANCE:
                return None
            return idx
    return None


def _stability_digest(output: str, prompt_idx: int) -> str:
    """Hash the pre-prompt region used for the quiet-period stability check.

    The bottom of the pane keeps updating during animation (status spinners,
    "esc to interrupt" tickers) even when the agent is otherwise idle. Hashing
    the region ABOVE the prompt line lets us detect when meaningful output has
    stopped changing without being thrown off by status-bar flicker.
    """
    if prompt_idx <= 0:
        return ""
    lines = output.split("\n")[:prompt_idx]
    region = "\n".join(strip_ansi_codes(line).rstrip() for line in lines).rstrip()
    return hashlib.sha256(region.encode("utf-8", errors="replace")).hexdigest()


async def wait_for_codex_prompt(
    tmux_session_name: str,
    *,
    timeout_s: float,
    quiet_s: float = 0.5,
    poll_interval_s: float = 0.2,
) -> bool:
    """Wait for Codex's prompt to render and the pre-prompt region to settle.

    Returns True when the live prompt marker has been visible long enough for
    the region above it to remain unchanged for ``quiet_s`` seconds. Returns
    False when ``timeout_s`` elapses without that condition being met.

    No exception escapes: tmux capture failures degrade to "not yet ready"
    and the loop retries until the timeout.
    """
    deadline = time.monotonic() + timeout_s
    last_digest: str | None = None
    quiet_since: float | None = None

    while time.monotonic() < deadline:
        try:
            pane = await tmux_bridge.capture_pane(tmux_session_name)
        except Exception as exc:
            logger.debug("codex_readiness: pane capture failed (%s) — retrying", exc)
            pane = None

        if pane:
            prompt_idx = _find_codex_prompt_line(pane)
            if prompt_idx is not None:
                digest = _stability_digest(pane, prompt_idx)
                now = time.monotonic()
                if digest != last_digest:
                    last_digest = digest
                    quiet_since = now
                elif quiet_since is not None and (now - quiet_since) >= quiet_s:
                    logger.debug(
                        "codex_readiness: prompt settled tmux=%s quiet_s=%.2f",
                        tmux_session_name,
                        quiet_s,
                    )
                    return True
            else:
                last_digest = None
                quiet_since = None

        await asyncio.sleep(poll_interval_s)

    logger.debug(
        "codex_readiness: timed out tmux=%s timeout_s=%.1f",
        tmux_session_name,
        timeout_s,
    )
    return False
