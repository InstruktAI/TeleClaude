"""Unit tests for teleclaude.core.agent_readiness."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from teleclaude.core import agent_readiness
from teleclaude.core.agent_readiness import (
    _READINESS_PROFILES,
    DEFAULT_READINESS_QUIET_S,
    WINNER_HOOK,
    WINNER_PANE,
    CodexReadinessProfile,
    MarkerLineReadinessProfile,
    race_for_readiness,
)
from teleclaude.core.agents import AgentName
from teleclaude.core.models import Session


def _make_session(session_id: str = "sess-readiness", tmux_name: str = "tc-readiness") -> Session:
    return Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name=tmux_name,
        title="readiness",
    )


def _snapshot_sequence_factory(snapshots: list[str]) -> AsyncMock:
    """Return an AsyncMock that yields each snapshot in order then repeats the last."""

    queue: list[str] = list(snapshots)

    async def _capture(_tmux_session_name: str) -> str:
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0] if queue else ""

    return AsyncMock(side_effect=_capture)


class TestProfileQuietS:
    @pytest.mark.unit
    def test_marker_profile_defaults_to_unified_quiet_window(self) -> None:
        profile = MarkerLineReadinessProfile(marker=">")
        assert profile.quiet_s == DEFAULT_READINESS_QUIET_S

    @pytest.mark.unit
    def test_codex_profile_defaults_to_unified_quiet_window(self) -> None:
        profile = CodexReadinessProfile()
        assert profile.quiet_s == DEFAULT_READINESS_QUIET_S

    @pytest.mark.unit
    def test_registered_profiles_carry_quiet_s_for_every_adapter(self) -> None:
        for agent in (AgentName.CLAUDE, AgentName.GEMINI, AgentName.CODEX):
            profile = _READINESS_PROFILES[agent]
            assert profile.quiet_s == DEFAULT_READINESS_QUIET_S, agent


_QUIET_PROBE_TIMEOUT_S = 0.3
_QUIET_PROBE_POLL_S = 0.02


def _install_claude_quiet_s(monkeypatch: pytest.MonkeyPatch, quiet_s: float) -> None:
    """Swap in a Claude profile with the given quiet_s, leaving others alone."""
    monkeypatch.setattr(
        agent_readiness,
        "_READINESS_PROFILES",
        {
            **_READINESS_PROFILES,
            AgentName.CLAUDE: MarkerLineReadinessProfile(
                marker=AgentName.CLAUDE.prompt_marker,
                quiet_s=quiet_s,
            ),
        },
    )


def _install_stable_claude_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stable snapshot containing the Claude prompt marker — digest is constant."""
    monkeypatch.setattr(
        agent_readiness.tmux_bridge,
        "capture_pane",
        AsyncMock(return_value=f"working\n{AgentName.CLAUDE.prompt_marker} ready"),
    )


class TestWaitForAgentReadyReadsQuietSFromProfile:
    # Mutation-proof contrast spans the two tests below. Each pins a single
    # behavioral path; together they prove the settle engine consumes
    # ``quiet_s`` from the profile per call (a hard-coded constant in
    # production would break at least one of the two).

    @pytest.mark.unit
    async def test_long_profile_quiet_s_blocks_settlement_within_outer_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _install_stable_claude_snapshot(monkeypatch)
        _install_claude_quiet_s(monkeypatch, quiet_s=5.0)

        ready, _tail = await agent_readiness.wait_for_agent_ready(
            AgentName.CLAUDE.value,
            _make_session(),
            timeout_s=_QUIET_PROBE_TIMEOUT_S,
            poll_interval_s=_QUIET_PROBE_POLL_S,
        )
        assert ready is False

    @pytest.mark.unit
    async def test_short_profile_quiet_s_allows_settlement_within_outer_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _install_stable_claude_snapshot(monkeypatch)
        _install_claude_quiet_s(monkeypatch, quiet_s=0.01)

        ready, _tail = await agent_readiness.wait_for_agent_ready(
            AgentName.CLAUDE.value,
            _make_session(),
            timeout_s=_QUIET_PROBE_TIMEOUT_S,
            poll_interval_s=_QUIET_PROBE_POLL_S,
        )
        assert ready is True


class TestRaceForReadiness:
    @pytest.mark.unit
    async def test_hook_wins_when_pane_never_settles(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No prompt visible — pane detector will keep polling until timeout.
        capture = _snapshot_sequence_factory([""])
        monkeypatch.setattr(agent_readiness.tmux_bridge, "capture_pane", capture)

        loop = asyncio.get_running_loop()
        ready_future: asyncio.Future[None] = loop.create_future()
        loop.call_later(0.02, lambda: ready_future.set_result(None))

        result = await race_for_readiness(
            agent_name=AgentName.CLAUDE.value,
            session=_make_session(),
            timeout_s=0.5,
            ready_future=ready_future,
        )

        assert result.winner == WINNER_HOOK
        # Hook wins before the pane snapshot is captured by the caller path.
        assert not result.tail

    @pytest.mark.unit
    async def test_pane_wins_when_hook_never_arrives(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stable snapshot containing a Claude prompt marker — pane should
        # settle within the unified quiet window.
        capture = _snapshot_sequence_factory([f"working\n{AgentName.CLAUDE.prompt_marker} ready"])
        monkeypatch.setattr(agent_readiness.tmux_bridge, "capture_pane", capture)
        # Shorten the quiet window so the test finishes well under timeout.
        monkeypatch.setattr(
            agent_readiness,
            "_READINESS_PROFILES",
            {
                **_READINESS_PROFILES,
                AgentName.CLAUDE: MarkerLineReadinessProfile(
                    marker=AgentName.CLAUDE.prompt_marker,
                    quiet_s=0.05,
                ),
            },
        )

        loop = asyncio.get_running_loop()
        ready_future: asyncio.Future[None] = loop.create_future()
        # Never set the future — pane must win.

        result = await race_for_readiness(
            agent_name=AgentName.CLAUDE.value,
            session=_make_session(),
            timeout_s=0.9,
            ready_future=ready_future,
        )

        assert result.winner == WINNER_PANE
        # Non-empty guard: the pane-win path must return the snapshot it
        # evaluated, not an empty placeholder. Content identity is governed
        # by wait_for_agent_ready's own tests; here we only assert that the
        # race plumbed the tail back to the caller at all.
        assert result.tail
        # The underlying future must remain alive — shield protected it from
        # cancellation of the hook wrapper.
        assert not ready_future.done()
        assert not ready_future.cancelled()

    @pytest.mark.unit
    async def test_hook_wins_first_pane_task_cancelled_cleanly(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pane has a valid marker — it would eventually settle — but the hook
        # fires first. The race helper must cancel the pane task in its
        # finally block; this test passes as long as the helper returns
        # promptly with winner=hook and no leftover capture-pane polling
        # continues beyond the helper's lifetime.
        captures: list[float] = []

        async def _capture(_tmux_session_name: str) -> str:
            captures.append(asyncio.get_running_loop().time())
            return f"{AgentName.CLAUDE.prompt_marker} ready"

        monkeypatch.setattr(
            agent_readiness.tmux_bridge,
            "capture_pane",
            AsyncMock(side_effect=_capture),
        )

        loop = asyncio.get_running_loop()
        ready_future: asyncio.Future[None] = loop.create_future()
        loop.call_later(0.01, lambda: ready_future.set_result(None))

        result = await race_for_readiness(
            agent_name=AgentName.CLAUDE.value,
            session=_make_session(),
            timeout_s=0.9,
            ready_future=ready_future,
        )
        assert result.winner == WINNER_HOOK

        # After the race returns, the pane task should be cancelled. Capture
        # calls must stop accumulating.
        captures_after_race = len(captures)
        await asyncio.sleep(0.3)  # well past one pane poll interval
        assert len(captures) == captures_after_race

    @pytest.mark.unit
    async def test_pane_loses_when_pane_snapshot_keeps_changing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Each capture differs above the marker — the digest never stabilizes,
        # so the quiet window cannot accumulate. With hook delayed past
        # timeout, the race must raise TimeoutError instead of falsely
        # claiming pane readiness.
        snapshots: list[str] = [f"line-{i}\nline-stable\n{AgentName.CLAUDE.prompt_marker} ready" for i in range(50)]

        async def _capture(_tmux_session_name: str) -> str:
            if snapshots:
                return snapshots.pop(0)
            return ""

        monkeypatch.setattr(
            agent_readiness.tmux_bridge,
            "capture_pane",
            AsyncMock(side_effect=_capture),
        )
        monkeypatch.setattr(
            agent_readiness,
            "_READINESS_PROFILES",
            {
                **_READINESS_PROFILES,
                AgentName.CLAUDE: MarkerLineReadinessProfile(
                    marker=AgentName.CLAUDE.prompt_marker,
                    quiet_s=0.5,  # > test timeout so a single stable digest cannot win
                ),
            },
        )

        loop = asyncio.get_running_loop()
        ready_future: asyncio.Future[None] = loop.create_future()

        with pytest.raises(TimeoutError):
            await race_for_readiness(
                agent_name=AgentName.CLAUDE.value,
                session=_make_session(),
                timeout_s=0.2,
                ready_future=ready_future,
            )

    @pytest.mark.unit
    async def test_race_works_for_every_registered_adapter(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Smoke: the hook-wins path must succeed regardless of adapter.
        capture = _snapshot_sequence_factory([""])
        monkeypatch.setattr(agent_readiness.tmux_bridge, "capture_pane", capture)

        for agent in (AgentName.CLAUDE, AgentName.GEMINI, AgentName.CODEX):
            loop = asyncio.get_running_loop()
            ready_future: asyncio.Future[None] = loop.create_future()
            loop.call_later(0.01, lambda f=ready_future: f.set_result(None))

            result = await race_for_readiness(
                agent_name=agent.value,
                session=_make_session(),
                timeout_s=0.5,
                ready_future=ready_future,
            )
            assert result.winner == WINNER_HOOK, agent

    @pytest.mark.unit
    async def test_pane_detector_exception_chains_into_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # When the pane detector crashes (e.g., tmux subprocess error), the
        # race must not mask the root cause as a generic timeout. The raised
        # TimeoutError must carry the underlying RuntimeError as __cause__.
        crash = RuntimeError("tmux capture-pane crashed")

        async def _capture(_tmux_session_name: str) -> str:
            raise crash

        monkeypatch.setattr(
            agent_readiness.tmux_bridge,
            "capture_pane",
            AsyncMock(side_effect=_capture),
        )

        loop = asyncio.get_running_loop()
        ready_future: asyncio.Future[None] = loop.create_future()

        with pytest.raises(TimeoutError) as exc_info:
            await race_for_readiness(
                agent_name=AgentName.CLAUDE.value,
                session=_make_session(),
                timeout_s=0.2,
                ready_future=ready_future,
            )
        assert exc_info.value.__cause__ is crash


@pytest.fixture(autouse=True)
async def _flush_pending_tasks() -> AsyncIterator[None]:
    """Yield then drain any background tasks the race helper leaves behind."""
    yield
    await asyncio.sleep(0)
