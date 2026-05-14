"""Unit tests for teleclaude.core.codex_readiness."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.codex_readiness import (
    CODEX_PROMPT_LIVE_DISTANCE,
    _find_codex_prompt_line,
    _stability_digest,
    wait_for_codex_prompt,
)

pytestmark = pytest.mark.unit


class TestFindCodexPromptLine:
    def test_returns_index_when_marker_at_bottom(self) -> None:
        pane = "boot line 1\nboot line 2\n› "
        assert _find_codex_prompt_line(pane) == 2

    def test_returns_index_when_marker_within_live_distance(self) -> None:
        # Marker on line 0, two status lines below — still within distance of 4.
        pane = "› \nstatus line 1\nstatus line 2"
        assert _find_codex_prompt_line(pane) == 0

    def test_returns_none_when_marker_buried_too_deep(self) -> None:
        # Marker is buried beyond CODEX_PROMPT_LIVE_DISTANCE — historical, not live.
        below = "\n".join(f"line {i}" for i in range(CODEX_PROMPT_LIVE_DISTANCE + 1))
        pane = f"› old prompt\n{below}"
        assert _find_codex_prompt_line(pane) is None

    def test_returns_none_when_no_marker(self) -> None:
        pane = "nothing\nto\nsee here"
        assert _find_codex_prompt_line(pane) is None

    def test_handles_ansi_escapes_before_marker(self) -> None:
        # ANSI SGR before the marker — strip_ansi_codes should remove them.
        pane = "\x1b[2m› \x1b[0m"
        assert _find_codex_prompt_line(pane) == 0

    def test_picks_latest_marker_when_multiple_present(self) -> None:
        # Older prompts higher up; the live one should be the one near the bottom.
        pane = "› old\nintermediate output\nmore output\n› current"
        assert _find_codex_prompt_line(pane) == 3


class TestStabilityDigest:
    def test_empty_when_prompt_at_top(self) -> None:
        assert _stability_digest("› prompt", 0) == ""

    def test_changes_when_region_above_changes(self) -> None:
        pane_a = "line one\nline two\n› "
        pane_b = "line one\nline two CHANGED\n› "
        assert _stability_digest(pane_a, 2) != _stability_digest(pane_b, 2)

    def test_stable_for_identical_pre_prompt_region(self) -> None:
        # Two captures with the same ANSI-stripped content above the prompt
        # produce the same digest, so the quiet-period check can recognize
        # them as settled.
        pane_a = "\x1b[1mbold\x1b[0m line\n› "
        pane_b = "\x1b[1mbold\x1b[0m line\n› "
        assert _stability_digest(pane_a, 2) == _stability_digest(pane_b, 2)


class TestWaitForCodexPrompt:
    async def test_returns_true_when_prompt_settles(self) -> None:
        """First two captures show marker; pre-prompt region stable across them → settled."""
        pane_steady = "boot\nready\n› "
        with patch(
            "teleclaude.core.codex_readiness.tmux_bridge.capture_pane",
            new=AsyncMock(side_effect=[pane_steady, pane_steady, pane_steady]),
        ):
            result = await wait_for_codex_prompt("tc_test", timeout_s=5.0, quiet_s=0.0, poll_interval_s=0.01)
        assert result is True

    async def test_returns_false_on_timeout_without_marker(self) -> None:
        pane_boot_only = "still booting\nno prompt yet\n"
        with patch(
            "teleclaude.core.codex_readiness.tmux_bridge.capture_pane",
            new=AsyncMock(return_value=pane_boot_only),
        ):
            result = await wait_for_codex_prompt("tc_test", timeout_s=0.05, quiet_s=0.0, poll_interval_s=0.01)
        assert result is False

    async def test_waits_for_quiet_period_when_region_keeps_changing(self) -> None:
        """Prompt visible but pre-prompt region keeps changing — must keep waiting."""
        changing = [
            "boot 1\nstatus a\n› ",
            "boot 1\nstatus b\n› ",
            "boot 1\nstatus c\n› ",
        ]
        with patch(
            "teleclaude.core.codex_readiness.tmux_bridge.capture_pane",
            new=AsyncMock(side_effect=changing + [changing[-1]]),
        ):
            # Quiet window is longer than the time it takes us to exhaust the
            # changing snapshots, so we never reach the "settled" branch in
            # the available frames. Verify we time out cleanly.
            result = await wait_for_codex_prompt("tc_test", timeout_s=0.1, quiet_s=10.0, poll_interval_s=0.01)
        assert result is False

    async def test_pane_capture_exception_does_not_crash(self) -> None:
        """tmux capture transient failure → retry loop, not exception escape."""
        with patch(
            "teleclaude.core.codex_readiness.tmux_bridge.capture_pane",
            new=AsyncMock(side_effect=RuntimeError("tmux gone")),
        ):
            result = await wait_for_codex_prompt("tc_test", timeout_s=0.05, quiet_s=0.0, poll_interval_s=0.01)
        # Loop swallows the exception and times out cleanly.
        assert result is False
