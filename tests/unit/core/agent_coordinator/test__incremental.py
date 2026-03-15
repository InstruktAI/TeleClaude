"""Characterization tests for teleclaude.core.agent_coordinator._incremental."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.agent_coordinator._incremental import _IncrementalOutputMixin


def _make_mixin() -> _IncrementalOutputMixin:
    """Create a minimal _IncrementalOutputMixin instance with required state dicts."""
    mixin = object.__new__(_IncrementalOutputMixin)
    mixin._incremental_noop_state = {}
    mixin._tool_use_skip_state = {}
    mixin._incremental_eval_state = {}
    mixin._incremental_render_digests = {}
    mixin._incremental_output_locks = {}
    mixin._last_emitted_status = {}
    return mixin


class TestSuppressionSignature:
    @pytest.mark.unit
    def test_same_inputs_produce_same_signature(self):
        mixin = _make_mixin()
        sig1 = mixin._suppression_signature("a", "b", 1)
        sig2 = mixin._suppression_signature("a", "b", 1)
        assert sig1 == sig2

    @pytest.mark.unit
    def test_different_inputs_produce_different_signature(self):
        mixin = _make_mixin()
        sig1 = mixin._suppression_signature("a", "b")
        sig2 = mixin._suppression_signature("a", "c")
        assert sig1 != sig2

    @pytest.mark.unit
    def test_none_parts_handled(self):
        mixin = _make_mixin()
        sig = mixin._suppression_signature(None, "x", None)
        assert isinstance(sig, str)
        assert len(sig) > 0

    @pytest.mark.unit
    def test_returns_hex_string(self):
        mixin = _make_mixin()
        sig = mixin._suppression_signature("test")
        # sha256 hex digest is 64 chars
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)


class TestMarkIncrementalNoop:
    @pytest.mark.unit
    def test_first_call_creates_state_entry(self):
        mixin = _make_mixin()
        mixin._mark_incremental_noop("sess-001", reason="test_reason", signature="sig1")
        assert "sess-001" in mixin._incremental_noop_state

    @pytest.mark.unit
    def test_new_state_has_zero_suppressed(self):
        mixin = _make_mixin()
        mixin._mark_incremental_noop("sess-001", reason="test_reason", signature="sig1")
        state = mixin._incremental_noop_state["sess-001"]
        assert state.suppressed == 0

    @pytest.mark.unit
    def test_same_signature_increments_suppressed(self):
        mixin = _make_mixin()
        mixin._mark_incremental_noop("sess-001", reason="test_reason", signature="sig1")
        mixin._mark_incremental_noop("sess-001", reason="test_reason", signature="sig1")
        state = mixin._incremental_noop_state["sess-001"]
        assert state.suppressed == 1

    @pytest.mark.unit
    def test_different_signature_resets_state(self):
        mixin = _make_mixin()
        mixin._mark_incremental_noop("sess-001", reason="r1", signature="sig1")
        mixin._mark_incremental_noop("sess-001", reason="r1", signature="sig1")
        # Now different signature resets
        mixin._mark_incremental_noop("sess-001", reason="r2", signature="sig2")
        state = mixin._incremental_noop_state["sess-001"]
        assert state.signature == "sig2"
        assert state.suppressed == 0


class TestClearIncrementalNoop:
    @pytest.mark.unit
    def test_no_state_is_noop(self):
        mixin = _make_mixin()
        mixin._clear_incremental_noop("sess-001", outcome="cleared")

    @pytest.mark.unit
    def test_clears_existing_state(self):
        mixin = _make_mixin()
        mixin._mark_incremental_noop("sess-001", reason="r1", signature="sig1")
        assert "sess-001" in mixin._incremental_noop_state
        mixin._clear_incremental_noop("sess-001", outcome="done")
        assert "sess-001" not in mixin._incremental_noop_state


class TestMarkToolUseSkip:
    @pytest.mark.unit
    def test_first_call_creates_state_entry(self):
        mixin = _make_mixin()
        mixin._mark_tool_use_skip("sess-001")
        assert "sess-001" in mixin._tool_use_skip_state

    @pytest.mark.unit
    def test_repeated_call_increments_suppressed(self):
        mixin = _make_mixin()
        mixin._mark_tool_use_skip("sess-001")
        mixin._mark_tool_use_skip("sess-001")
        state = mixin._tool_use_skip_state["sess-001"]
        assert state.suppressed == 1

    @pytest.mark.unit
    def test_state_signature_is_fixed(self):
        mixin = _make_mixin()
        mixin._mark_tool_use_skip("sess-001")
        state = mixin._tool_use_skip_state["sess-001"]
        assert state.signature == "tool_use_already_set"


class TestClearToolUseSkip:
    @pytest.mark.unit
    def test_no_state_is_noop(self):
        mixin = _make_mixin()
        mixin._clear_tool_use_skip("sess-001")

    @pytest.mark.unit
    def test_clears_existing_state_with_suppressed(self):
        mixin = _make_mixin()
        mixin._mark_tool_use_skip("sess-001")
        mixin._mark_tool_use_skip("sess-001")
        assert "sess-001" in mixin._tool_use_skip_state
        mixin._clear_tool_use_skip("sess-001")
        assert "sess-001" not in mixin._tool_use_skip_state

    @pytest.mark.unit
    def test_state_with_zero_suppressed_clears_silently(self):
        mixin = _make_mixin()
        mixin._mark_tool_use_skip("sess-001")
        mixin._clear_tool_use_skip("sess-001")
        assert "sess-001" not in mixin._tool_use_skip_state


class TestMaybeSendIncrementalOutput:
    @pytest.mark.unit
    async def test_creates_lock_if_missing(self):
        mixin = _make_mixin()
        mixin.client = MagicMock()
        with patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await mixin._maybe_send_incremental_output("sess-001", MagicMock())
        assert "sess-001" in mixin._incremental_output_locks

    @pytest.mark.unit
    async def test_reuses_existing_lock(self):
        mixin = _make_mixin()
        import asyncio as _asyncio

        existing_lock = _asyncio.Lock()
        mixin._incremental_output_locks["sess-001"] = existing_lock
        with patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            await mixin._maybe_send_incremental_output("sess-001", MagicMock())
        assert mixin._incremental_output_locks["sess-001"] is existing_lock

    @pytest.mark.unit
    async def test_returns_false_when_no_session(self):
        mixin = _make_mixin()
        with patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            result = await mixin._maybe_send_incremental_output("sess-001", MagicMock())
        assert result is False


class TestMaybeSendIncrementalOutputUnlocked:
    @pytest.mark.unit
    async def test_no_session_returns_false(self):
        mixin = _make_mixin()
        with patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            result = await mixin._maybe_send_incremental_output_unlocked("sess-001", MagicMock())
        assert result is False

    @pytest.mark.unit
    async def test_no_agent_key_returns_false(self):
        mixin = _make_mixin()
        session = MagicMock()
        session.active_agent = None
        payload = MagicMock()
        payload.raw = {"agent_name": ""}
        with patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._maybe_send_incremental_output_unlocked("sess-001", payload)
        assert result is False

    @pytest.mark.unit
    async def test_threaded_output_disabled_returns_false(self):
        mixin = _make_mixin()
        session = MagicMock()
        session.active_agent = "claude"
        payload = MagicMock()
        payload.raw = {"agent_name": "claude"}
        with (
            patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._incremental.is_threaded_output_enabled",
                return_value=False,
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._maybe_send_incremental_output_unlocked("sess-001", payload)
        assert result is False
        assert "sess-001" in mixin._incremental_noop_state

    @pytest.mark.unit
    async def test_no_transcript_path_returns_false(self):
        mixin = _make_mixin()
        session = MagicMock()
        session.active_agent = "claude"
        session.native_log_file = None
        payload = MagicMock()
        payload.raw = {"agent_name": "claude"}
        payload.transcript_path = None
        with (
            patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._incremental.is_threaded_output_enabled",
                return_value=True,
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._maybe_send_incremental_output_unlocked("sess-001", payload)
        assert result is False
        assert "sess-001" in mixin._incremental_noop_state

    @pytest.mark.unit
    async def test_no_assistant_messages_returns_false(self):
        mixin = _make_mixin()
        session = MagicMock()
        session.active_agent = "claude"
        session.native_log_file = "/path/log"
        session.last_tool_done_at = None
        payload = MagicMock()
        payload.raw = {"agent_name": "claude"}
        payload.transcript_path = "/path/log"
        with (
            patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._incremental.is_threaded_output_enabled",
                return_value=True,
            ),
            patch(
                "teleclaude.core.agent_coordinator._incremental._has_active_output_message",
                return_value=False,
            ),
            patch(
                "teleclaude.core.agent_coordinator._incremental.get_assistant_messages_since",
                return_value=[],
            ),
            patch(
                "teleclaude.core.agent_coordinator._incremental.count_renderable_assistant_blocks",
                return_value=0,
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._maybe_send_incremental_output_unlocked("sess-001", payload)
        assert result is False
        assert "sess-001" in mixin._incremental_noop_state

    @pytest.mark.unit
    async def test_unchanged_digest_returns_false(self):
        mixin = _make_mixin()
        mixin._incremental_render_digests["sess-001"] = "existing-digest"
        session = MagicMock()
        session.active_agent = "claude"
        session.native_log_file = "/path/log"
        session.last_tool_done_at = None
        payload = MagicMock()
        payload.raw = {"agent_name": "claude"}
        payload.transcript_path = "/path/log"

        # Produce the same digest as already stored
        from hashlib import sha256

        message_text = "Hello"
        expected_digest = sha256(message_text.encode()).hexdigest()
        mixin._incremental_render_digests["sess-001"] = expected_digest

        with (
            patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._incremental.is_threaded_output_enabled",
                return_value=True,
            ),
            patch(
                "teleclaude.core.agent_coordinator._incremental._has_active_output_message",
                return_value=False,
            ),
            patch(
                "teleclaude.core.agent_coordinator._incremental.get_assistant_messages_since",
                return_value=["msg"],
            ),
            patch(
                "teleclaude.core.agent_coordinator._incremental.count_renderable_assistant_blocks",
                return_value=1,
            ),
            patch(
                "teleclaude.core.agent_coordinator._incremental.render_clean_agent_output",
                return_value=(message_text, None),
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            result = await mixin._maybe_send_incremental_output_unlocked("sess-001", payload)
        assert result is False

    @pytest.mark.unit
    async def test_sends_output_and_stores_digest(self):
        mixin = _make_mixin()
        mixin.client = MagicMock()
        mixin.client.send_threaded_output = AsyncMock()
        mixin.client.break_threaded_turn = AsyncMock()
        session = MagicMock()
        session.active_agent = "claude"
        session.native_log_file = "/path/log"
        session.last_tool_done_at = None
        payload = MagicMock()
        payload.raw = {"agent_name": "claude"}
        payload.transcript_path = "/path/log"

        fresh_session = MagicMock()
        fresh_session.active_agent = "claude"

        with (
            patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._incremental.is_threaded_output_enabled",
                return_value=True,
            ),
            patch(
                "teleclaude.core.agent_coordinator._incremental._has_active_output_message",
                return_value=False,
            ),
            patch(
                "teleclaude.core.agent_coordinator._incremental.get_assistant_messages_since",
                return_value=["msg"],
            ),
            patch(
                "teleclaude.core.agent_coordinator._incremental.count_renderable_assistant_blocks",
                return_value=1,
            ),
            patch(
                "teleclaude.core.agent_coordinator._incremental.render_clean_agent_output",
                return_value=("New agent output", None),
            ),
        ):
            mock_db.get_session = AsyncMock(side_effect=[session, fresh_session])
            mock_db.update_session = AsyncMock()
            result = await mixin._maybe_send_incremental_output_unlocked("sess-001", payload)

        assert result is True
        mixin.client.send_threaded_output.assert_called_once()  # pyright: ignore[reportAttributeAccessIssue]
        assert "sess-001" in mixin._incremental_render_digests


class TestTriggerIncrementalOutput:
    @pytest.mark.unit
    async def test_no_session_returns_false(self):
        mixin = _make_mixin()
        with patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=None)
            result = await mixin.trigger_incremental_output("sess-001")
        assert result is False

    @pytest.mark.unit
    async def test_threaded_output_disabled_returns_false(self):
        mixin = _make_mixin()
        mock_session = MagicMock()
        mock_session.active_agent = "claude"
        with (
            patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._incremental.is_threaded_output_enabled",
                return_value=False,
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=mock_session)
            result = await mixin.trigger_incremental_output("sess-001")
        assert result is False

    @pytest.mark.unit
    async def test_completed_status_returns_false(self):
        mixin = _make_mixin()
        mixin._last_emitted_status["sess-001"] = "completed"
        mock_session = MagicMock()
        mock_session.active_agent = "claude"
        with (
            patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._incremental.is_threaded_output_enabled",
                return_value=True,
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=mock_session)
            result = await mixin.trigger_incremental_output("sess-001")
        assert result is False

    @pytest.mark.unit
    async def test_closed_status_returns_false(self):
        mixin = _make_mixin()
        mixin._last_emitted_status["sess-001"] = "closed"
        mock_session = MagicMock()
        mock_session.active_agent = "claude"
        with (
            patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._incremental.is_threaded_output_enabled",
                return_value=True,
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=mock_session)
            result = await mixin.trigger_incremental_output("sess-001")
        assert result is False

    @pytest.mark.unit
    async def test_error_status_returns_false(self):
        mixin = _make_mixin()
        mixin._last_emitted_status["sess-001"] = "error"
        mock_session = MagicMock()
        mock_session.active_agent = "claude"
        with (
            patch("teleclaude.core.agent_coordinator._incremental.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator._incremental.is_threaded_output_enabled",
                return_value=True,
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=mock_session)
            result = await mixin.trigger_incremental_output("sess-001")
        assert result is False
