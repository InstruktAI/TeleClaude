"""Unit tests for polling_coordinator module."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core import polling_coordinator
from teleclaude.core.events import AgentHookEvents, AgentOutputPayload, UserPromptSubmitPayload
from teleclaude.core.models import Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.output_poller import OutputChanged, ProcessExited


@pytest.mark.asyncio
class TestPollAndSendOutput:
    """Test poll_and_send_output function."""

    async def test_duplicate_polling_prevention(self):
        """Test polling request ignored when already polling."""
        session_id = "test-123"
        await polling_coordinator._register_polling(session_id)
        try:
            # Should return False and not start polling
            result = await polling_coordinator.schedule_polling(
                session_id=session_id,
                tmux_session_name="tmux",
                output_poller=Mock(),
                adapter_client=Mock(),
                get_output_file=Mock(),
            )
            assert result is False
        finally:
            await polling_coordinator._unregister_polling(session_id)

    async def test_output_changed_event(self):
        """Test OutputChanged event handling."""
        # Mock session
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        # Mock poller to yield OutputChanged event
        async def mock_poll(session_id, tmux_session_name, output_file):
            yield OutputChanged(
                session_id="test-123",
                output="test output",
                started_at=1000.0,
                last_changed_at=1001.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        adapter_client = Mock()
        adapter_client.send_output_update = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        with (
            patch("teleclaude.core.polling_coordinator.db.get_session", new_callable=AsyncMock) as mock_get,
        ):
            mock_get.return_value = mock_session
            await polling_coordinator.poll_and_send_output(
                session_id="test-123",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
                _skip_register=True,
            )

        # Verify send_output_update was called
        assert adapter_client.send_output_update.called
        args, _ = adapter_client.send_output_update.call_args
        assert args[1] == "test output"

    async def test_output_changed_codex_detection_does_not_spawn_wrapper_task(self):
        """Codex detection should run inline without per-update wrapper tasks."""
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            active_agent="gemini",
        )

        async def mock_poll(session_id, tmux_session_name, output_file):
            yield OutputChanged(
                session_id="test-123",
                output="test output",
                started_at=1000.0,
                last_changed_at=1001.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        adapter_client = Mock()
        adapter_client.send_output_update = AsyncMock()
        adapter_client.agent_event_handler = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        with (
            patch("teleclaude.core.polling_coordinator.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.polling_coordinator._maybe_emit_codex_input",
                new_callable=AsyncMock,
            ) as mock_maybe_emit,
            patch("teleclaude.core.polling_coordinator.asyncio.create_task") as mock_create_task,
        ):
            mock_get.return_value = mock_session
            await polling_coordinator.poll_and_send_output(
                session_id="test-123",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
                _skip_register=True,
            )

        mock_maybe_emit.assert_awaited_once()
        mock_create_task.assert_not_called()

    async def test_process_exited_with_exit_code(self):
        """Test ProcessExited event with exit code."""
        # Mock session
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        async def mock_poll(session_id, tmux_session_name, output_file):
            yield ProcessExited(
                session_id="test-123",
                final_output="command output",
                exit_code=0,
                started_at=1000.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        adapter_client = Mock()
        adapter_client.send_output_update = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        with (
            patch("teleclaude.core.polling_coordinator.db.get_session", new_callable=AsyncMock) as mock_get,
            patch("teleclaude.core.tmux_bridge.session_exists", new_callable=AsyncMock, return_value=True),
        ):
            mock_get.return_value = mock_session
            await polling_coordinator.poll_and_send_output(
                session_id="test-123",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
                _skip_register=True,
            )

        # Verify final update sent
        assert adapter_client.send_output_update.called
        args, kwargs = adapter_client.send_output_update.call_args
        assert kwargs["is_final"] is True
        assert kwargs["exit_code"] == 0

    async def test_process_exited_without_exit_code(self, tmp_path):
        """Test ProcessExited event without exit code (session died)."""
        # Mock session with human-readable title
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        # Create real temp file
        output_file = tmp_path / "output.txt"
        output_file.write_text("test output")

        # Mock poller to yield ProcessExited event without exit code
        async def mock_poll(session_id, tmux_session_name, output_file):
            yield ProcessExited(
                session_id="test-123",
                final_output="partial output",
                exit_code=None,
                started_at=1000.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        adapter_client = Mock()
        adapter_client.send_output_update = AsyncMock()

        get_output_file = Mock(return_value=output_file)

        with (
            patch("teleclaude.core.polling_coordinator.db.get_session", new_callable=AsyncMock) as mock_get,
            patch("teleclaude.core.session_cleanup.terminate_session", new_callable=AsyncMock) as mock_terminate,
        ):
            mock_get.return_value = mock_session
            await polling_coordinator.poll_and_send_output(
                session_id="test-123",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
                _skip_register=True,
            )

        mock_terminate.assert_not_called()

    async def test_process_exited_with_exit_code_and_missing_tmux(self, tmp_path):
        """Exit code with missing tmux should terminate the session."""
        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        output_file = tmp_path / "output.txt"
        output_file.write_text("test output")

        async def mock_poll(session_id, tmux_session_name, output_file):
            yield ProcessExited(
                session_id="test-123",
                final_output="command output",
                exit_code=0,
                started_at=1000.0,
            )

        output_poller = Mock()
        output_poller.poll = mock_poll

        adapter_client = Mock()
        adapter_client.send_output_update = AsyncMock()

        get_output_file = Mock(return_value=output_file)

        with (
            patch("teleclaude.core.polling_coordinator.db.get_session", new_callable=AsyncMock) as mock_get,
            patch(
                "teleclaude.core.tmux_bridge.session_exists", new_callable=AsyncMock, return_value=False
            ) as mock_exists,
            patch("teleclaude.core.session_cleanup.terminate_session", new_callable=AsyncMock) as mock_terminate,
        ):
            mock_get.return_value = mock_session
            await polling_coordinator.poll_and_send_output(
                session_id="test-123",
                tmux_session_name="test-tmux",
                output_poller=output_poller,
                adapter_client=adapter_client,
                get_output_file=get_output_file,
                _skip_register=True,
            )

        assert mock_exists.call_args == (("test-tmux",), {"log_missing": False})
        assert mock_terminate.call_args is not None
        _, kwargs = mock_terminate.call_args
        assert kwargs["kill_tmux"] is False

    async def test_cleanup_in_finally_block(self):
        """Test cleanup always happens in finally block."""
        session_id = "test-123"
        mock_session = Session(
            session_id=session_id,
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
        )

        # Mock poller to raise exception
        async def mock_poll(session_id, tmux_session_name, output_file):
            raise RuntimeError("Polling error")
            yield  # Never reached

        output_poller = Mock()
        output_poller.poll = mock_poll

        adapter_client = Mock()
        adapter_client.send_error_feedback = AsyncMock()

        get_output_file = Mock(return_value=Path("/tmp/output.txt"))

        with (
            patch("teleclaude.core.polling_coordinator.db.get_session", new_callable=AsyncMock) as mock_get,
            patch("teleclaude.core.polling_coordinator._unregister_polling", new_callable=AsyncMock) as mock_unreg,
        ):
            mock_get.return_value = mock_session
            with pytest.raises(RuntimeError, match="Polling error"):
                await polling_coordinator.poll_and_send_output(
                    session_id=session_id,
                    tmux_session_name="test-tmux",
                    output_poller=output_poller,
                    adapter_client=adapter_client,
                    get_output_file=get_output_file,
                    _skip_register=True,
                )

        # Verify cleanup was called even on error
        assert mock_unreg.called
        assert mock_unreg.call_args == ((session_id,),)
        # Verify error feedback sent
        assert adapter_client.send_error_feedback.called


@pytest.mark.asyncio
class TestCodexSyntheticPromptDetection:
    async def test_marker_visible_during_typing_emits_only_after_prompt_clears(self):
        """Stale marker above prompt while typing must not emit partial prompts."""
        session_id = "codex-partial-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            # First keystroke appears while stale marker is visible above prompt.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="• Working...\n› c",
                output_changed=True,
                emit_agent_event=emit,
            )
            emit.assert_not_awaited()

            # User continues typing multiline prompt.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="• Working...\n› commit all\nasdsd",
                output_changed=True,
                emit_agent_event=emit,
            )
            emit.assert_not_awaited()

            # Submit boundary marker appears below prompt block -> emit full buffered prompt.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="› commit all\nasdsd\n• Working...",
                output_changed=True,
                emit_agent_event=emit,
            )

            emit.assert_awaited_once()
            context = emit.await_args.args[0]
            payload = context.data
            assert isinstance(payload, UserPromptSubmitPayload)
            assert payload.prompt == "commit all\nasdsd"
            assert payload.raw.get("source") == "codex_output_polling"
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_stale_bullet_below_prompt_does_not_trigger_submit_boundary(self):
        """Assistant bullet text below prompt must not count as submit boundary."""
        session_id = "codex-stale-bullet-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            # Stale assistant bullet appears below prompt; should not emit partial prompt.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="› say hi\n• I am applying the change now",
                output_changed=True,
                emit_agent_event=emit,
            )
            emit.assert_not_awaited()

            # Live status marker below prompt is the real submit boundary.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="› say hi\n• Working...",
                output_changed=True,
                emit_agent_event=emit,
            )
            emit.assert_awaited_once()
            context = emit.await_args.args[0]
            payload = context.data
            assert isinstance(payload, UserPromptSubmitPayload)
            assert payload.prompt == "say hi"
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_emits_on_prompt_to_agent_transition_without_overlap_frame(self):
        """Emit submit when prompt disappears and first visible agent line is a tool action."""
        session_id = "codex-transition-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            # Prompt visible while user is composing - no submit yet.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="› say hi",
                output_changed=True,
                emit_agent_event=emit,
            )
            emit.assert_not_awaited()

            # Next frame: prompt gone, response starts with a tool-action line.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="• Ran rg -n foo",
                output_changed=True,
                emit_agent_event=emit,
            )

            emit.assert_awaited_once()
            context = emit.await_args.args[0]
            payload = context.data
            assert isinstance(payload, UserPromptSubmitPayload)
            assert payload.prompt == "say hi"
            assert payload.raw.get("source") == "codex_marker_transition"
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_emits_when_prompt_visibility_helper_misses_prompt_frame(self):
        """Submit must still emit if prompt text is captured while prompt-visible helper returns false."""
        session_id = "codex-transition-gap-2"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            with patch(
                "teleclaude.core.polling_coordinator._has_live_prompt_marker",
                side_effect=[False, False],
            ):
                await polling_coordinator._maybe_emit_codex_input(
                    session_id=session_id,
                    active_agent="codex",
                    current_output="› hidden-prompt case",
                    output_changed=True,
                    emit_agent_event=emit,
                )
                emit.assert_not_awaited()

                await polling_coordinator._maybe_emit_codex_input(
                    session_id=session_id,
                    active_agent="codex",
                    current_output="• Working...",
                    output_changed=True,
                    emit_agent_event=emit,
                )

            emit.assert_awaited_once()
            context = emit.await_args.args[0]
            payload = context.data
            assert isinstance(payload, UserPromptSubmitPayload)
            assert payload.prompt == "hidden-prompt case"
            assert payload.raw.get("source") == "codex_marker_transition"
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_keeps_buffered_prompt_across_empty_prompt_frame_before_emit(self):
        """Do not drop buffered prompt when an empty `› ` frame appears before agent response."""
        session_id = "codex-empty-prompt-gap-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="› keep me",
                output_changed=True,
                emit_agent_event=emit,
            )
            emit.assert_not_awaited()

            # Transitional empty prompt frame (previously cleared buffered prompt).
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="› ",
                output_changed=True,
                emit_agent_event=emit,
            )
            emit.assert_not_awaited()

            # First agent-active frame should emit buffered prompt.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="• Working...",
                output_changed=True,
                emit_agent_event=emit,
            )

            emit.assert_awaited_once()
            context = emit.await_args.args[0]
            payload = context.data
            assert isinstance(payload, UserPromptSubmitPayload)
            assert payload.prompt == "keep me"
            assert payload.raw.get("source") == "codex_marker_transition"
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_transition_emit_when_prompt_visible_and_agent_already_active(self):
        """Emit submit even when prompt-visible helper is true on the transition frame."""
        session_id = "codex-transition-visible-prompt-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="› go",
                output_changed=True,
                emit_agent_event=emit,
            )
            emit.assert_not_awaited()

            # Agent marker visible while prompt line still visible below it.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="• Working...\n› ",
                output_changed=True,
                emit_agent_event=emit,
            )

            emit.assert_awaited_once()
            context = emit.await_args.args[0]
            payload = context.data
            assert isinstance(payload, UserPromptSubmitPayload)
            assert payload.prompt == "go"
            assert payload.raw.get("source") == "codex_marker_transition"
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_does_not_emit_while_prompt_text_is_still_visible(self):
        """Stale marker glyphs above prompt should not trigger synthetic submit."""
        session_id = "codex-visible-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)
        polling_coordinator._codex_input_state[session_id] = polling_coordinator.CodexInputState(
            last_prompt_input="hello world",
            last_output_change_time=0.0,
        )

        try:
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="• Working...\n› hello world",
                output_changed=True,
                emit_agent_event=emit,
            )
            emit.assert_not_awaited()
            state = polling_coordinator._codex_input_state[session_id]
            assert state.last_prompt_input == "hello world"
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_does_not_emit_when_prompt_clears_without_marker(self):
        """Prompt-clear alone must not emit; submit requires explicit marker boundary."""
        session_id = "codex-cleared-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)
        polling_coordinator._codex_input_state[session_id] = polling_coordinator.CodexInputState(
            last_prompt_input="please continue",
            last_output_change_time=0.0,
        )

        try:
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="some changed pane output",
                output_changed=True,
                emit_agent_event=emit,
            )

            emit.assert_not_awaited()
            state = polling_coordinator._codex_input_state[session_id]
            assert state.last_prompt_input == "please continue"
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_find_prompt_input_ignores_stale_scrollback_prompt(self):
        """Older prompt lines in scrollback must not be treated as current user input."""
        stale_output = "\n".join(
            [
                "header",
                "› old input that should not be reused",
                "line a",
                "line b",
                "line c",
                "line d",
            ]
        )
        assert polling_coordinator._find_prompt_input(stale_output) == ""

    async def test_duplicate_prompt_not_re_emitted(self):
        """Same synthetic prompt should not be emitted repeatedly."""
        session_id = "codex-dup-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)
        polling_coordinator._codex_input_state[session_id] = polling_coordinator.CodexInputState(
            last_prompt_input="repeat me",
            last_emitted_prompt="repeat me",
            last_output_change_time=0.0,
        )

        try:
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="some changed pane output",
                output_changed=True,
                emit_agent_event=emit,
            )
            emit.assert_not_awaited()
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_same_prompt_can_emit_again_on_new_turn(self):
        """Identical prompt text should emit once per turn, not once per session."""
        session_id = "codex-repeat-turn-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            # Turn 1 submit.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="› say hi\n• Working...",
                output_changed=True,
                emit_agent_event=emit,
            )
            assert emit.await_count == 1

            # Same boundary frame should not re-emit during the same response phase.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="› say hi\n• Working...",
                output_changed=True,
                emit_agent_event=emit,
            )
            assert emit.await_count == 1

            # Response ended; prompt visible again starts a new turn.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="assistant done\n› say hi",
                output_changed=True,
                emit_agent_event=emit,
            )
            assert emit.await_count == 1

            # Turn 2 submit with identical prompt should emit again.
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="› say hi\n• Working...",
                output_changed=True,
                emit_agent_event=emit,
            )
            assert emit.await_count == 2
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_has_live_prompt_marker_with_footer_hint(self):
        output = "final text\n› Write tests for @filename\n\n? for shortcuts"
        assert polling_coordinator._has_live_prompt_marker(output) is True


@pytest.mark.asyncio
class TestCodexSyntheticTurnEvents:
    async def test_emits_tool_use_from_visible_bold_action_line(self):
        session_id = "codex-turn-tool-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            output = "\x1b[2m• \x1b[0m\x1b[1mRan\x1b[0m rg -n foo"
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=output,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )
            emit.assert_awaited_once()
            context = emit.await_args.args[0]
            assert context.event_type == AgentHookEvents.TOOL_USE
            assert isinstance(context.data, AgentOutputPayload)
            assert context.data.raw.get("synthetic") is True
            assert context.data.raw.get("tool_name") == "Ran"
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_emits_tool_use_when_action_line_is_not_in_short_tail(self):
        session_id = "codex-turn-tool-lookback-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            filler = "\n".join(f"line {i}" for i in range(30))
            output = f"\x1b[2m• \x1b[0m\x1b[1mRan\x1b[0m rg -n foo\n{filler}"
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=output,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )
            emit.assert_awaited_once()
            context = emit.await_args.args[0]
            assert context.event_type == AgentHookEvents.TOOL_USE
            assert context.data.raw.get("tool_name") == "Ran"
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_emits_tool_done_when_prompt_returns(self):
        session_id = "codex-turn-stop-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            active_output = "\x1b[2m• \x1b[0m\x1b[1mExplored\x1b[0m\n\x1b[2m│\x1b[0m details"
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=active_output,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )

            stop_output = "final assistant text\n\n› "
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=stop_output,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )

            event_types = [call.args[0].event_type for call in emit.await_args_list]
            assert event_types == [AgentHookEvents.TOOL_USE, AgentHookEvents.TOOL_DONE]
            assert isinstance(emit.await_args_list[-1].args[0].data, AgentOutputPayload)
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_prompt_visible_ignores_stale_tool_action_lines(self):
        session_id = "codex-turn-stale-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            active_output = "\x1b[2m• \x1b[0m\x1b[1mRan\x1b[0m rg -n foo"
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=active_output,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )

            # Prompt is back, but stale action line still visible in recent output.
            stop_output_with_stale_action = "assistant summary\n\x1b[2m• \x1b[0m\x1b[1mRan\x1b[0m rg -n foo\n› "
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=stop_output_with_stale_action,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )

            event_types = [call.args[0].event_type for call in emit.await_args_list]
            assert event_types == [AgentHookEvents.TOOL_USE, AgentHookEvents.TOOL_DONE]
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_prompt_visible_emits_tool_use_once_for_new_action_signature(self):
        session_id = "codex-turn-signature-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            # First prompt-visible frame establishes stale baseline, no emit.
            baseline = "older text\n\x1b[2m• \x1b[0m\x1b[1mRan\x1b[0m rg -n old\n› "
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=baseline,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )
            emit.assert_not_awaited()

            # New action signature while prompt is still visible should emit once.
            updated = "older text\n\x1b[2m• \x1b[0m\x1b[1mRan\x1b[0m rg -n new\n› "
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=updated,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )
            assert emit.await_count == 2
            event_types = [call.args[0].event_type for call in emit.await_args_list]
            assert event_types == [AgentHookEvents.TOOL_USE, AgentHookEvents.TOOL_DONE]

            # Same signature should not emit again.
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=updated,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )
            assert emit.await_count == 2
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_skips_when_synthetic_turn_events_disabled(self):
        session_id = "codex-turn-disabled-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            output = "\x1b[2m• \x1b[0m\x1b[1mRead\x1b[0m teleclaude/core/polling_coordinator.py"
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=output,
                emit_agent_event=emit,
                enable_synthetic_turn_events=False,
            )
            emit.assert_not_awaited()
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_prompt_return_without_tool_emits_no_synthetic_stop(self):
        session_id = "codex-turn-text-only-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)
        polling_coordinator._codex_turn_state[session_id] = polling_coordinator.CodexTurnState(
            turn_active=True,
            in_tool=False,
        )

        try:
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output="assistant response text\n› ",
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )
            emit.assert_not_awaited()
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_prompt_footer_hint_emits_no_synthetic_stop(self):
        session_id = "codex-turn-footer-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)
        polling_coordinator._codex_turn_state[session_id] = polling_coordinator.CodexTurnState(
            turn_active=True,
            in_tool=False,
        )

        try:
            output = "assistant text\n› Write tests for @filename\n? for shortcuts"
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=output,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )
            emit.assert_not_awaited()
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)

    async def test_prompt_transition_without_tool_emits_no_synthetic_stop(self):
        session_id = "codex-turn-transition-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            # Prompt not visible: stale action line marks active response context.
            active_output = "\x1b[2m• \x1b[0m\x1b[1mExplored\x1b[0m files"
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=active_output,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )

            # Simulate lost turn state after daemon reconnect/restart.
            polling_coordinator._codex_turn_state[session_id] = polling_coordinator.CodexTurnState(
                turn_active=False,
                in_tool=False,
                prompt_visible_last=False,
            )

            # Prompt transition should not emit synthetic stop.
            stop_output = (
                "assistant text\n"
                "\x1b[2m• \x1b[0m\x1b[1mExplored\x1b[0m files\n"
                "› Write tests for @filename\n"
                "? for shortcuts"
            )
            await polling_coordinator._maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output=stop_output,
                emit_agent_event=emit,
                enable_synthetic_turn_events=True,
            )

            event_types = [call.args[0].event_type for call in emit.await_args_list]
            assert event_types == [AgentHookEvents.TOOL_USE]
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)


@pytest.mark.asyncio
class TestCodexTurnActivationFromPromptSubmit:
    async def test_prompt_submit_marks_turn_active(self):
        session_id = "codex-submit-turn-1"
        emit = AsyncMock()
        polling_coordinator._cleanup_codex_input_state(session_id)

        try:
            await polling_coordinator._maybe_emit_codex_input(
                session_id=session_id,
                active_agent="codex",
                current_output="› explain this bug\n• Working...",
                output_changed=True,
                emit_agent_event=emit,
            )

            state = polling_coordinator._codex_turn_state.get(session_id)
            assert state is not None
            assert state.turn_active is True
        finally:
            polling_coordinator._cleanup_codex_input_state(session_id)
