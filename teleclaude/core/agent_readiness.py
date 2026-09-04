"""Agent readiness detection logic."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from re import Pattern
from typing import TYPE_CHECKING, Protocol

from instrukt_ai_logging import get_logger

from teleclaude.constants import UI_MESSAGE_MAX_CHARS
from teleclaude.core import tmux_bridge
from teleclaude.core.agents import AgentName, resolve_parser_agent
from teleclaude.utils import strip_ansi_codes

if TYPE_CHECKING:
    from teleclaude.core.models._session import Session

logger = get_logger(__name__)

_AGENT_READINESS_DECIDED_EVENT = "agent_readiness_decided"
_ANSI_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
_ANSI_ESCAPE_PREFIX = "\x1b["
_CODEX_FOOTER_INDENTATION = "  "
_CODEX_WORKSPACE_PATH_PREFIX = "~/"


class ReadinessSignal(StrEnum):
    """Which detector opened the readiness gate."""

    HOOK = "hook"
    PANE = "pane"


class _ReadinessDecisionOutcome(StrEnum):
    """Closed terminal outcomes for the readiness race."""

    OPENED = "opened"
    TIMED_OUT = "timed_out"


class _ReadinessTimeoutReason(StrEnum):
    """Closed reason for a readiness race without a signal."""

    NO_SIGNAL = "no_signal"


class PromptDeliveryState(StrEnum):
    """Whether the active agent composer can safely receive a submitted turn."""

    EMPTY = "empty"
    OCCUPIED = "occupied"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class PromptDeliveryObservation:
    """Content-independent observation of a complete live composer."""

    state: PromptDeliveryState


def _log_readiness_decision(
    *,
    agent_name: str,
    session_id: str,
    outcome: _ReadinessDecisionOutcome,
    reason: ReadinessSignal | _ReadinessTimeoutReason,
    quiet_s: float,
) -> None:
    """Record the terminal readiness decision without pane content."""
    logger.info(
        _AGENT_READINESS_DECIDED_EVENT,
        agent_name=agent_name,
        session_id=session_id,
        outcome=outcome.value,
        reason=reason.value,
        quiet_s=quiet_s,
    )


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

    def observe_composer(self, output: str) -> PromptDeliveryObservation:
        """Classify a complete editable composer for normal input delivery."""
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

    agent: AgentName
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

    def observe_composer(self, output: str) -> PromptDeliveryObservation:
        """Classify this marker-based agent's complete composer."""
        return _classify_complete_composer(output, self.agent)


_CODEX_AGENT_MARKERS = frozenset(
    {
        "\u2022",
        "\u25e6",
        "\u2736",
        "\u2726",
        "\u2727",
        "\u2734",
        "\u2738",
        "\u2739",
        "\u273a",
        "\u2605",
        "\u2606",
        "\u25cf",
        "\u25cb",
        "\u25c6",
        "\u25c7",
    }
)


@dataclass(frozen=True)
class CodexReadinessProfile:
    """Codex readiness profile that rejects stale prompts below active output."""

    marker: str = AgentName.CODEX.prompt_marker.strip()
    ignored_above_patterns: tuple[Pattern[str], ...] = field(default_factory=tuple)

    def locate_prompt(self, output: str) -> PromptMatch | None:
        """Locate the last live Codex prompt line within the visible pane."""
        lines = _normalized_lines(output)
        while lines and not lines[-1].strip():
            lines.pop()
        start_index = max(0, len(lines) - 10)
        for idx in range(len(lines) - 1, start_index - 1, -1):
            line = lines[idx].strip()
            if not line:
                continue
            if line.startswith(self.marker):
                return PromptMatch(line_index=idx)
            if line.startswith("?") and "shortcut" in line.lower():
                continue
            if line[0] in _CODEX_AGENT_MARKERS:
                return None
        return None

    def build_stability_view(self, output: str, prompt: PromptMatch) -> str:
        """Build the normalized pre-prompt region used for quiet detection."""
        return _build_default_stability_view_with_ignored_patterns(
            output,
            prompt,
            ignored_above_patterns=self.ignored_above_patterns,
        )

    def observe_composer(self, output: str) -> PromptDeliveryObservation:
        """Classify the complete Codex composer for normal input delivery."""
        return _classify_complete_composer(output, AgentName.CODEX)


_READINESS_PROFILES: dict[AgentName, AgentReadinessProfile] = {
    AgentName.CLAUDE: MarkerLineReadinessProfile(
        agent=AgentName.CLAUDE,
        marker=AgentName.CLAUDE.prompt_marker,
    ),
    AgentName.GEMINI: MarkerLineReadinessProfile(
        agent=AgentName.GEMINI,
        marker=AgentName.GEMINI.prompt_marker,
        match_mode="contains",
    ),
    AgentName.CODEX: CodexReadinessProfile(),
    # DeepSeek Harness is an interactive TUI in the pane; its input prompt is
    # the U+276F glyph (same prompt char as Claude), so marker-line readiness
    # applies just as it does for the other pane-based agents.
    AgentName.DEEPSEEK: MarkerLineReadinessProfile(
        agent=AgentName.DEEPSEEK,
        marker=AgentName.DEEPSEEK.prompt_marker,
    ),
}


def _get_readiness_profile(agent_name: AgentName) -> AgentReadinessProfile:
    return _READINESS_PROFILES[agent_name]


def classify_prompt_delivery(
    output: str,
    active_agent: str | None,
) -> PromptDeliveryObservation:
    """Classify delivery through the selected agent's canonical readiness profile."""
    agent = resolve_parser_agent(active_agent)
    return _get_readiness_profile(agent).observe_composer(output)


def _classify_complete_composer(output: str, agent: AgentName) -> PromptDeliveryObservation:
    live_region = _extract_complete_live_region(output, agent)
    if live_region is None:
        return PromptDeliveryObservation(PromptDeliveryState.AMBIGUOUS)
    if _live_region_has_input(live_region, agent):
        return PromptDeliveryObservation(PromptDeliveryState.OCCUPIED)
    return PromptDeliveryObservation(PromptDeliveryState.EMPTY)


def _extract_complete_live_region(output: str, agent: AgentName) -> str | None:
    lines = output.rstrip().split("\n")
    if agent is AgentName.CODEX:
        return _extract_complete_codex_live_region(lines)
    if agent is AgentName.GEMINI:
        return _extract_complete_gemini_live_region(lines)
    if agent is AgentName.DEEPSEEK:
        return _extract_complete_deepseek_live_region(lines)
    marker = agent.prompt_marker.strip()
    if not marker:
        return None
    for idx in range(len(lines) - 1, -1, -1):
        if strip_ansi_codes(lines[idx].strip()).startswith(marker):
            return _extract_complete_claude_live_region(lines[idx:])
    return None


def _extract_complete_claude_live_region(lines: list[str]) -> str | None:
    input_lines: list[str] = []
    for line in lines:
        input_lines.append(line)
        if _is_horizontal_rule_line(line):
            return "\n".join(input_lines)
    return None


def _extract_complete_codex_live_region(lines: list[str]) -> str | None:
    marker = AgentName.CODEX.prompt_marker.strip()
    if not marker:
        return None
    for idx in range(len(lines) - 1, -1, -1):
        if strip_ansi_codes(lines[idx].strip()).startswith(marker):
            return _extract_complete_codex_live_input_block(lines[idx:])
    return None


def _extract_complete_codex_live_input_block(lines: list[str]) -> str | None:
    input_lines: list[str] = []
    marker = AgentName.CODEX.prompt_marker.strip()
    previous_was_blank = False
    for idx, line in enumerate(lines):
        normalized = strip_ansi_codes(line).strip()
        if idx > 0 and _is_codex_composer_chrome_line(line):
            input_lines.append(line)
            return "\n".join(input_lines)
        if idx > 0 and previous_was_blank and _is_complete_codex_passive_workspace_footer(line, lines[idx + 1 :]):
            return "\n".join(input_lines)
        if idx > 0 and marker and normalized.startswith(marker):
            input_lines.append(line)
            return "\n".join(input_lines)
        input_lines.append(line)
        previous_was_blank = not normalized
    return None


def _is_complete_codex_passive_workspace_footer(line: str, trailing_lines: list[str]) -> bool:
    """Return whether a terminal status row closes Codex's passive composer."""
    return (
        _ANSI_ESCAPE_PREFIX in line
        and strip_ansi_codes(line).startswith(_CODEX_FOOTER_INDENTATION + _CODEX_WORKSPACE_PATH_PREFIX)
        and all(not strip_ansi_codes(trailing_line).strip() for trailing_line in trailing_lines)
    )


def _extract_complete_deepseek_live_region(lines: list[str]) -> str | None:
    """Extract the DeepSeek composer up to its closing horizontal rule.

    DeepSeek renders status and hint lines below that rule; they are not
    editable composer content.
    """
    marker = AgentName.DEEPSEEK.prompt_marker.strip()
    if not marker:
        return None
    for idx in range(len(lines) - 1, -1, -1):
        if strip_ansi_codes(lines[idx].strip()).startswith(marker):
            input_lines: list[str] = []
            for line in lines[idx:]:
                if input_lines and _is_horizontal_rule_line(line):
                    return "\n".join(input_lines)
                input_lines.append(line)
            return None
    return None


def _extract_complete_gemini_live_region(lines: list[str]) -> str | None:
    for idx in range(len(lines) - 1, -1, -1):
        if AgentName.GEMINI.prompt_marker not in strip_ansi_codes(lines[idx]):
            continue
        start_idx = idx
        for preceding_idx in range(idx - 1, max(-1, idx - 20), -1):
            if strip_ansi_codes(lines[preceding_idx]).strip().startswith(">"):
                start_idx = preceding_idx
                break
        return "\n".join(lines[start_idx : idx + 1])
    return _extract_complete_gemini_bordered_live_region(lines)


def _extract_complete_gemini_bordered_live_region(lines: list[str]) -> str | None:
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
                return "\n".join(lines[idx : end_idx + 1])
            end_idx += 1
    return None


def _live_region_has_input(live_region: str, agent: AgentName) -> bool:
    """Return whether a complete composer contains operator-authored input."""
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
    if not stripped or _is_horizontal_rule_line(raw_line):
        return True
    if agent is AgentName.GEMINI and stripped == AgentName.GEMINI.prompt_marker:
        return True
    if agent is AgentName.CODEX and _is_codex_composer_chrome_line(raw_line):
        return True
    return False


def _is_codex_composer_chrome_line(line: str) -> bool:
    normalized = _fold_prompt_whitespace(line).lower()
    return ("shift + tab" in normalized and "esc dismiss" in normalized) or (
        normalized.startswith("gpt-") and "·" in normalized
    )


def _is_horizontal_rule_line(raw_line: str) -> bool:
    stripped = strip_ansi_codes(raw_line).strip()
    return bool(stripped) and set(stripped) <= {"─"}


def _strip_live_prompt_marker(raw_line: str, agent: AgentName) -> str:
    marker = ">" if agent is AgentName.GEMINI else agent.prompt_marker.strip()
    if not marker:
        return raw_line
    marker_pos = raw_line.find(marker)
    if marker_pos < 0 or strip_ansi_codes(raw_line[:marker_pos]).strip():
        return raw_line
    return raw_line[marker_pos + len(marker) :]


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
                params = [param for param in match.group(1).split(";") if param]
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


async def _capture_snapshot(tmux_session_name: str) -> str:
    output = await tmux_bridge.capture_pane(tmux_session_name)
    if not output:
        return ""
    return output[-UI_MESSAGE_MAX_CHARS:]


async def pane_shows_ready_prompt(agent_name: str, session: Session) -> bool:
    """Return whether the current pane has an idle prompt for this agent."""
    agent = AgentName.from_str(agent_name)
    output = await _capture_snapshot(session.tmux_session_name)
    return _get_readiness_profile(agent).locate_prompt(output) is not None


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


async def await_agent_readiness(
    *,
    agent_name: str,
    session: Session,
    session_id: str,
    ready_future: asyncio.Future[None],
    quiet_s: float,
    timeout_s: float,
) -> ReadinessSignal:
    """Open the launch/relaunch gate on whichever readiness signal arrives first.

    Uniform across every agent — there is no per-agent branch at the call site.
    CLIs differ in how (or whether) they announce readiness: Claude emits a
    reliable native session_start; Codex fires it late or combined with the first
    prompt; agy never fires one at all. So the pane-quiet detector
    (`wait_for_agent_ready` with the agent's readiness profile) always races the
    native-hook ``ready_future``, and the gate opens on the first to complete.

    A pane win authorizes prompt delivery only. Lifecycle state remains the
    authority of normalized runtime hooks.

    Returns the signal that opened the gate. Raises ``TimeoutError`` if both
    detectors fail within ``timeout_s``.
    """
    pane_task = asyncio.create_task(
        wait_for_agent_ready(agent_name, session, timeout_s, quiet_s),
        name=f"agent-readiness-pane:{session_id}",
    )
    # Shield the shared readiness future from cancellation when the pane task wins.
    hook_task = asyncio.create_task(
        asyncio.wait_for(asyncio.shield(ready_future), timeout=timeout_s),
        name=f"agent-readiness-hook:{session_id}",
    )
    try:
        done, _ = await asyncio.wait(
            {pane_task, hook_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for task in (pane_task, hook_task):
            if not task.done():
                task.cancel()

    hook_won = hook_task in done and not hook_task.cancelled() and hook_task.exception() is None
    if hook_won:
        _log_readiness_decision(
            agent_name=agent_name,
            session_id=session_id,
            outcome=_ReadinessDecisionOutcome.OPENED,
            reason=ReadinessSignal.HOOK,
            quiet_s=quiet_s,
        )
        logger.info("agent readiness gate opened via hook agent=%s session=%s", agent_name, session_id)
        return ReadinessSignal.HOOK

    pane_won = False
    if pane_task in done and not pane_task.cancelled() and pane_task.exception() is None:
        ready, _ = pane_task.result()
        pane_won = ready

    if not pane_won:
        _log_readiness_decision(
            agent_name=agent_name,
            session_id=session_id,
            outcome=_ReadinessDecisionOutcome.TIMED_OUT,
            reason=_ReadinessTimeoutReason.NO_SIGNAL,
            quiet_s=quiet_s,
        )
        raise TimeoutError(f"agent readiness: pane and hook both failed within timeout (agent={agent_name})")

    _log_readiness_decision(
        agent_name=agent_name,
        session_id=session_id,
        outcome=_ReadinessDecisionOutcome.OPENED,
        reason=ReadinessSignal.PANE,
        quiet_s=quiet_s,
    )
    logger.info("agent readiness gate opened via pane agent=%s session=%s", agent_name, session_id)
    return ReadinessSignal.PANE
