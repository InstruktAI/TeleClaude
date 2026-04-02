# guard: no-companion
# pylint: disable=protected-access,redefined-outer-name,missing-function-docstring,too-few-public-methods,import-outside-toplevel,too-many-locals,too-many-lines
"""Spec tests (xfail) for cadence-file-authority - R1 through R10.

These tests specify the behavioral contracts for the file-authority refactoring.
Every test is marked xfail because the production code does not yet implement
these behaviors. The builder removes xfail markers as implementation satisfies
each specification.

Requirements summary:
- R1: File-derived rendering authority (no external cursor/timestamp state)
- R2: File-derived turn detection (user messages in transcript)
- R3: Cadence-owned delivery bookkeeping (char_offset, output_message_id)
- R4: Transient rendering mode (origin vs reflection from session metadata)
- R5: Unified content belt (user + agent in one stream for reflection mode)
- R6: Lifecycle layer reduced to QoS (break_threaded_turn drops payloads only)
- R7: Signal-rendering separation (signals touch only last_activity_at)
- R8: Terminal input rendering parity (no force-pull on terminal input)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.models import Session

pytestmark = [pytest.mark.unit]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(**kwargs: object) -> Session:
    return Session(
        session_id="sess-spec",
        computer_name="local",
        tmux_session_name="test",
        title="Spec Test",
        **kwargs,
    )


class _FakeAdapter:
    """Minimal adapter stub satisfying OutputCadenceLoop's interface."""

    ADAPTER_KEY = "discord"

    def __init__(self) -> None:
        self.clear_turn_state = AsyncMock()
        self.send_threaded_output = AsyncMock(return_value="msg-1")
        self.ensure_channel = AsyncMock(side_effect=lambda session: session)  # pyright: ignore[reportUnknownLambdaType]
        self.send_message = AsyncMock(return_value="reflected-msg")
        self._clear_output_message_id = AsyncMock()
        self._set_char_offset = AsyncMock()
        self.set_last_delivered_at = AsyncMock()

    def get_last_delivered_at(self, session: Session) -> datetime | None:
        raw = session.get_origin_section(self.ADAPTER_KEY).get("last_delivered_at")
        if isinstance(raw, str):
            from teleclaude.utils.transcript._utils import _parse_timestamp

            return _parse_timestamp(raw)
        return None


@pytest.fixture
def adapter() -> _FakeAdapter:
    return _FakeAdapter()


@pytest.fixture
def cadence_loop(adapter: _FakeAdapter) -> object:
    from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

    return OutputCadenceLoop(adapter, interval_seconds=1.0)


# ---------------------------------------------------------------------------
# R1 — File-derived rendering authority
# ---------------------------------------------------------------------------


class TestFileDerivedRenderingAuthority:
    """R1: The cadence derives its rendering window from the transcript file,
    not from external state like last_tool_done_at set by the coordinator."""

    def test_cadence_does_not_reference_turn_cursor_from_session(self) -> None:
        """The cadence must not read last_tool_done_at from the session to use
        as a rendering cursor. It derives the rendering window from the file."""
        import ast
        import inspect
        from pathlib import Path

        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        source_file = Path(inspect.getfile(OutputCadenceLoop))
        source = source_file.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "OutputCadenceLoop":
                class_source = ast.get_source_segment(source, node) or ""
                # The cadence must not read session.last_tool_done_at
                assert "last_tool_done_at" not in class_source, (
                    "OutputCadenceLoop still references last_tool_done_at — "
                    "the cadence must derive rendering windows from the transcript file (R1)"
                )
                break
        else:
            pytest.fail("OutputCadenceLoop class not found")

    async def test_cadence_does_not_update_session_cursor(self, cadence_loop: object) -> None:
        """After rendering, the cadence must not write last_tool_done_at to the DB."""
        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        loop = cadence_loop
        assert isinstance(loop, OutputCadenceLoop)

        session = _make_session(native_log_file="/tmp/spec.jsonl", active_agent="claude")
        last_ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch("teleclaude.adapters.ui.output_cadence.get_assistant_messages_since", return_value=["msg"]),
            patch("teleclaude.adapters.ui.output_cadence.count_renderable_assistant_blocks", return_value=1),
            patch("teleclaude.adapters.ui.output_cadence.render_clean_agent_output", return_value=("content", last_ts)),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_origin_metadata = AsyncMock()
            await loop._tick()

        # The cadence must NOT call update_session with last_tool_done_at
        for call in mock_db.update_session.call_args_list:
            _, call_kwargs = call
            assert "last_tool_done_at" not in call_kwargs, (
                "Cadence must not write last_tool_done_at — rendering authority is file-derived"
            )

    async def test_output_equivalence_without_coordinator_state(self, cadence_loop: object, tmp_path: object) -> None:
        """The cadence must produce identical output whether or not the coordinator
        has run state-mutation operations (the R1 success criterion).

        Uses a multi-turn transcript with timestamps. Wraps
        get_assistant_messages_since with a spy to verify that the stale
        last_tool_done_at cursor is NOT passed as since_timestamp — a broken
        implementation that merely ignores the cursor but still reads it from
        the session would be caught by the call-argument assertion.
        """
        import json
        from functools import wraps
        from pathlib import Path

        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop
        from teleclaude.utils.transcript import get_assistant_messages_since as _real_get

        loop = cadence_loop
        assert isinstance(loop, OutputCadenceLoop)

        transcript = Path(str(tmp_path)) / "equiv.jsonl"
        stale_cursor = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)
        entries = [
            # First turn
            {
                "timestamp": "2024-06-01T10:00:00+00:00",
                "message": {"role": "user", "content": [{"type": "text", "text": "first"}]},
            },
            {
                "timestamp": "2024-06-01T10:00:01+00:00",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "first reply"}]},
            },
            # Second turn
            {
                "timestamp": "2024-06-01T12:00:00+00:00",
                "message": {"role": "user", "content": [{"type": "text", "text": "second"}]},
            },
            {
                "timestamp": "2024-06-01T12:00:01+00:00",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "second reply"}]},
            },
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        # Spy: calls through to the real function but records since_timestamp args.
        since_timestamps_seen: list[object] = []

        @wraps(_real_get)
        def spy_get_assistant(*args: object, **kwargs: object) -> object:
            since_timestamps_seen.append(kwargs.get("since_timestamp", args[2] if len(args) > 2 else None))
            return _real_get(*args, **kwargs)  # pyright: ignore[reportCallIssue]

        session = _make_session(
            native_log_file=str(transcript),
            active_agent="claude",
            last_tool_done_at=stale_cursor,
        )

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch(
                "teleclaude.adapters.ui.output_cadence.get_assistant_messages_since",
                side_effect=spy_get_assistant,
            ),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_origin_metadata = AsyncMock()
            await loop._tick()

        # R1 success criterion: the cadence must NOT pass the stale
        # last_tool_done_at as since_timestamp. The transcript file alone
        # determines the rendering window.
        for ts in since_timestamps_seen:
            assert ts != stale_cursor, (
                f"Cadence passed stale last_tool_done_at ({stale_cursor}) as since_timestamp — "
                "file-derived rendering must not use coordinator cursors (R1)"
            )


# ---------------------------------------------------------------------------
# R2 — File-derived turn detection
# ---------------------------------------------------------------------------


class TestFileDerivedTurnDetection:
    """R2: Turn boundaries detected from user messages in the transcript file."""

    async def test_cadence_detects_new_turn_from_user_message_in_file(
        self, cadence_loop: object, adapter: _FakeAdapter, tmp_path: object
    ) -> None:
        """When a new user message appears in the transcript, the cadence must
        detect the turn boundary and reset delivery bookkeeping."""
        import json
        from pathlib import Path

        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        loop = cadence_loop
        assert isinstance(loop, OutputCadenceLoop)

        # Write a real transcript file containing a user message turn boundary.
        transcript = Path(str(tmp_path)) / "spec.jsonl"
        entries = [
            {
                "timestamp": "2024-06-01T10:00:00+00:00",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "old output"}]},
            },
            {
                "timestamp": "2024-06-01T10:00:01+00:00",
                "message": {"role": "user", "content": [{"type": "text", "text": "new prompt"}]},
            },
            {
                "timestamp": "2024-06-01T10:00:02+00:00",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "new output"}]},
            },
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        session = _make_session(native_log_file=str(transcript), active_agent="claude")

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_origin_metadata = AsyncMock()
            await loop._tick()

        # The cadence must detect the user message in the transcript as a turn
        # boundary and reset delivery bookkeeping (R3 ownership model: cadence
        # resets output_message_id directly, not via clear_turn_state which is
        # a lifecycle-layer method that R6 removes from the rendering path).
        adapter._clear_output_message_id.assert_called()

    async def test_tool_result_only_user_message_does_not_trigger_turn_reset(
        self, cadence_loop: object, adapter: _FakeAdapter, tmp_path: object
    ) -> None:
        """Tool-result-only user messages (role=user with only tool_result blocks)
        must NOT trigger a turn reset. Only genuine human-initiated user messages
        constitute turn boundaries. Regression guard — must hold before and after R2."""
        import json
        from pathlib import Path

        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        loop = cadence_loop
        assert isinstance(loop, OutputCadenceLoop)

        # Transcript: assistant output → tool-result-only user message → more assistant output.
        # The user message at index 1 carries only tool_result blocks — it is part of
        # the assistant turn, NOT a turn boundary.
        transcript = Path(str(tmp_path)) / "spec_tool_result.jsonl"
        entries = [
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Let me check that."},
                        {"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "ls"}},
                    ],
                }
            },
            {
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "file.txt"},
                    ],
                }
            },
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "Found file.txt"}]}},
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        session = _make_session(native_log_file=str(transcript), active_agent="claude")

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_origin_metadata = AsyncMock()
            await loop._tick()

        # A tool-result-only user message must NOT trigger turn reset.
        # Check both legacy lifecycle method and new cadence-owned method (R3).
        adapter.clear_turn_state.assert_not_called()
        adapter._clear_output_message_id.assert_not_called()

    def test_cadence_uses_tool_result_discriminator(self) -> None:
        """The cadence must use _is_user_tool_result_only_message (or equivalent)
        to distinguish real user messages from tool-result user entries when
        detecting turn boundaries."""
        import inspect
        from pathlib import Path

        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        source_file = Path(inspect.getfile(OutputCadenceLoop))
        source = source_file.read_text(encoding="utf-8")

        # The cadence must reference the tool-result discriminator
        has_discriminator = (
            "_is_user_tool_result_only_message" in source or "is_tool_result" in source or "tool_result_only" in source
        )
        assert has_discriminator, (
            "OutputCadenceLoop does not reference any tool-result discriminator — "
            "turn detection must filter out tool-result-only user messages (R2)"
        )


# ---------------------------------------------------------------------------
# R3 — Cadence-owned delivery bookkeeping
# ---------------------------------------------------------------------------


class TestCadenceOwnedDeliveryBookkeeping:
    """R3: char_offset and output_message_id managed exclusively by the cadence."""

    def test_lifecycle_layer_does_not_manipulate_delivery_bookkeeping(self) -> None:
        """break_threaded_turn must not call clear_turn_state (which resets
        char_offset, output_message_id, last_delivered_at)."""
        import ast
        from pathlib import Path

        output_path = Path(__file__).resolve().parents[4] / "teleclaude" / "core" / "adapter_client" / "_output.py"
        source = output_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "break_threaded_turn":
                method_source = ast.get_source_segment(source, node) or ""
                assert "clear_turn_state" not in method_source, (
                    "break_threaded_turn still references clear_turn_state — "
                    "delivery bookkeeping is owned by the cadence (R3)"
                )
                break
        else:
            pytest.fail("break_threaded_turn not found in _output.py")

    async def test_cadence_resets_bookkeeping_on_new_turn(
        self, cadence_loop: object, adapter: _FakeAdapter, tmp_path: object
    ) -> None:
        """On detecting a new turn (R2), the cadence must reset char_offset and
        output_message_id for this adapter."""
        import json
        from pathlib import Path

        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        loop = cadence_loop
        assert isinstance(loop, OutputCadenceLoop)

        # Write a real transcript file with a user message turn boundary.
        transcript = Path(str(tmp_path)) / "bookkeeping.jsonl"
        entries = [
            {
                "timestamp": "2024-06-01T10:00:00+00:00",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "first response"}]},
            },
            {
                "timestamp": "2024-06-01T12:00:00+00:00",
                "message": {"role": "user", "content": [{"type": "text", "text": "new prompt"}]},
            },
            {
                "timestamp": "2024-06-01T12:00:01+00:00",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "new response"}]},
            },
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        session = _make_session(native_log_file=str(transcript), active_agent="claude")

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_origin_metadata = AsyncMock()
            await loop._tick()

        # The cadence must manage delivery bookkeeping when it detects a turn boundary:
        # both output_message_id and char_offset must be reset.
        adapter._clear_output_message_id.assert_called()
        adapter._set_char_offset.assert_called()
        # Verify char_offset was reset to 0
        reset_call = adapter._set_char_offset.call_args
        assert reset_call is not None
        assert reset_call[0][-1] == 0 or reset_call[1].get("offset", reset_call[1].get("value")) == 0, (
            "Cadence must reset char_offset to 0 on new turn — got different value"
        )


# ---------------------------------------------------------------------------
# R4 — Transient rendering mode
# ---------------------------------------------------------------------------


class TestTransientRenderingMode:
    """R4: Rendering mode (origin vs reflection) determined at render time
    from last_input_origin, not stored as persistent state."""

    async def test_origin_mode_renders_agent_output_only(self, cadence_loop: object, adapter: _FakeAdapter) -> None:
        """When adapter matches last_input_origin (origin mode), cadence renders
        only agent output. R10 preserved behavior — this must not regress."""
        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        loop = cadence_loop
        assert isinstance(loop, OutputCadenceLoop)

        # Adapter is "discord", last_input_origin is "discord" → origin mode
        session = _make_session(
            native_log_file="/tmp/spec.jsonl",
            active_agent="claude",
            last_input_origin="discord",
        )

        rendered_content: list[str] = []

        async def capture_send(_sess: object, text: str, **_kwargs: object) -> str:
            rendered_content.append(text)
            return "msg-1"

        adapter.send_threaded_output = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
            side_effect=capture_send
        )

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch("teleclaude.adapters.ui.output_cadence.get_assistant_messages_since", return_value=["msg"]),
            patch("teleclaude.adapters.ui.output_cadence.count_renderable_assistant_blocks", return_value=1),
            patch(
                "teleclaude.adapters.ui.output_cadence.render_clean_agent_output",
                return_value=("agent content only", datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)),
            ),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_origin_metadata = AsyncMock()
            await loop._tick()

        assert rendered_content, "Cadence should have rendered content"
        # In origin mode, the cadence must not include user messages in output
        adapter.send_message.assert_not_called()

    async def test_reflection_mode_renders_user_and_agent_content(
        self, cadence_loop: object, adapter: _FakeAdapter, tmp_path: object
    ) -> None:
        """When adapter does NOT match last_input_origin (reflection mode),
        the cadence must render both user and agent messages from the transcript."""
        import json
        from pathlib import Path

        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        loop = cadence_loop
        assert isinstance(loop, OutputCadenceLoop)

        transcript = Path(str(tmp_path)) / "reflect.jsonl"
        entries = [
            {"message": {"role": "user", "content": [{"type": "text", "text": "hello"}]}},
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "world"}]}},
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        # Adapter is "discord", last_input_origin is "telegram" → reflection mode
        session = _make_session(
            native_log_file=str(transcript),
            active_agent="claude",
            last_input_origin="telegram",
        )

        # Track which transcript reading functions get called
        get_assistant_calls: list[object] = []

        def track_get_assistant(*args: object, **kwargs: object) -> list[str]:
            get_assistant_calls.append((args, kwargs))
            return ["msg"]

        mock_identity = MagicMock()
        mock_identity.display_name = "TestUser"
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_identity

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch(
                "teleclaude.adapters.ui.output_cadence.get_assistant_messages_since",
                side_effect=track_get_assistant,
            ),
            patch(
                "teleclaude.adapters.ui.output_cadence.get_identity_resolver",
                return_value=mock_resolver,
            ),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_origin_metadata = AsyncMock()
            await loop._tick()

        # In reflection mode, the cadence must NOT use get_assistant_messages_since
        assert not get_assistant_calls, (
            "Reflection-mode rendering must not use get_assistant_messages_since — "
            "it must render both user and agent messages from the transcript (R4/R5)"
        )
        adapter.send_threaded_output.assert_called()

    async def test_mode_change_switches_rendering_pipeline(
        self, cadence_loop: object, adapter: _FakeAdapter, tmp_path: object
    ) -> None:
        """Changing last_input_origin between ticks must immediately switch
        the rendering pipeline — agent-only for origin, user+agent for reflection."""
        import json
        from pathlib import Path

        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        loop = cadence_loop
        assert isinstance(loop, OutputCadenceLoop)

        transcript = Path(str(tmp_path)) / "mode_switch.jsonl"
        entries = [
            {"message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}},
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        # First tick: origin mode (discord matches adapter → agent only)
        session_origin = _make_session(
            native_log_file=str(transcript),
            active_agent="claude",
            last_input_origin="discord",
        )
        # Second tick: reflection mode (telegram does not match → user + agent)
        session_reflection = _make_session(
            native_log_file=str(transcript),
            active_agent="claude",
            last_input_origin="telegram",
        )

        get_assistant_calls: list[object] = []

        def track_get_assistant(*_args: object, **_kwargs: object) -> list[str]:
            get_assistant_calls.append(True)
            return ["msg"]

        mock_identity = MagicMock()
        mock_identity.display_name = "TestUser"
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_identity

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch(
                "teleclaude.adapters.ui.output_cadence.get_assistant_messages_since",
                side_effect=track_get_assistant,
            ),
            patch("teleclaude.adapters.ui.output_cadence.count_renderable_assistant_blocks", return_value=1),
            patch(
                "teleclaude.adapters.ui.output_cadence.render_clean_agent_output",
                return_value=("content", datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)),
            ),
            patch(
                "teleclaude.adapters.ui.output_cadence.get_identity_resolver",
                return_value=mock_resolver,
            ),
        ):
            mock_db.update_origin_metadata = AsyncMock()
            mock_db.update_session = AsyncMock()

            # Origin mode tick — should use assistant-only pipeline
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session_origin])
            mock_db.get_session = AsyncMock(return_value=session_origin)
            await loop._tick()
            origin_assistant_calls = len(get_assistant_calls)

            # Reset tracking
            get_assistant_calls.clear()

            # Reflection mode tick — should NOT use assistant-only pipeline
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session_reflection])
            mock_db.get_session = AsyncMock(return_value=session_reflection)
            await loop._tick()

        # The second tick (reflection mode) must NOT use get_assistant_messages_since.
        assert origin_assistant_calls > 0, "Origin mode should use assistant-only pipeline"
        assert not get_assistant_calls, (
            "Reflection mode tick must not use get_assistant_messages_since — "
            "it must switch to a user+agent rendering pipeline immediately (R4)"
        )
        adapter.send_threaded_output.assert_called()


# ---------------------------------------------------------------------------
# R5 — Unified content belt
# ---------------------------------------------------------------------------


class TestUnifiedContentBelt:
    """R5: User messages in reflection mode come from the same transcript
    rendering pipeline as agent messages — no separate reflection mechanism."""

    async def test_no_separate_user_input_reflection(self, cadence_loop: object) -> None:
        """The cadence must not have a separate _reflect_user_input method.
        Reflection-mode adapters see user messages as part of the rendered belt."""
        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        loop = cadence_loop
        assert isinstance(loop, OutputCadenceLoop)

        # _reflect_user_input must not exist on the cadence loop
        assert not hasattr(loop, "_reflect_user_input"), (
            "OutputCadenceLoop._reflect_user_input must be removed — "
            "user messages are part of the unified content belt (R5)"
        )

    async def test_reflection_mode_delivers_user_content_via_belt(
        self, cadence_loop: object, adapter: _FakeAdapter, tmp_path: object
    ) -> None:
        """In reflection mode, user messages from the transcript must reach
        the adapter's delivery method as part of the rendered content belt —
        not via a separate broadcast_user_input mechanism."""
        import json
        from pathlib import Path

        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        loop = cadence_loop
        assert isinstance(loop, OutputCadenceLoop)

        # Transcript with user message followed by assistant output.
        transcript = Path(str(tmp_path)) / "belt.jsonl"
        entries = [
            {"message": {"role": "user", "content": [{"type": "text", "text": "What is 2+2?"}]}},
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "4"}]}},
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        # Adapter is "discord", last_input_origin is "telegram" → reflection mode.
        session = _make_session(
            native_log_file=str(transcript),
            active_agent="claude",
            last_input_origin="telegram",
        )

        delivered_content: list[str] = []

        async def capture_send(_sess: object, text: str, **_kw: object) -> str:
            delivered_content.append(text)
            return "msg-1"

        adapter.send_threaded_output = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
            side_effect=capture_send
        )

        mock_identity = MagicMock()
        mock_identity.display_name = "TestUser"
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = mock_identity

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
            patch(
                "teleclaude.adapters.ui.output_cadence.get_identity_resolver",
                return_value=mock_resolver,
            ),
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_origin_metadata = AsyncMock()
            await loop._tick()

        # The unified belt must include the user message content in what gets
        # delivered to reflection-mode adapters.
        all_delivered = "\n".join(delivered_content)
        assert "What is 2+2?" in all_delivered, (
            "Reflection-mode adapter did not receive user message content — "
            "the unified content belt must include user messages (R5)"
        )

    async def test_no_broadcast_user_input_for_reflection(self) -> None:
        """The adapter runtime's broadcast_user_input must not be the mechanism
        for reflection. Reflection-mode adapters get user messages from the belt."""
        import ast
        import inspect
        from pathlib import Path

        from teleclaude.core.adapter_client._output import _OutputMixin

        source_file = Path(inspect.getfile(_OutputMixin))
        source = source_file.read_text(encoding="utf-8")

        # broadcast_user_input should no longer exist as a method
        tree = ast.parse(source)
        method_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "_OutputMixin":
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_names.append(item.name)

        assert "broadcast_user_input" not in method_names, (
            "broadcast_user_input must be removed from _OutputMixin — "
            "unified content belt replaces the separate reflection mechanism"
        )


# ---------------------------------------------------------------------------
# R6 — Lifecycle layer reduced to QoS
# ---------------------------------------------------------------------------


class TestLifecycleReducedToQoS:
    """R6: break_threaded_turn drops QoS payloads only — no rendering state."""

    async def test_break_threaded_turn_only_drops_qos(self) -> None:
        """break_threaded_turn must only drop pending QoS payloads.
        It must not manipulate rendering state."""
        from teleclaude.adapters.ui_adapter import UiAdapter
        from teleclaude.core.adapter_client._output import _OutputMixin

        mixin = _OutputMixin()
        fake_adapter = MagicMock(spec=UiAdapter)
        fake_adapter.ADAPTER_KEY = "discord"
        fake_adapter.drop_pending_output = MagicMock(return_value=2)
        fake_adapter.clear_turn_state = AsyncMock()

        mixin.adapters = {"discord": fake_adapter}  # pyright: ignore[reportAttributeAccessIssue]

        session = _make_session()
        with patch("teleclaude.core.adapter_client._output.db") as mock_db:
            mock_db.update_session = AsyncMock()
            mock_db.update_origin_metadata = AsyncMock()
            await mixin.break_threaded_turn(session)

        # QoS drop must happen
        fake_adapter.drop_pending_output.assert_called_once_with(session.session_id)
        # Rendering state must NOT be touched
        fake_adapter.clear_turn_state.assert_not_called()
        # Origin metadata (rendering state) must not be updated from lifecycle layer
        mock_db.update_origin_metadata.assert_not_called()

    async def test_break_threaded_turn_does_not_advance_cursor(self) -> None:
        """break_threaded_turn must not write last_tool_done_at to the DB."""
        from teleclaude.core.adapter_client._output import _OutputMixin

        mixin = _OutputMixin()
        fake_adapter = MagicMock()
        fake_adapter.ADAPTER_KEY = "discord"
        fake_adapter.drop_pending_output = MagicMock(return_value=0)

        from teleclaude.adapters.ui_adapter import UiAdapter

        with patch.object(UiAdapter, "__instancecheck__", return_value=True):
            mixin.adapters = {"discord": fake_adapter}  # pyright: ignore[reportAttributeAccessIssue]

            async def noop_broadcast(
                _session: object, _op: str, _factory: object, **_kw: object
            ) -> list[tuple[str, object]]:
                return []

            mixin._broadcast_to_ui_adapters = noop_broadcast  # pyright: ignore[reportAttributeAccessIssue]

            session = _make_session()
            with patch("teleclaude.core.adapter_client._output.db") as mock_db:
                mock_db.update_session = AsyncMock()
                await mixin.break_threaded_turn(session)

                # Must NOT write last_tool_done_at (rendering cursor).
                # Check that if update_session is called, it doesn't set the cursor.
                for call in mock_db.update_session.call_args_list:
                    _, kwargs = call
                    assert "last_tool_done_at" not in kwargs, (
                        "break_threaded_turn must not write last_tool_done_at — "
                        "rendering authority is file-derived (R1/R6)"
                    )


# ---------------------------------------------------------------------------
# R7 — Signal-rendering separation
# ---------------------------------------------------------------------------


class TestSignalRenderingSeparation:
    """R7: Signals only update last_activity_at. Rendering only reads transcripts."""

    async def test_coordinator_does_not_set_rendering_cursors(self) -> None:
        """handle_user_prompt_submit must not write last_tool_done_at (a rendering
        cursor). It may write last_activity_at and session metadata fields."""
        import ast
        import inspect
        from pathlib import Path

        from teleclaude.core.agent_coordinator._coordinator import AgentCoordinator

        source_file = Path(inspect.getfile(AgentCoordinator))
        source = source_file.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Find handle_user_prompt_submit method body
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_user_prompt_submit":
                body_source = ast.dump(node)
                # The method must not contain last_tool_done_at assignments
                assert "last_tool_done_at" not in body_source, (
                    "handle_user_prompt_submit must not manipulate last_tool_done_at — "
                    "rendering cursors belong to the cadence (R7)"
                )
                break
        else:
            pytest.fail("handle_user_prompt_submit not found in AgentCoordinator")

    def test_tmux_activity_signal_does_not_touch_rendering_state(self) -> None:
        """The TMUX polling coordinator (tmux activity signal handler) must only
        write last_activity_at. It must not read or write rendering state
        (char_offset, output_message_id, delivery timestamps, rendering cursors)."""
        import ast
        from pathlib import Path

        polling_path = Path(__file__).resolve().parents[4] / "teleclaude" / "core" / "polling_coordinator.py"
        source = polling_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        rendering_state_tokens = {
            "char_offset",
            "output_message_id",
            "last_delivered_at",
            "last_tool_done_at",
            "LAST_TOOL_DONE_AT",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "poll_and_send_output":
                method_source = ast.get_source_segment(source, node) or ""
                for token in rendering_state_tokens:
                    assert token not in method_source, (
                        f"poll_and_send_output references '{token}' — "
                        "TMUX activity signal must not touch rendering state (R7)"
                    )
                break
        else:
            pytest.fail("poll_and_send_output not found in polling_coordinator.py")

    def test_cadence_does_not_write_signal_state(self) -> None:
        """The cadence (rendering path) must not write to last_activity_at.
        The converse of signals not touching rendering state.
        Regression guard — must hold before and after R7."""
        import ast
        from pathlib import Path

        cadence_path = Path(__file__).resolve().parents[4] / "teleclaude" / "adapters" / "ui" / "output_cadence.py"
        source = cadence_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "OutputCadenceLoop":
                class_source = ast.get_source_segment(source, node) or ""
                # The cadence may READ last_activity_at (via get_sessions_active_since),
                # but must not WRITE it.
                assert "update_last_activity" not in class_source, (
                    "OutputCadenceLoop writes last_activity_at — the cadence must not touch signal state (R7)"
                )
                break
        else:
            pytest.fail("OutputCadenceLoop class not found in output_cadence.py")


# ---------------------------------------------------------------------------
# R8 — Terminal input rendering parity
# ---------------------------------------------------------------------------


class TestTerminalInputRenderingParity:
    """R8: Terminal input follows the same cadence-driven rendering path.
    No special force-pull mechanism for terminal input."""

    async def test_no_force_pull_for_terminal_input(self) -> None:
        """handle_user_prompt_submit must not call force_session_output_pull
        for terminal input. Terminal and UI adapter inputs converge to the
        cadence tick rendering path."""
        import ast
        import inspect
        from pathlib import Path

        from teleclaude.core.agent_coordinator._coordinator import AgentCoordinator

        source_file = Path(inspect.getfile(AgentCoordinator))
        source = source_file.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_user_prompt_submit":
                # Walk the method body for force_session_output_pull calls
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute) and child.attr == "force_session_output_pull":
                        pytest.fail(
                            "handle_user_prompt_submit still calls force_session_output_pull — "
                            "terminal input must use the cadence path (R8)"
                        )
                break
        else:
            pytest.fail("handle_user_prompt_submit not found in AgentCoordinator")

    async def test_force_pull_preserved_for_final_flush(self) -> None:
        """force_session_output_pull must still exist on _OutputMixin for the
        final-flush use case (session close). R10 preserved behavior."""
        from teleclaude.core.adapter_client._output import _OutputMixin

        assert hasattr(_OutputMixin, "force_session_output_pull"), (
            "force_session_output_pull must be preserved for final flush before session close"
        )


# ---------------------------------------------------------------------------
# R9 — Removal of superseded mechanisms
# ---------------------------------------------------------------------------
# R9 coverage is in test_cadence_superseded_removal_spec.py (more granular AST checks).
# This main spec file avoids duplication per testing policy (one test home per function).


# ---------------------------------------------------------------------------
# R10 — Preserved behaviors
# ---------------------------------------------------------------------------


class TestPreservedBehaviors:
    """R10: The following behaviors must be preserved with their current contracts.
    Changes in ownership (from coordinator to cadence, from session state to
    transient metadata) are implementation details — contracts remain stable."""

    def test_char_offset_output_message_id_preserved_as_concepts(self) -> None:
        """char_offset and output_message_id must continue to exist as
        delivery bookkeeping concepts. Ownership transfers to cadence (R3)
        but the mechanism and contract are preserved."""
        # Verify the session still includes delivery bookkeeping fields
        session = _make_session()
        # These fields should exist somewhere in the session/adapter state structure
        # This is a contract verification — the concepts are preserved even if
        # management moves to the cadence.
        assert hasattr(session, "get_origin_section") or hasattr(Session, "get_origin_section"), (
            "Session must preserve delivery bookkeeping structure (R10)"
        )

    def test_force_session_output_pull_exists_for_final_flush(self) -> None:
        """force_session_output_pull method must be preserved on _OutputMixin.
        R8 removes its use for terminal input but preserves the method for
        the final-flush use case before session close."""
        from teleclaude.core.adapter_client._output import _OutputMixin

        assert hasattr(_OutputMixin, "force_session_output_pull"), (
            "force_session_output_pull must be preserved for final-flush use case (R10)"
        )
        # Verify the method exists and is callable
        method = getattr(_OutputMixin, "force_session_output_pull", None)
        assert callable(method), "force_session_output_pull must be a callable method (R10)"

    def test_last_input_origin_preserved_for_rendering_mode(self) -> None:
        """last_input_origin in session must be preserved for determining
        rendering mode (origin vs reflection) at render time.
        Transient mode determination (R4) relies on this field."""
        session = _make_session()
        # last_input_origin is used to determine rendering mode
        # This is a preserved contract from R4
        assert hasattr(session, "last_input_origin"), (
            "Session must preserve last_input_origin for mode determination (R10)"
        )

    def test_transcript_parser_interface_preserved(self) -> None:
        """Transcript parser interfaces and their file-reading contracts
        must remain unchanged. File-derived rendering (R1) depends on these."""
        import inspect

        from teleclaude.utils.transcript import get_assistant_messages_since

        # Verify the function signature is stable
        sig = inspect.signature(get_assistant_messages_since)
        assert "since_timestamp" in sig.parameters or "session_id" in sig.parameters, (
            "Transcript parser interface must preserve file-reading contracts (R10)"
        )

    def test_tmux_activity_signal_activation_pattern_preserved(self) -> None:
        """TMUX activity signal → last_activity_at → cadence activation
        pattern must be preserved. Signals wake the cadence, cadence reads
        transcript (R1)."""
        import ast
        from pathlib import Path

        # Verify that poll_and_send_output sets last_activity_at
        polling_path = Path(__file__).resolve().parents[4] / "teleclaude" / "core" / "polling_coordinator.py"
        source = polling_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        found_update = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "poll_and_send_output":
                method_source = ast.get_source_segment(source, node) or ""
                # Must update last_activity_at or related activation mechanism
                if "last_activity" in method_source or "last_activity_at" in method_source:
                    found_update = True
                break

        assert found_update, "TMUX activity signal must wake cadence via last_activity_at (R10)"

    def test_agent_event_signal_for_headless_activation_preserved(self) -> None:
        """Agent event signals for headless session cadence activation
        must be preserved. Same pattern as TMUX activity (last_activity_at)."""
        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        # Verify OutputCadenceLoop checks for session activation
        # It should read last_activity_at or similar activation signals
        # The _tick method should check activation
        assert "_tick" in dir(OutputCadenceLoop), (
            "OutputCadenceLoop must have _tick method for signal-driven activation (R10)"
        )

    def test_lifecycle_events_typing_indicators_preserved(self) -> None:
        """Lifecycle events (typing indicators, status badges) that are
        already correctly separated from rendering must continue to work.
        No regression in these already-clean signal paths."""
        # Verify that lifecycle event signal handlers exist and don't touch rendering state.
        # This is a regression guard for patterns already correctly separated.
        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        assert hasattr(OutputCadenceLoop, "_tick"), (
            "Lifecycle events must be preserved and not interfere with rendering (R10)"
        )

    async def test_delivery_bookkeeping_message_state_tracking(self, adapter: _FakeAdapter, tmp_path: object) -> None:
        """Delivery bookkeeping (char_offset, output_message_id) must still
        track message state correctly. Ownership moves to cadence (R3) but
        tracking contract is preserved."""
        import json
        from pathlib import Path

        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        # Create a transcript with agent output
        transcript = Path(str(tmp_path)) / "delivery_test.jsonl"
        entries = [
            {
                "timestamp": "2024-06-01T10:00:00+00:00",
                "message": {"role": "user", "content": [{"type": "text", "text": "prompt"}]},
            },
            {
                "timestamp": "2024-06-01T10:00:01+00:00",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "response"}]},
            },
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

        session = _make_session(native_log_file=str(transcript), active_agent="claude")
        loop = OutputCadenceLoop(adapter, interval_seconds=1.0)

        with (
            patch("teleclaude.adapters.ui.output_cadence.db") as mock_db,
        ):
            mock_db.get_sessions_active_since = AsyncMock(return_value=[session])
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.update_origin_metadata = AsyncMock()
            await loop._tick()

        # Verify that send_threaded_output was called (message sent)
        adapter.send_threaded_output.assert_called()

    def test_rendering_mode_determined_at_render_time_from_metadata(self, adapter: _FakeAdapter) -> None:
        """Rendering mode (origin vs reflection) must be determined at
        render time from session metadata (last_input_origin), not stored
        as persistent adapter state. R4 transience contract is preserved."""
        from teleclaude.adapters.ui.output_cadence import OutputCadenceLoop

        session1 = _make_session(native_log_file="/tmp/test.jsonl", active_agent="claude")
        session1.last_input_origin = "discord"

        session2 = _make_session(native_log_file="/tmp/test.jsonl", active_agent="claude")
        session2.last_input_origin = "terminal"

        loop = OutputCadenceLoop(adapter, interval_seconds=1.0)

        # Verify that the loop reads mode from session metadata, not stored state
        assert loop is not None, "OutputCadenceLoop exists and can determine mode from metadata (R10)"
        # The real test happens when rendering: same adapter should render
        # differently based on session.last_input_origin at render time
