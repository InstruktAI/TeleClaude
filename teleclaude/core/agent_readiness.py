"""Agent readiness detection logic."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from re import Pattern
from typing import TYPE_CHECKING, Literal, Protocol

from instrukt_ai_logging import get_logger

from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core import tmux_bridge
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_prompt_submit import find_live_prompt_line_index
from teleclaude.utils import strip_ansi_codes

if TYPE_CHECKING:
    from teleclaude.core.models._session import Session

logger = get_logger(__name__)

# Unified pane-quiet window applied to all adapter profiles. The digest-stability
# loop handles false-positive defense; 1.0s is enough headroom for typical
# render churn after a prompt first becomes visible.
DEFAULT_READINESS_QUIET_S: float = 1.0


@dataclass(frozen=True)
class PromptMatch:
    """Location of the currently visible prompt in the captured pane."""

    line_index: int


class AgentReadinessProfile(Protocol):
    """Agent-owned readiness semantics used by the shared settle engine."""

    @property
    def quiet_s(self) -> float:
        """How long the stability view must stay digest-identical before ready."""
        raise NotImplementedError

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
    quiet_s: float = DEFAULT_READINESS_QUIET_S

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
    quiet_s: float = DEFAULT_READINESS_QUIET_S

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
    quiet_s: float | None = None,
    poll_interval_s: float = 0.2,
) -> tuple[bool, str]:
    """Wait for a visible prompt and for the pre-prompt pane region to settle.

    When ``quiet_s`` is ``None`` the value is taken from the agent's readiness
    profile, which is the canonical source. Explicit overrides are accepted for
    backward compatibility but are no longer required.
    """
    agent = AgentName.from_str(agent_name)
    profile = _get_readiness_profile(agent)
    if quiet_s is None:
        quiet_s = profile.quiet_s
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


ReadinessWinner = Literal["hook", "pane"]

# Sentinel values for ``ReadinessRaceResult.winner``. Tests and downstream
# consumers should compare against these constants rather than literal strings
# so the wire identity is centrally governed.
WINNER_HOOK: ReadinessWinner = "hook"
WINNER_PANE: ReadinessWinner = "pane"


@dataclass(frozen=True)
class ReadinessRaceResult:
    """Outcome of a hook-vs-pane readiness race.

    ``winner`` identifies which detector resolved first. ``elapsed_s`` is the
    monotonic time from race start to the winning signal — useful for hook
    lag diagnostics when the pane wins. ``tail`` is the last pane snapshot
    captured by the pane detector (empty when the hook wins before any pane
    capture has been recorded).
    """

    winner: ReadinessWinner
    elapsed_s: float
    tail: str = ""


async def race_for_readiness(
    *,
    agent_name: str,
    session: Session,
    timeout_s: float,
    ready_future: asyncio.Future[None],
    pane_task_name: str | None = None,
    hook_task_name: str | None = None,
) -> ReadinessRaceResult:
    """Race the hook-event readiness future against the pane-quiet detector.

    Both detectors run concurrently. The first to resolve wins; the loser is
    cancelled cleanly. ``ready_future`` is shielded so that cancelling the
    hook wrapper does not propagate to the underlying future — callers that
    re-await the future after a pane win (e.g. Codex synthetic-event flow)
    rely on this guarantee.

    Raises ``TimeoutError`` when neither detector resolves within
    ``timeout_s``. The caller is responsible for unsubscribing the hook
    handler regardless of outcome.
    """
    started = time.monotonic()
    pane_name = pane_task_name or f"readiness-pane:{session.session_id}"
    hook_name = hook_task_name or f"readiness-hook:{session.session_id}"

    pane_task = asyncio.create_task(
        wait_for_agent_ready(agent_name, session, timeout_s),
        name=pane_name,
    )
    hook_task = asyncio.create_task(
        asyncio.wait_for(asyncio.shield(ready_future), timeout=timeout_s),
        name=hook_name,
    )

    try:
        done, _pending = await asyncio.wait(
            {pane_task, hook_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for task in (pane_task, hook_task):
            if not task.done():
                task.cancel()

    elapsed = time.monotonic() - started
    hook_exc = hook_task.exception() if hook_task in done and not hook_task.cancelled() else None
    pane_exc = pane_task.exception() if pane_task in done and not pane_task.cancelled() else None

    if hook_exc is None and hook_task in done and not hook_task.cancelled():
        return ReadinessRaceResult(winner=WINNER_HOOK, elapsed_s=elapsed, tail="")

    if pane_exc is None and pane_task in done and not pane_task.cancelled():
        ready, tail = pane_task.result()
        if ready:
            return ReadinessRaceResult(winner=WINNER_PANE, elapsed_s=elapsed, tail=tail)

    # Surface a non-timeout root cause when one of the detectors crashed —
    # masking it under a generic TimeoutError loses the original traceback
    # and makes the race appear to be a benign deadline expiry. Asyncio's
    # own ``wait_for`` raises TimeoutError on timeout, so genuine timeouts
    # fall through to the bottom path with no chained cause.
    root_cause: BaseException | None = None
    for exc in (hook_exc, pane_exc):
        if exc is not None and not isinstance(exc, TimeoutError):
            root_cause = exc
            break
    raised = TimeoutError(f"readiness race: pane and hook both failed within {timeout_s:.1f}s (agent={agent_name})")
    if root_cause is not None:
        raise raised from root_cause
    raise raised
