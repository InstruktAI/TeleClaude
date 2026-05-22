"""Agent readiness detection logic."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from re import Pattern
from typing import TYPE_CHECKING, Protocol

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
    """Location of the currently visible prompt in the captured pane."""

    line_index: int


class AgentReadinessProfile(Protocol):
    """Agent-owned readiness semantics used by the shared settle engine."""

    def locate_prompt(self, output: str) -> PromptMatch | None:
        """Return the visible prompt location when the agent prompt is available."""
        raise NotImplementedError

    def build_stability_view(self, output: str, prompt: PromptMatch) -> str:
        """Return the normalized content that must settle before input is injected."""
        raise NotImplementedError


def _normalized_lines(output: str) -> list[str]:
    """Return ANSI-stripped lines from the visible readiness window."""
    sanitized = strip_ansi_codes(output or "")
    if len(sanitized) > UI_MESSAGE_MAX_CHARS:
        sanitized = sanitized[-UI_MESSAGE_MAX_CHARS:]
    return sanitized.split("\n")


def _build_default_stability_view_with_ignored_patterns(
    output: str,
    prompt: PromptMatch,
    *,
    ignored_above_patterns: tuple[Pattern[str], ...] = (),
) -> str:
    lines = _normalized_lines(output)
    if prompt.line_index <= 0:
        return ""
    stable_lines: list[str] = []
    for line in lines[: prompt.line_index]:
        stripped = line.strip()
        if stripped and any(pattern.search(stripped) for pattern in ignored_above_patterns):
            continue
        stable_lines.append(line.rstrip())
    return "\n".join(stable_lines).rstrip()


@dataclass(frozen=True)
class MarkerLineReadinessProfile:
    """Default readiness profile for marker-based agent prompts."""

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
                matched = self.marker in line
            else:
                matched = line.startswith(self.marker)
            if matched:
                return PromptMatch(line_index=idx)
        return None

    def build_stability_view(self, output: str, prompt: PromptMatch) -> str:
        """Build the normalized pre-prompt region used for quiet detection."""
        return _build_default_stability_view_with_ignored_patterns(
            output,
            prompt,
            ignored_above_patterns=self.ignored_above_patterns,
        )


@dataclass(frozen=True)
class CodexReadinessProfile:
    """Codex readiness profile using Codex-owned prompt detection."""

    ignored_above_patterns: tuple[Pattern[str], ...] = field(default_factory=tuple)

    def locate_prompt(self, output: str) -> PromptMatch | None:
        """Locate the last live Codex prompt line within the visible pane."""
        prompt_idx = find_live_prompt_line_index(output)
        if prompt_idx is None:
            return None
        return PromptMatch(line_index=prompt_idx)

    def build_stability_view(self, output: str, prompt: PromptMatch) -> str:
        """Build the normalized pre-prompt region used for quiet detection."""
        return _build_default_stability_view_with_ignored_patterns(
            output,
            prompt,
            ignored_above_patterns=self.ignored_above_patterns,
        )


_READINESS_PROFILES: dict[AgentName, AgentReadinessProfile] = {
    AgentName.CLAUDE: MarkerLineReadinessProfile(marker=AgentName.CLAUDE.prompt_marker),
    AgentName.GEMINI: MarkerLineReadinessProfile(
        marker=AgentName.GEMINI.prompt_marker,
        match_mode="contains",
    ),
    AgentName.CODEX: CodexReadinessProfile(),
}


def _get_readiness_profile(agent_name: AgentName) -> AgentReadinessProfile:
    return _READINESS_PROFILES[agent_name]


async def _capture_snapshot(tmux_session_name: str) -> str:
    output = await tmux_bridge.capture_pane(tmux_session_name)
    if not output:
        return ""
    return output[-UI_MESSAGE_MAX_CHARS:]


def _digest_stability_view(stability_view: str) -> str:
    return hashlib.sha256(stability_view.encode("utf-8", errors="replace")).hexdigest()


async def wait_for_agent_ready(
    agent_name: str,
    session: Session,
    timeout_s: float,
    quiet_s: float,
    poll_interval_s: float = 0.2,
) -> tuple[bool, str]:
    """Wait for a visible prompt and for the pre-prompt pane region to settle."""
    agent = AgentName.from_str(agent_name)
    profile = _get_readiness_profile(agent)
    deadline = time.monotonic() + timeout_s
    last_tail = await _capture_snapshot(session.tmux_session_name)
    last_digest: str | None = None
    quiet_since: float | None = None
    prompt_seen = False

    while time.monotonic() < deadline:
        current_tail = await _capture_snapshot(session.tmux_session_name)
        last_tail = current_tail
        prompt = profile.locate_prompt(current_tail)
        now = time.monotonic()

        if prompt is None:
            last_digest = None
            quiet_since = None
            await asyncio.sleep(poll_interval_s)
            continue

        prompt_seen = True
        stability_view = profile.build_stability_view(current_tail, prompt)
        current_digest = _digest_stability_view(stability_view)

        if current_digest != last_digest:
            last_digest = current_digest
            quiet_since = now
            await asyncio.sleep(poll_interval_s)
            continue

        if quiet_since is None:
            quiet_since = now
            await asyncio.sleep(poll_interval_s)
            continue

        if now - quiet_since < quiet_s:
            await asyncio.sleep(poll_interval_s)
            continue

        logger.debug(
            "readiness: settled with prompt agent=%s quiet_s=%.1f stability_lines=%d",
            agent_name,
            quiet_s,
            len(stability_view.splitlines()) if stability_view else 0,
        )
        return True, current_tail

    elapsed = time.monotonic() - (deadline - timeout_s)
    logger.debug(
        "readiness: timed out agent=%s prompt_seen=%s elapsed=%.1fs",
        agent_name,
        prompt_seen,
        elapsed,
    )
    return False, last_tail
