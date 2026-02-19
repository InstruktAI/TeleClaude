"""Unit tests for session_relay module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.session_relay import (
    RelayParticipant,
    _compute_delta,
    _fanout,
    _relay_by_session,
    _relay_lock,
    _relays,
    create_relay,
    get_relay,
    get_relay_for_session,
    stop_relay,
)


def _make_participant(
    sid: str = "sess-A", tmux: str = "tc_A", name: str = "Alice", number: int = 1
) -> RelayParticipant:
    return RelayParticipant(session_id=sid, tmux_session_name=tmux, name=name, number=number)


@pytest.fixture(autouse=True)
async def _clean_relay_state():
    """Ensure relay module state is clean before and after each test."""
    async with _relay_lock:
        _relays.clear()
        _relay_by_session.clear()
    yield
    relay_ids = list(_relays.keys())
    for rid in relay_ids:
        await stop_relay(rid)
    async with _relay_lock:
        _relays.clear()
        _relay_by_session.clear()


# ---------------------------------------------------------------------------
# _compute_delta
# ---------------------------------------------------------------------------


class TestComputeDelta:
    def test_empty_baseline_returns_full_current(self):
        assert _compute_delta("", "hello world") == "hello world"

    def test_prefix_match_returns_suffix(self):
        assert _compute_delta("hello ", "hello world") == "world"

    def test_identical_returns_empty(self):
        assert _compute_delta("hello", "hello") == ""

    def test_anchor_fallback_when_prefix_trimmed(self):
        # Baseline is long; scrollback trimmed the prefix but the anchor
        # (last 200 chars of baseline) still appears in current
        prefix = "A" * 300
        shared_tail = "B" * 200  # This becomes the 200-char anchor
        baseline = prefix + shared_tail
        current = shared_tail + "\nnew stuff"
        result = _compute_delta(baseline, current)
        assert result == "\nnew stuff"

    def test_no_overlap_returns_empty(self):
        assert _compute_delta("completely different", "no match at all") == ""


# ---------------------------------------------------------------------------
# create_relay / stop_relay / get_relay_for_session
# ---------------------------------------------------------------------------


class TestCreateRelay:
    @pytest.mark.asyncio
    async def test_create_relay_registers_state(self):
        participants = [_make_participant("sess-A", "tc_A", "Alice", 1), _make_participant("sess-B", "tc_B", "Bob", 2)]
        with (
            patch("teleclaude.core.session_relay.tmux_bridge") as mock_tmux,
            patch("teleclaude.core.session_relay.POLL_INTERVAL_SECONDS", 100),
        ):
            mock_tmux.capture_pane = AsyncMock(return_value="initial")
            mock_tmux.send_keys_existing_tmux = AsyncMock(return_value=True)
            relay_id = await create_relay(participants)

        assert relay_id is not None
        assert await get_relay_for_session("sess-A") == relay_id
        assert await get_relay_for_session("sess-B") == relay_id

        relay = await get_relay(relay_id)
        assert relay is not None
        assert len(relay.participants) == 2
        assert relay.active is True
        assert relay.baselines["sess-A"] == "initial"
        assert relay.baselines["sess-B"] == "initial"
        assert "sess-A" in relay._monitor_tasks
        assert "sess-B" in relay._monitor_tasks
        await stop_relay(relay_id)

    @pytest.mark.asyncio
    async def test_create_relay_with_three_participants(self):
        participants = [
            _make_participant("sess-A", "tc_A", "Alice", 1),
            _make_participant("sess-B", "tc_B", "Bob", 2),
            _make_participant("sess-C", "tc_C", "Carol", 3),
        ]
        with (
            patch("teleclaude.core.session_relay.tmux_bridge") as mock_tmux,
            patch("teleclaude.core.session_relay.POLL_INTERVAL_SECONDS", 100),
        ):
            mock_tmux.capture_pane = AsyncMock(return_value="")
            mock_tmux.send_keys_existing_tmux = AsyncMock(return_value=True)
            relay_id = await create_relay(participants)

        relay = await get_relay(relay_id)
        assert relay is not None
        assert len(relay.participants) == 3
        for sid in ("sess-A", "sess-B", "sess-C"):
            assert await get_relay_for_session(sid) == relay_id
        await stop_relay(relay_id)


class TestStopRelay:
    @pytest.mark.asyncio
    async def test_stop_relay_clears_state(self):
        participants = [_make_participant("sess-A", "tc_A", "Alice", 1), _make_participant("sess-B", "tc_B", "Bob", 2)]
        with (
            patch("teleclaude.core.session_relay.tmux_bridge") as mock_tmux,
            patch("teleclaude.core.session_relay.POLL_INTERVAL_SECONDS", 100),
        ):
            mock_tmux.capture_pane = AsyncMock(return_value="initial")
            mock_tmux.send_keys_existing_tmux = AsyncMock(return_value=True)
            relay_id = await create_relay(participants)

        result = await stop_relay(relay_id)
        assert result is True
        assert await get_relay_for_session("sess-A") is None
        assert await get_relay_for_session("sess-B") is None
        assert await get_relay(relay_id) is None

    @pytest.mark.asyncio
    async def test_stop_nonexistent_relay_returns_false(self):
        assert await stop_relay("nonexistent-id") is False


class TestMultipleConcurrentRelays:
    @pytest.mark.asyncio
    async def test_two_relays_independent(self):
        with (
            patch("teleclaude.core.session_relay.tmux_bridge") as mock_tmux,
            patch("teleclaude.core.session_relay.POLL_INTERVAL_SECONDS", 100),
        ):
            mock_tmux.capture_pane = AsyncMock(return_value="content")
            mock_tmux.send_keys_existing_tmux = AsyncMock(return_value=True)
            relay1 = await create_relay(
                [
                    _make_participant("sess-1A", "tc_1A", "Alice", 1),
                    _make_participant("sess-1B", "tc_1B", "Bob", 2),
                ]
            )
            relay2 = await create_relay(
                [
                    _make_participant("sess-2A", "tc_2A", "Carol", 1),
                    _make_participant("sess-2B", "tc_2B", "Dave", 2),
                ]
            )

        assert relay1 != relay2
        assert await get_relay_for_session("sess-1A") == relay1
        assert await get_relay_for_session("sess-2A") == relay2

        await stop_relay(relay1)
        assert await get_relay_for_session("sess-1A") is None
        assert await get_relay_for_session("sess-2A") == relay2
        await stop_relay(relay2)


# ---------------------------------------------------------------------------
# _fanout (direct invocation)
# ---------------------------------------------------------------------------


class TestFanout:
    @pytest.mark.asyncio
    async def test_fanout_delivers_to_peer_with_attribution(self):
        from teleclaude.core.session_relay import SessionRelay

        participants = [_make_participant("sess-A", "tc_A", "Alice", 1), _make_participant("sess-B", "tc_B", "Bob", 2)]
        relay = SessionRelay(relay_id="test-relay", participants=participants, baselines={"sess-A": "", "sess-B": ""})

        with patch("teleclaude.core.session_relay.tmux_bridge") as mock_tmux:
            mock_tmux.send_keys_existing_tmux = AsyncMock(return_value=True)
            mock_tmux.capture_pane = AsyncMock(return_value="updated pane")
            await _fanout(relay, participants[0], "Hello from Alice!")

        mock_tmux.send_keys_existing_tmux.assert_called_once()
        call_kwargs = mock_tmux.send_keys_existing_tmux.call_args
        assert call_kwargs.kwargs["session_name"] == "tc_B"
        assert "[Alice] (1):" in call_kwargs.kwargs["text"]
        assert "Hello from Alice!" in call_kwargs.kwargs["text"]
        assert call_kwargs.kwargs["send_enter"] is False

    @pytest.mark.asyncio
    async def test_fanout_delivers_to_all_peers(self):
        from teleclaude.core.session_relay import SessionRelay

        participants = [
            _make_participant("sess-A", "tc_A", "Alice", 1),
            _make_participant("sess-B", "tc_B", "Bob", 2),
            _make_participant("sess-C", "tc_C", "Carol", 3),
        ]
        relay = SessionRelay(
            relay_id="test-relay",
            participants=participants,
            baselines={"sess-A": "", "sess-B": "", "sess-C": ""},
        )

        with patch("teleclaude.core.session_relay.tmux_bridge") as mock_tmux:
            mock_tmux.send_keys_existing_tmux = AsyncMock(return_value=True)
            mock_tmux.capture_pane = AsyncMock(return_value="updated")
            await _fanout(relay, participants[0], "Hello!")

        # Should deliver to B and C, not A
        assert mock_tmux.send_keys_existing_tmux.call_count == 2
        targets = [c.kwargs["session_name"] for c in mock_tmux.send_keys_existing_tmux.call_args_list]
        assert "tc_B" in targets
        assert "tc_C" in targets
        assert "tc_A" not in targets

    @pytest.mark.asyncio
    async def test_fanout_updates_recipient_baselines(self):
        from teleclaude.core.session_relay import SessionRelay

        participants = [_make_participant("sess-A", "tc_A", "Alice", 1), _make_participant("sess-B", "tc_B", "Bob", 2)]
        relay = SessionRelay(
            relay_id="test-relay", participants=participants, baselines={"sess-A": "old", "sess-B": "old"}
        )

        with patch("teleclaude.core.session_relay.tmux_bridge") as mock_tmux:
            mock_tmux.send_keys_existing_tmux = AsyncMock(return_value=True)
            mock_tmux.capture_pane = AsyncMock(return_value="new-baseline-after-injection")
            await _fanout(relay, participants[0], "msg")

        assert relay.baselines["sess-B"] == "new-baseline-after-injection"
        # Sender baseline unchanged
        assert relay.baselines["sess-A"] == "old"


# ---------------------------------------------------------------------------
# Monitor output loop
# ---------------------------------------------------------------------------


class TestMonitorOutput:
    @pytest.mark.asyncio
    async def test_monitor_detects_delta_and_calls_fanout(self):
        """Monitor loop should detect delta and relay it."""
        from teleclaude.core.session_relay import SessionRelay, _monitor_output

        participants = [_make_participant("sess-A", "tc_A", "Alice", 1), _make_participant("sess-B", "tc_B", "Bob", 2)]
        relay = SessionRelay(
            relay_id="test-relay",
            participants=participants,
            baselines={"sess-A": "initial", "sess-B": "initial"},
        )

        poll_count = 0

        async def mock_capture(session_name: str) -> str:
            nonlocal poll_count
            poll_count += 1
            if session_name == "tc_A":
                if poll_count <= 1:
                    return "initial"
                # Return new content, then stop the relay so monitor exits
                relay.active = False
                return "initial\nnew output from A"
            return "initial"

        with (
            patch("teleclaude.core.session_relay.tmux_bridge") as mock_tmux,
            patch("teleclaude.core.session_relay.POLL_INTERVAL_SECONDS", 0),
        ):
            mock_tmux.capture_pane = AsyncMock(side_effect=mock_capture)
            mock_tmux.send_keys_existing_tmux = AsyncMock(return_value=True)
            await _monitor_output(relay, participants[0])

        # Should have delivered the delta to B
        mock_tmux.send_keys_existing_tmux.assert_called_once()
        call_kwargs = mock_tmux.send_keys_existing_tmux.call_args
        assert call_kwargs.kwargs["session_name"] == "tc_B"
        assert "new output from A" in call_kwargs.kwargs["text"]

    @pytest.mark.asyncio
    async def test_monitor_stops_on_empty_capture(self):
        from teleclaude.core.session_relay import SessionRelay, _monitor_output

        participants = [_make_participant("sess-A", "tc_A", "Alice", 1), _make_participant("sess-B", "tc_B", "Bob", 2)]
        relay = SessionRelay(
            relay_id="test-mon",
            participants=participants,
            baselines={"sess-A": "initial", "sess-B": "initial"},
        )
        # Register in module state so stop_relay can find it
        async with _relay_lock:
            _relays["test-mon"] = relay
            _relay_by_session["sess-A"] = "test-mon"
            _relay_by_session["sess-B"] = "test-mon"

        call_count = 0

        async def mock_capture(session_name: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ""  # Empty = session ended
            return "content"

        with (
            patch("teleclaude.core.session_relay.tmux_bridge") as mock_tmux,
            patch("teleclaude.core.session_relay.POLL_INTERVAL_SECONDS", 0),
        ):
            mock_tmux.capture_pane = AsyncMock(side_effect=mock_capture)
            mock_tmux.send_keys_existing_tmux = AsyncMock(return_value=True)
            await _monitor_output(relay, participants[0])

        assert relay.active is False

    @pytest.mark.asyncio
    async def test_monitor_stops_on_capture_exception(self):
        from teleclaude.core.session_relay import SessionRelay, _monitor_output

        participants = [_make_participant("sess-A", "tc_A", "Alice", 1), _make_participant("sess-B", "tc_B", "Bob", 2)]
        relay = SessionRelay(
            relay_id="test-exc",
            participants=participants,
            baselines={"sess-A": "initial", "sess-B": "initial"},
        )
        async with _relay_lock:
            _relays["test-exc"] = relay
            _relay_by_session["sess-A"] = "test-exc"
            _relay_by_session["sess-B"] = "test-exc"

        with (
            patch("teleclaude.core.session_relay.tmux_bridge") as mock_tmux,
            patch("teleclaude.core.session_relay.POLL_INTERVAL_SECONDS", 0),
        ):
            mock_tmux.capture_pane = AsyncMock(side_effect=RuntimeError("tmux gone"))
            mock_tmux.send_keys_existing_tmux = AsyncMock(return_value=True)
            await _monitor_output(relay, participants[0])

        assert relay.active is False


# ---------------------------------------------------------------------------
# Baseline prevents feedback loops
# ---------------------------------------------------------------------------


class TestBaselinePreventsReCapture:
    @pytest.mark.asyncio
    async def test_injected_content_not_recaptured(self):
        """After fanout, recipient baseline is updated so injected content is not re-captured."""
        from teleclaude.core.session_relay import SessionRelay

        participants = [_make_participant("sess-A", "tc_A", "Alice", 1), _make_participant("sess-B", "tc_B", "Bob", 2)]
        relay = SessionRelay(
            relay_id="test-bl", participants=participants, baselines={"sess-A": "initial", "sess-B": "initial"}
        )

        with patch("teleclaude.core.session_relay.tmux_bridge") as mock_tmux:
            mock_tmux.send_keys_existing_tmux = AsyncMock(return_value=True)
            # After injection, B's pane includes the injected content
            mock_tmux.capture_pane = AsyncMock(return_value="initial\n[Alice] (1):\n\nmsg\n")
            await _fanout(relay, participants[0], "msg")

        # B's baseline now includes injected content
        assert relay.baselines["sess-B"] == "initial\n[Alice] (1):\n\nmsg\n"
        # So computing delta against this baseline yields nothing
        delta = _compute_delta(relay.baselines["sess-B"], "initial\n[Alice] (1):\n\nmsg\n")
        assert delta == ""
