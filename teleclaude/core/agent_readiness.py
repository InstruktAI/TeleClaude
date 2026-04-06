"""Agent readiness detection logic."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from re import Pattern
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core import tmux_bridge
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_prompt_submit import find_live_prompt_line_index
from teleclaude.utils import strip_ansi_codes

if TYPE_CHECKING:
    from teleclaude.core.models._session import Session

logger = get_logger(__name__)


@dataclass(frozen=True)
class PromptMatch:
    """Location of a live prompt within the visible pane."""

    line_index: int


@dataclass(frozen=True)
class MarkerPromptProfile:
    """Default readiness profile for marker-based CLIs."""

    marker: str
    match_mode: str = "startswith"
    ignored_above_patterns: tuple[Pattern[str], ...] = field(default_factory=tuple)

    def locate_prompt(self, output: str) -> PromptMatch | None:
        """Locate the last visible prompt line for a marker-based CLI."""
        lines = _normalized_lines(output)
        for idx in range(len(lines) - 1, -1, -1):
            line = lines[idx].strip()
            if not line:
                continue
            if self.match_mode == "contains":
                if self.marker in line:
                    return PromptMatch(line_index=idx)
                continue
            if line.startswith(self.marker):
                return PromptMatch(line_index=idx)
        return None

    def build_stability_view(self, output: str, prompt: PromptMatch) -> str:
        """Build the normalized pre-prompt region used for quiet detection."""
        return _build_default_stability_view(
            output,
            prompt.line_index,
            ignored_above_patterns=self.ignored_above_patterns,
        )


@dataclass(frozen=True)
class CodexPromptProfile:
    """Readiness profile for Codex terminal output."""

    ignored_above_patterns: tuple[Pattern[str], ...] = field(default_factory=tuple)

    def locate_prompt(self, output: str) -> PromptMatch | None:
        """Locate the last live Codex prompt line within the visible pane."""
        line_index = find_live_prompt_line_index(output)
        if line_index is None:
            return None
        return PromptMatch(line_index=line_index)

    def build_stability_view(self, output: str, prompt: PromptMatch) -> str:
        """Build the normalized pre-prompt region used for quiet detection."""
        return _build_default_stability_view(
            output,
            prompt.line_index,
            ignored_above_patterns=self.ignored_above_patterns,
        )


def _normalized_lines(output: str) -> list[str]:
    """Return the visible pane as ANSI-stripped lines."""
    if not output:
        return []
    tail = output[-UI_MESSAGE_MAX_CHARS:]
    return [strip_ansi_codes(line).rstrip() for line in tail.split("\n")]


def _build_default_stability_view(
    output: str,
    prompt_line_index: int,
    *,
    ignored_above_patterns: tuple[Pattern[str], ...] = (),
) -> str:
    """Build the normalized pre-prompt region used for quiet detection."""
    lines = _normalized_lines(output)
    if prompt_line_index <= 0:
        return ""

    stable_lines: list[str] = []
    for line in lines[:prompt_line_index]:
        stripped = line.strip()
        if stripped and any(pattern.search(stripped) for pattern in ignored_above_patterns):
            continue
        stable_lines.append(line)
    return "\n".join(stable_lines).rstrip()


_READINESS_PROFILES: dict[AgentName, MarkerPromptProfile | CodexPromptProfile] = {
    AgentName.CLAUDE: MarkerPromptProfile(marker=AgentName.CLAUDE.prompt_marker),
    AgentName.GEMINI: MarkerPromptProfile(marker=AgentName.GEMINI.prompt_marker, match_mode="contains"),
    AgentName.CODEX: CodexPromptProfile(),
}


def _get_readiness_profile(agent: AgentName) -> MarkerPromptProfile | CodexPromptProfile:
    """Return the readiness profile for the active agent."""
    return _READINESS_PROFILES[agent]


async def _capture_snapshot(agent: AgentName, tmux_session_name: str) -> tuple[str, str, bool]:
    output = await tmux_bridge.capture_pane(tmux_session_name)
    if not output:
        return "", "", False

    tail = output[-UI_MESSAGE_MAX_CHARS:]
    profile = _get_readiness_profile(agent)
    prompt = profile.locate_prompt(tail)
    if prompt is None:
        return tail, "", False

    stability_view = profile.build_stability_view(tail, prompt)
    digest = hashlib.sha256(stability_view.encode("utf-8", errors="replace")).hexdigest()
    return tail, digest, True


async def wait_for_agent_ready(
    agent_name: str,
    session: Session,
    timeout_s: float,
    quiet_s: float,
    poll_interval_s: float = 0.2,
) -> tuple[bool, str]:
    """Wait for agent output above the visible prompt to settle."""
    agent = AgentName.from_str(agent_name)
    deadline = time.monotonic() + timeout_s
    last_tail, last_digest, prompt_visible = await _capture_snapshot(agent, session.tmux_session_name)
    quiet_since: float | None = time.monotonic() if prompt_visible else None

    while time.monotonic() < deadline:
        await asyncio.sleep(poll_interval_s)
        current_tail, current_digest, prompt_visible = await _capture_snapshot(agent, session.tmux_session_name)
        now = time.monotonic()

        if not prompt_visible:
            last_tail = current_tail
            last_digest = current_digest
            quiet_since = None
            continue

        if current_digest != last_digest:
            last_tail = current_tail
            last_digest = current_digest
            quiet_since = now
            continue

        last_tail = current_tail

        if quiet_since is None:
            quiet_since = now
            continue

        if now - quiet_since < quiet_s:
            continue

        logger.debug(
            "readiness: settled above prompt agent=%s quiet_s=%.1f",
            agent_name,
            quiet_s,
        )
        return True, current_tail

    elapsed = time.monotonic() - (deadline - timeout_s)
    logger.debug(
        "readiness: timed out agent=%s prompt_visible=%s elapsed=%.1fs",
        agent_name,
        prompt_visible,
        elapsed,
    )
    return False, last_tail
