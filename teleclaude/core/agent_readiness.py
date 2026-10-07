"""Agent readiness detection logic."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.core.agents import AgentName, AgentStartupSignal, resolve_parser_agent
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import DeliveryNoComposerContext, TeleClaudeEvents
from teleclaude.core.tmux_bridge import PaneObservation
from teleclaude.events.envelope import EventVisibility
from teleclaude.utils import strip_ansi_codes

if TYPE_CHECKING:
    from teleclaude.core.models._session import Session

logger = get_logger(__name__)

_AGENT_READINESS_DECIDED_EVENT = "agent_readiness_decided"
_ANSI_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
_ROW_SEPARATOR = "\n"
_NO_VIEW = ""
_RULE_CHARACTER = "─"
_DEEPSEEK_COMPOSER_EXPAND_AFFORDANCE = "⛶"
_DEEPSEEK_TOP_BORDER_CORNERS = ("╭", "╮")
_DEEPSEEK_BOTTOM_BORDER_CORNERS = ("╰", "╯")
_DEEPSEEK_BORDER_CHARACTERS = frozenset({"╭", "╮", "╰", "╯", _RULE_CHARACTER})
_CODEX_COMPOSER_MARKER = AgentName.CODEX.prompt_marker.strip()
_CODEX_COMPOSER_GUTTER = "  "
_DEEPSEEK_COMPOSER_MARKER = AgentName.DEEPSEEK.prompt_marker.strip()
# How long visible agent output must hold still after a launch before its pane
# is judged: a composer for input readiness, a screen with none for a block.
AGENT_START_STABILIZE_QUIET_S = 3.0


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
    SCREEN_WITHOUT_COMPOSER = "screen_without_composer"


class PaneReadiness(StrEnum):
    """How a pane-authority readiness wait ended."""

    OPENED = "opened"
    TIMED_OUT = "timed_out"
    TIMED_OUT_ON_SCREEN = "timed_out_on_screen"


class NoComposerReadinessTimeout(TimeoutError):
    """A readiness wait ended while the pane showed a settled screen with no composer.

    That screen is a dialog, menu, or overlay that waits for an agent. Callers
    that treat every readiness timeout alike catch ``TimeoutError``; callers
    that hold input for a composer tell this cause apart by type.
    """


class PromptDeliveryState(StrEnum):
    """Whether the active agent composer can safely receive a submitted turn."""

    EMPTY = "empty"
    OCCUPIED = "occupied"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class PromptDeliveryObservation:
    """Content-independent observation of a complete live composer."""

    state: PromptDeliveryState


def publish_delivery_no_composer(session_id: str, surface_text: str) -> None:
    """Publish the fact that a captured pane shows no recognized composer.

    The fact carries the bounded last lines of the surface so the session's
    watchers can see what it displays. What the status owner and the watchers
    do with it is theirs; observers publish and move on.
    """
    event_bus.emit(
        TeleClaudeEvents.DELIVERY_NO_COMPOSER,
        DeliveryNoComposerContext(
            session_id=session_id,
            observed_at=datetime.now(UTC).isoformat(),
            pane_tail=tmux_bridge.pane_evidence_tail(surface_text),
        ),
        visibility=EventVisibility.LOCAL,
    )


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


@dataclass(frozen=True)
class _Composer:
    """A live composer located on the visible surface.

    ``rows`` are the raw surface rows the composer's own markers enclose,
    starting at its prompt row, which sits at ``marker_index``.
    """

    marker_index: int
    rows: tuple[str, ...]


class AgentReadinessProfile(Protocol):
    """Agent-owned readiness semantics used by the shared settle engine."""

    def locate_prompt(self, observation: PaneObservation) -> PromptMatch | None:
        """Return the visible prompt location when the agent's composer is identified."""
        raise NotImplementedError

    def build_stability_view(self, observation: PaneObservation, prompt: PromptMatch) -> str:
        """Return the normalized content that must settle before input is injected."""
        raise NotImplementedError

    def observe_composer(self, observation: PaneObservation) -> PromptDeliveryObservation:
        """Classify the identified composer for normal input delivery."""
        raise NotImplementedError


def _surface_rows(observation: PaneObservation) -> list[str]:
    """Return the raw visible rows; the cursor row indexes this list directly."""
    return observation.text.split(_ROW_SEPARATOR)


def _plain_row(raw_row: str) -> str:
    return strip_ansi_codes(raw_row).strip()


def _rows_above_view(observation: PaneObservation, prompt: PromptMatch) -> str:
    """Return the ANSI-free rows above the composer's prompt row."""
    if prompt.line_index <= 0:
        return _NO_VIEW
    rows = _surface_rows(observation)[: prompt.line_index]
    return _ROW_SEPARATOR.join(strip_ansi_codes(row).rstrip() for row in rows).rstrip()


def _observe(composer: _Composer | None, *, has_input: bool) -> PromptDeliveryObservation:
    if composer is None:
        return PromptDeliveryObservation(PromptDeliveryState.AMBIGUOUS)
    if has_input:
        return PromptDeliveryObservation(PromptDeliveryState.OCCUPIED)
    return PromptDeliveryObservation(PromptDeliveryState.EMPTY)


def _row_has_authored_text(raw_row: str) -> bool:
    """Return whether a composer row holds text the CLI did not generate itself."""
    return bool(_normalize_text(_strip_generated_segments(raw_row)).strip())


@dataclass(frozen=True)
class FramedComposerReadinessProfile:
    """Readiness profile for composers drawn between two horizontal rules.

    The composer is the prompt row with a rule directly above it, through the
    rule that closes it below. A prompt-prefixed row without that frame is not
    a candidate.
    """

    agent: AgentName

    def _locate(self, observation: PaneObservation) -> _Composer | None:
        marker = self.agent.prompt_marker.strip()
        rows = _surface_rows(observation)
        for index in range(len(rows) - 1, 0, -1):
            if not _plain_row(rows[index]).startswith(marker) or not _is_horizontal_rule_line(rows[index - 1]):
                continue
            for end in range(index + 1, len(rows)):
                if _is_horizontal_rule_line(rows[end]):
                    return _Composer(marker_index=index, rows=tuple(rows[index:end]))
            return None
        return None

    def locate_prompt(self, observation: PaneObservation) -> PromptMatch | None:
        """Locate the framed prompt row."""
        composer = self._locate(observation)
        return None if composer is None else PromptMatch(line_index=composer.marker_index)

    def build_stability_view(self, observation: PaneObservation, prompt: PromptMatch) -> str:
        """Build the normalized region above the composer used for quiet detection."""
        return _rows_above_view(observation, prompt)

    def observe_composer(self, observation: PaneObservation) -> PromptDeliveryObservation:
        """Classify the framed composer from the rows its frame encloses."""
        composer = self._locate(observation)
        if composer is None:
            return _observe(None, has_input=False)
        first_row = _strip_live_prompt_marker(composer.rows[0], self.agent.prompt_marker.strip())
        return _observe(composer, has_input=any(_row_has_authored_text(row) for row in (first_row, *composer.rows[1:])))


@dataclass(frozen=True)
class CodexReadinessProfile:
    """Codex readiness profile that identifies the composer by its input cursor.

    Codex draws no border around its composer, but it indents every row below the
    prompt row by the width of the prompt marker. The composer runs from the
    nearest prompt-marker row at or above the visible input cursor through the
    cursor's row, and every non-blank row in between sits in that gutter, so a
    draft with blank rows between its lines is one composer wherever the cursor
    sits in it. A surface with no visible cursor, or whose cursor is reached from
    a prompt-marker row only across rows outside the gutter, has no composer:
    selection lists, approval overlays and transcript echoes place no cursor, and
    a cursor elsewhere does not adopt an earlier prompt row.
    """

    def _locate(self, observation: PaneObservation) -> _Composer | None:
        cursor = observation.cursor
        rows = _surface_rows(observation)
        if cursor is None or cursor.row >= len(rows):
            return None
        for start in range(cursor.row, -1, -1):
            if _plain_row(rows[start]).startswith(_CODEX_COMPOSER_MARKER):
                return _Composer(marker_index=start, rows=tuple(rows[start : cursor.row + 1]))
            if _plain_row(rows[start]) and not strip_ansi_codes(rows[start]).startswith(_CODEX_COMPOSER_GUTTER):
                return None
        return None

    def locate_prompt(self, observation: PaneObservation) -> PromptMatch | None:
        """Locate the prompt row of the composer holding the input cursor."""
        composer = self._locate(observation)
        return None if composer is None else PromptMatch(line_index=composer.marker_index)

    def build_stability_view(self, observation: PaneObservation, prompt: PromptMatch) -> str:
        """Build the normalized region above the composer used for quiet detection."""
        return _rows_above_view(observation, prompt)

    def observe_composer(self, observation: PaneObservation) -> PromptDeliveryObservation:
        """Classify the composer: empty only while it shows its generated placeholder.

        Codex renders its placeholder in generated style on the prompt row while
        the input is empty. A prompt row without it, or any authored text in the
        composer rows, is a draft.
        """
        composer = self._locate(observation)
        if composer is None:
            return _observe(None, has_input=False)
        first_row = _strip_live_prompt_marker(composer.rows[0], _CODEX_COMPOSER_MARKER)
        placeholder_shown = bool(_normalize_text(first_row).strip())
        authored = any(_row_has_authored_text(row) for row in (first_row, *composer.rows[1:]))
        return _observe(composer, has_input=authored or not placeholder_shown)


@dataclass(frozen=True)
class DeepSeekReadinessProfile:
    """DeepSeek readiness profile that identifies the composer by its rounded border.

    The composer is the region inside the rounded border whose first content row
    carries the prompt marker, which may follow the composer's own leading glyph.
    DeepSeek renders animated splash art above it, so the settle engine measures
    stability on the composer region itself.
    """

    def _locate(self, observation: PaneObservation) -> _Composer | None:
        rows = _surface_rows(observation)
        for top in range(len(rows) - 1, -1, -1):
            if not _is_deepseek_rounded_border_line(rows[top], _DEEPSEEK_TOP_BORDER_CORNERS):
                continue
            for bottom in range(top + 1, len(rows)):
                if _is_deepseek_rounded_border_line(rows[bottom], _DEEPSEEK_BOTTOM_BORDER_CORNERS):
                    content = rows[top + 1 : bottom]
                    if content and _DEEPSEEK_COMPOSER_MARKER in _plain_row(content[0]):
                        return _Composer(marker_index=top + 1, rows=tuple(content))
                    break
        return None

    def locate_prompt(self, observation: PaneObservation) -> PromptMatch | None:
        """Locate the composer's marker row inside the rounded border."""
        composer = self._locate(observation)
        return None if composer is None else PromptMatch(line_index=composer.marker_index)

    def build_stability_view(self, observation: PaneObservation, prompt: PromptMatch) -> str:
        """Return the composer's own region; the splash above it never settles."""
        composer = self._locate(observation)
        if composer is None or composer.marker_index != prompt.line_index:
            return _NO_VIEW
        return _ROW_SEPARATOR.join(strip_ansi_codes(row).rstrip() for row in composer.rows).rstrip()

    def observe_composer(self, observation: PaneObservation) -> PromptDeliveryObservation:
        """Classify the composer from the rows its border encloses."""
        composer = self._locate(observation)
        if composer is None:
            return _observe(None, has_input=False)
        first_row = composer.rows[0].partition(_DEEPSEEK_COMPOSER_MARKER)[2]
        texts = (
            _strip_deepseek_composer_expand_affordance(_normalize_text(_strip_generated_segments(row)).strip())
            for row in (first_row, *composer.rows[1:])
        )
        return _observe(composer, has_input=any(texts))


_READINESS_PROFILES: dict[AgentName, AgentReadinessProfile] = {
    AgentName.CLAUDE: FramedComposerReadinessProfile(agent=AgentName.CLAUDE),
    AgentName.GEMINI: FramedComposerReadinessProfile(agent=AgentName.GEMINI),
    AgentName.CODEX: CodexReadinessProfile(),
    AgentName.DEEPSEEK: DeepSeekReadinessProfile(),
}


def _get_readiness_profile(agent_name: AgentName) -> AgentReadinessProfile:
    return _READINESS_PROFILES[agent_name]


def classify_prompt_delivery(
    observation: PaneObservation,
    active_agent: str | None,
) -> PromptDeliveryObservation:
    """Classify delivery through the selected agent's canonical readiness profile."""
    agent = resolve_parser_agent(active_agent)
    return _get_readiness_profile(agent).observe_composer(observation)


def _is_deepseek_rounded_border_line(raw_line: str, corners: tuple[str, str]) -> bool:
    """Recognize one of DeepSeek's structural rounded input borders without reading prose."""
    stripped = strip_ansi_codes(raw_line).strip()
    if len(stripped) < len(corners):
        return False
    left, right = corners
    return stripped.startswith(left) and stripped.endswith(right) and set(stripped) <= _DEEPSEEK_BORDER_CHARACTERS


def _strip_live_prompt_marker(raw_line: str, marker: str) -> str:
    """Return the row after its leading prompt marker; a row not led by it is returned whole."""
    marker_pos = raw_line.find(marker)
    if marker_pos < 0 or strip_ansi_codes(raw_line[:marker_pos]).strip():
        return raw_line
    return raw_line[marker_pos + len(marker) :]


def _strip_deepseek_composer_expand_affordance(normalized_text: str) -> str:
    """Strip DeepSeek's trailing expand-composer affordance; it is chrome, not input."""
    if normalized_text.endswith(_DEEPSEEK_COMPOSER_EXPAND_AFFORDANCE):
        return normalized_text[: -len(_DEEPSEEK_COMPOSER_EXPAND_AFFORDANCE)]
    return normalized_text


def _is_horizontal_rule_line(raw_line: str) -> bool:
    stripped = strip_ansi_codes(raw_line).strip()
    return bool(stripped) and set(stripped) <= {"─"}


def _normalize_text(text: str) -> str:
    stripped = strip_ansi_codes(text or "")
    return stripped.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")


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
                    active_generated_style = _generated_style_active(params, active_generated_style)
                idx = match.end()
                continue
        if not active_generated_style:
            out.append(text[idx])
        idx += 1
    return "".join(out)


def _generated_style_active(params: list[str], active_style: bool) -> bool:
    """Apply SGR emphasis while treating extended-colour operands as colours."""
    index = 0
    while index < len(params):
        param = params[index]
        if param in {"38", "48", "58"} and index + 1 < len(params):
            mode = params[index + 1]
            if mode == "5":
                index += 3
                continue
            if mode == "2":
                index += 5
                continue
        if param in {"22", "23"}:
            active_style = False
        elif param in {"2", "3"}:
            active_style = True
        index += 1
    return active_style


async def _capture_snapshot(tmux_session_name: str) -> PaneObservation | None:
    return await tmux_bridge.observe_visible_pane(tmux_session_name)


def _digest_stability_view(stability_view: str) -> str:
    return hashlib.sha256(stability_view.encode("utf-8", errors="replace")).hexdigest()


def _surface_view(observation: PaneObservation) -> str:
    """Return the ANSI-free visible surface, row by row."""
    return _ROW_SEPARATOR.join(strip_ansi_codes(row).rstrip() for row in _surface_rows(observation))


async def wait_for_agent_ready(
    agent_name: str,
    session: Session,
    timeout_s: float,
    quiet_s: float,
    poll_interval_s: float = 0.2,
) -> PaneReadiness:
    """Wait for the agent's visible activity to settle, then for its identified composer.

    Settledness comes first: the view the profile declares stable must hold still
    for ``quiet_s`` while the composer is identified, and identification only
    resets the window when the composer or the agent process is absent.

    While the agent runs and no composer is identified, the whole surface is
    watched too: once it has held still for the startup quiet window it is a
    screen waiting for an agent, published once per wait as the delivery
    no-composer fact. The wait itself is unchanged: it opens only on a settled
    composer and ends at ``timeout_s``, reporting whether the last surface it
    judged was such a screen. A composer, a changed surface, or a failed capture
    restarts that settle clock.
    """
    agent = AgentName.from_str(agent_name)
    profile = _get_readiness_profile(agent)
    deadline = time.monotonic() + timeout_s
    last_digest: str | None = None
    quiet_since: float | None = None
    screen_digest: str | None = None
    screen_since: float | None = None
    screen_published = False
    on_settled_screen = False
    prompt_seen = False

    while time.monotonic() < deadline:
        observation = await _capture_snapshot(session.tmux_session_name)
        if observation is None:
            last_digest = None
            quiet_since = None
            screen_digest = None
            screen_since = None
            on_settled_screen = False
            await asyncio.sleep(poll_interval_s)
            continue
        prompt = profile.locate_prompt(observation)
        now = time.monotonic()
        process_running = await tmux_bridge.is_process_running(session.tmux_session_name)

        on_settled_screen = False
        if prompt is None and process_running:
            current_screen_digest = _digest_stability_view(_surface_view(observation))
            if current_screen_digest != screen_digest:
                screen_digest = current_screen_digest
                screen_since = now
            elif screen_since is not None and now - screen_since >= AGENT_START_STABILIZE_QUIET_S:
                on_settled_screen = True
                if not screen_published:
                    publish_delivery_no_composer(session.session_id, observation.text)
                    screen_published = True
        else:
            screen_digest = None
            screen_since = None

        if prompt is None or not process_running:
            last_digest = None
            quiet_since = None
            await asyncio.sleep(poll_interval_s)
            continue

        prompt_seen = True
        stability_view = profile.build_stability_view(observation, prompt)
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
        return PaneReadiness.OPENED

    elapsed = time.monotonic() - (deadline - timeout_s)
    logger.debug(
        "readiness: timed out agent=%s prompt_seen=%s elapsed=%.1fs",
        agent_name,
        prompt_seen,
        elapsed,
    )
    return PaneReadiness.TIMED_OUT_ON_SCREEN if on_settled_screen else PaneReadiness.TIMED_OUT


async def await_agent_readiness(
    *,
    agent_name: str,
    session: Session,
    session_id: str,
    ready_future: asyncio.Future[None],
    quiet_s: float,
    timeout_s: float,
) -> ReadinessSignal:
    """Open the launch/relaunch gate on its provider-declared readiness authority.

    The provider capability selects one detector: native-start providers await
    ``ready_future``; pane-authority providers await a settled complete composer.
    Pane admission authorizes prompt delivery only. Lifecycle state remains the
    authority of normalized runtime hooks.

    Returns the selected signal. Raises ``TimeoutError`` when that provider's
    selected detector does not open within ``timeout_s``;
    ``NoComposerReadinessTimeout`` when a pane-authority wait ended on a settled
    screen with no composer.
    """
    agent = AgentName.from_str(agent_name)
    if agent.startup_signal is AgentStartupSignal.NATIVE:
        try:
            await asyncio.wait_for(asyncio.shield(ready_future), timeout=timeout_s)
        except TimeoutError:
            _log_readiness_decision(
                agent_name=agent_name,
                session_id=session_id,
                outcome=_ReadinessDecisionOutcome.TIMED_OUT,
                reason=_ReadinessTimeoutReason.NO_SIGNAL,
                quiet_s=quiet_s,
            )
            raise TimeoutError(
                f"agent readiness: native signal unavailable within timeout (agent={agent_name})"
            ) from None
        _log_readiness_decision(
            agent_name=agent_name,
            session_id=session_id,
            outcome=_ReadinessDecisionOutcome.OPENED,
            reason=ReadinessSignal.HOOK,
            quiet_s=quiet_s,
        )
        return ReadinessSignal.HOOK

    pane_task = asyncio.create_task(
        wait_for_agent_ready(agent_name, session, timeout_s, quiet_s),
        name=f"agent-readiness-pane:{session_id}",
    )
    try:
        readiness = await pane_task
    finally:
        if not pane_task.done():
            pane_task.cancel()

    if readiness is PaneReadiness.TIMED_OUT_ON_SCREEN:
        _log_readiness_decision(
            agent_name=agent_name,
            session_id=session_id,
            outcome=_ReadinessDecisionOutcome.TIMED_OUT,
            reason=_ReadinessTimeoutReason.SCREEN_WITHOUT_COMPOSER,
            quiet_s=quiet_s,
        )
        raise NoComposerReadinessTimeout(
            f"agent readiness: pane shows a screen with no composer at timeout (agent={agent_name})"
        )

    if readiness is PaneReadiness.TIMED_OUT:
        _log_readiness_decision(
            agent_name=agent_name,
            session_id=session_id,
            outcome=_ReadinessDecisionOutcome.TIMED_OUT,
            reason=_ReadinessTimeoutReason.NO_SIGNAL,
            quiet_s=quiet_s,
        )
        raise TimeoutError(f"agent readiness: pane signal unavailable within timeout (agent={agent_name})")

    _log_readiness_decision(
        agent_name=agent_name,
        session_id=session_id,
        outcome=_ReadinessDecisionOutcome.OPENED,
        reason=ReadinessSignal.PANE,
        quiet_s=quiet_s,
    )
    logger.info("agent readiness gate opened via pane agent=%s session=%s", agent_name, session_id)
    return ReadinessSignal.PANE
