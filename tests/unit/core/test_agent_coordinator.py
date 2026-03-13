"""Unit tests for echo suppression in teleclaude.core.agent_coordinator.

Tests the turn_triggered_by_linked_output flag that separates queue-drain state
(deliver_inbound) from agent-processing state (user_prompt_submit) for accurate
echo suppression in handle_agent_stop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.constants import TELECLAUDE_SYSTEM_PREFIX
from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.events import AgentEventContext, AgentStopPayload, UserPromptSubmitPayload
from teleclaude.core.models import Session
from teleclaude.core.origins import InputOrigin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LINKED_PREFIX = f"{TELECLAUDE_SYSTEM_PREFIX} Linked output from "


def _make_session(
    *,
    session_id: str = "sess-001",
    turn_triggered_by_linked_output: bool = False,
    last_message_sent: str | None = None,
    last_input_origin: str = InputOrigin.TERMINAL.value,
    lifecycle_status: str = "active",
    active_agent: str = "claude",
) -> Session:
    """Build a real core Session with the fields echo suppression reads."""
    return Session(
        session_id=session_id,
        computer_name="test-computer",
        tmux_session_name=f"teleclaude-{session_id}",
        title="Test",
        turn_triggered_by_linked_output=turn_triggered_by_linked_output,
        last_message_sent=last_message_sent,
        last_message_sent_at=datetime.now(UTC),
        last_input_origin=last_input_origin,
        lifecycle_status=lifecycle_status,
        active_agent=active_agent,
    )


def _make_coordinator() -> AgentCoordinator:
    """Build a real AgentCoordinator with mocked dependencies."""
    client = MagicMock()
    client.break_threaded_turn = AsyncMock()
    client.broadcast_user_input = AsyncMock()
    tts = MagicMock()
    tts.speak = AsyncMock()
    headless = MagicMock()
    coord = AgentCoordinator(client, tts, headless)
    return coord


def _make_prompt_context(session_id: str, prompt_text: str) -> AgentEventContext:
    """Build an AgentEventContext carrying a UserPromptSubmitPayload."""
    payload = UserPromptSubmitPayload(prompt=prompt_text, raw={"prompt": prompt_text})
    return AgentEventContext(session_id=session_id, data=cast(object, payload), event_type="user_prompt_submit")


def _make_stop_context(session_id: str) -> AgentEventContext:
    """Build an AgentEventContext carrying an AgentStopPayload."""
    payload = AgentStopPayload(raw={})
    return AgentEventContext(session_id=session_id, data=cast(object, payload), event_type="agent_stop")


# ---------------------------------------------------------------------------
# handle_user_prompt_submit: flag set correctly in DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_submit_sets_flag_true_for_linked_output():
    """handle_user_prompt_submit must persist turn_triggered_by_linked_output=True
    when the prompt is a linked output message."""
    session = _make_session()
    linked_text = f"{LINKED_PREFIX}reviewer (sess-002):\nHere is my review."

    db_mock = MagicMock()
    db_mock.get_session = AsyncMock(return_value=session)
    db_mock.update_session = AsyncMock()
    db_mock.set_notification_flag = AsyncMock()

    coord = _make_coordinator()
    context = _make_prompt_context("sess-001", linked_text)

    with patch("teleclaude.core.agent_coordinator._coordinator.db", db_mock):
        await coord.handle_user_prompt_submit(context)

    # Find the update_session call that sets the flag
    calls = db_mock.update_session.call_args_list
    flag_values = [
        c.kwargs.get("turn_triggered_by_linked_output") for c in calls if "turn_triggered_by_linked_output" in c.kwargs
    ]
    assert True in flag_values, f"Expected True in flag values, got: {flag_values}"


@pytest.mark.asyncio
async def test_prompt_submit_sets_flag_false_for_direct_message():
    """handle_user_prompt_submit must persist turn_triggered_by_linked_output=False
    when the prompt is a direct conversation (not linked output)."""
    session = _make_session(
        last_message_sent=f"{LINKED_PREFIX}someone:\npoisoned by deliver_inbound",
        last_input_origin=InputOrigin.REDIS.value,
    )
    direct_text = "Please fix the import error in module X."

    db_mock = MagicMock()
    db_mock.get_session = AsyncMock(return_value=session)
    db_mock.update_session = AsyncMock()
    db_mock.set_notification_flag = AsyncMock()

    coord = _make_coordinator()
    context = _make_prompt_context("sess-001", direct_text)

    with patch("teleclaude.core.agent_coordinator._coordinator.db", db_mock):
        await coord.handle_user_prompt_submit(context)

    calls = db_mock.update_session.call_args_list
    flag_values = [
        c.kwargs.get("turn_triggered_by_linked_output") for c in calls if "turn_triggered_by_linked_output" in c.kwargs
    ]
    assert False in flag_values, f"Expected False in flag values, got: {flag_values}"


# ---------------------------------------------------------------------------
# handle_agent_stop: echo suppression uses the flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_fanout_proceeds_when_flag_false():
    """handle_agent_stop must call _fanout_linked_stop_output when the turn was
    triggered by a direct conversation (flag=False), even if deliver_inbound
    poisoned last_message_sent with linked output content."""
    session = _make_session(
        turn_triggered_by_linked_output=False,
        last_message_sent=f"{LINKED_PREFIX}someone:\npoisoned by deliver_inbound",
        last_input_origin=InputOrigin.REDIS.value,
    )

    db_mock = MagicMock()
    db_mock.get_session = AsyncMock(return_value=session)
    db_mock.update_session = AsyncMock()

    coord = _make_coordinator()
    context = _make_stop_context("sess-001")

    with (
        patch("teleclaude.core.agent_coordinator._coordinator.db", db_mock),
        patch("teleclaude.core.agent_coordinator._fanout.db", db_mock),
        patch.object(coord, "_extract_agent_output", new_callable=AsyncMock, return_value="some output"),
        patch.object(coord, "_summarize_output", new_callable=AsyncMock, return_value="summary"),
        patch.object(coord, "_maybe_send_incremental_output", new_callable=AsyncMock),
        patch.object(coord, "_fanout_linked_stop_output", new_callable=AsyncMock) as fanout_mock,
        patch.object(coord, "_notify_session_listener", new_callable=AsyncMock),
        patch.object(coord, "_forward_stop_to_initiator", new_callable=AsyncMock),
        patch.object(coord, "_maybe_inject_checkpoint", new_callable=AsyncMock),
        patch("teleclaude.core.agent_coordinator._coordinator.is_threaded_output_enabled", return_value=False),
    ):
        await coord.handle_agent_stop(context)

    fanout_mock.assert_called_once()


@pytest.mark.asyncio
async def test_stop_fanout_suppressed_when_flag_true():
    """handle_agent_stop must NOT call _fanout_linked_stop_output when the turn
    was triggered by linked output (flag=True)."""
    session = _make_session(turn_triggered_by_linked_output=True)

    db_mock = MagicMock()
    db_mock.get_session = AsyncMock(return_value=session)
    db_mock.update_session = AsyncMock()

    coord = _make_coordinator()
    context = _make_stop_context("sess-001")

    with (
        patch("teleclaude.core.agent_coordinator._coordinator.db", db_mock),
        patch("teleclaude.core.agent_coordinator._fanout.db", db_mock),
        patch.object(coord, "_extract_agent_output", new_callable=AsyncMock, return_value="some output"),
        patch.object(coord, "_summarize_output", new_callable=AsyncMock, return_value="summary"),
        patch.object(coord, "_maybe_send_incremental_output", new_callable=AsyncMock),
        patch.object(coord, "_fanout_linked_stop_output", new_callable=AsyncMock) as fanout_mock,
        patch.object(coord, "_notify_session_listener", new_callable=AsyncMock),
        patch.object(coord, "_forward_stop_to_initiator", new_callable=AsyncMock),
        patch.object(coord, "_maybe_inject_checkpoint", new_callable=AsyncMock),
        patch("teleclaude.core.agent_coordinator._coordinator.is_threaded_output_enabled", return_value=False),
    ):
        await coord.handle_agent_stop(context)

    fanout_mock.assert_not_called()


@pytest.mark.asyncio
async def test_stop_clears_flag_after_suppression():
    """handle_agent_stop must reset turn_triggered_by_linked_output to False
    after using it for the fan-out decision."""
    session = _make_session(turn_triggered_by_linked_output=True)

    db_mock = MagicMock()
    db_mock.get_session = AsyncMock(return_value=session)
    db_mock.update_session = AsyncMock()

    coord = _make_coordinator()
    context = _make_stop_context("sess-001")

    with (
        patch("teleclaude.core.agent_coordinator._coordinator.db", db_mock),
        patch("teleclaude.core.agent_coordinator._fanout.db", db_mock),
        patch.object(coord, "_extract_agent_output", new_callable=AsyncMock, return_value="some output"),
        patch.object(coord, "_summarize_output", new_callable=AsyncMock, return_value="summary"),
        patch.object(coord, "_maybe_send_incremental_output", new_callable=AsyncMock),
        patch.object(coord, "_fanout_linked_stop_output", new_callable=AsyncMock),
        patch.object(coord, "_notify_session_listener", new_callable=AsyncMock),
        patch.object(coord, "_forward_stop_to_initiator", new_callable=AsyncMock),
        patch.object(coord, "_maybe_inject_checkpoint", new_callable=AsyncMock),
        patch("teleclaude.core.agent_coordinator._coordinator.is_threaded_output_enabled", return_value=False),
    ):
        await coord.handle_agent_stop(context)

    clear_calls = [
        c for c in db_mock.update_session.call_args_list if c.kwargs.get("turn_triggered_by_linked_output") is False
    ]
    assert len(clear_calls) >= 1, "Flag must be reset to False after fan-out decision"
