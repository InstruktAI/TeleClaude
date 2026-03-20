"""Agent readiness detection logic."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core import tmux_bridge
from teleclaude.core.agents import AgentName

if TYPE_CHECKING:
    from teleclaude.core.models._session import Session

logger = get_logger(__name__)


async def _capture_snapshot(tmux_session_name: str) -> tuple[str, str]:
    output = await tmux_bridge.capture_pane(tmux_session_name)
    if not output:
        return "", ""
    tail = output[-UI_MESSAGE_MAX_CHARS:]
    digest = hashlib.sha256(tail.encode("utf-8", errors="replace")).hexdigest()
    return tail, digest


async def wait_for_agent_ready(
    agent_name: str,
    session: Session,
    timeout_s: float,
    quiet_s: float,
    poll_interval_s: float = 0.2,
) -> tuple[bool, str]:
    """Wait for agent TUI to be stable and show prompt marker."""
    marker = AgentName.from_str(agent_name).prompt_marker
    deadline = time.monotonic() + timeout_s
    last_tail, last_digest = await _capture_snapshot(session.tmux_session_name)
    has_changed = False
    quiet_since: float | None = None

    while time.monotonic() < deadline:
        await asyncio.sleep(poll_interval_s)
        current_tail, current_digest = await _capture_snapshot(session.tmux_session_name)
        now = time.monotonic()

        if current_digest != last_digest:
            has_changed = True
            last_tail, last_digest = current_tail, current_digest
            quiet_since = now
            continue

        last_tail = current_tail

        if not has_changed or quiet_since is None:
            continue

        if now - quiet_since < quiet_s:
            continue

        if marker in current_tail:
            logger.debug(
                "readiness: settled with marker agent=%s quiet_s=%.1f",
                agent_name,
                quiet_s,
            )
            return True, current_tail

    elapsed = time.monotonic() - (deadline - timeout_s)
    logger.debug(
        "readiness: timed out agent=%s has_changed=%s elapsed=%.1fs",
        agent_name,
        has_changed,
        elapsed,
    )
    return False, last_tail
