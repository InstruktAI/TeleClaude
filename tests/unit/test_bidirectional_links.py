"""Unit tests for bidirectional conversation links."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.constants import CHECKPOINT_MESSAGE
from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.db import db
from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import (
    add_link_member,
    create_link,
    get_active_links_for_session,
    get_link_members,
)
from teleclaude.mcp_server import TeleClaudeMCPServer


@pytest.fixture(autouse=True)
async def _init_db():
    await db.initialize()
    yield


@pytest.fixture
def mcp_server():
    """MCP server with mocked transport and command service."""
    mock_client = MagicMock()
    mock_client.discover_peers = AsyncMock(return_value=[])
    mock_client.send_request = AsyncMock(return_value=None)

    command_service = MagicMock()
    command_service.process_message = AsyncMock(return_value=None)
    command_service.create_session = AsyncMock(return_value={"session_id": "unused"})
    command_service.start_agent = AsyncMock(return_value=None)
    command_service.end_session = AsyncMock(return_value={"status": "success"})
    command_service.get_session_data = AsyncMock(return_value={"status": "success", "messages": ""})

    with (
        patch("teleclaude.mcp.handlers.get_command_service", return_value=command_service),
        patch("teleclaude.mcp_server.config") as mock_config,
    ):
        mock_config.computer.name = "TestComputer"
        mock_config.mcp.socket_path = "/tmp/test.sock"
        server = TeleClaudeMCPServer(adapter_client=mock_client, tmux_bridge=MagicMock())
        server.command_service = command_service
        yield server, command_service, mock_client


@pytest.mark.asyncio
async def test_direct_send_message_creates_and_reuses_single_link(mcp_server):
    """direct=True should create once and reuse the same shared link."""
    server, command_service, _mock_client = mcp_server
    await db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tc_a",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Session A",
        session_id="sess-a",
    )
    await db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tc_b",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Session B",
        session_id="sess-b",
    )

    first_chunks = []
    async for chunk in server.teleclaude__send_message(
        computer="local",
        session_id="sess-b",
        message="hello 1",
        caller_session_id="sess-a",
        direct=True,
    ):
        first_chunks.append(chunk)

    second_chunks = []
    async for chunk in server.teleclaude__send_message(
        computer="local",
        session_id="sess-b",
        message="hello 2",
        caller_session_id="sess-a",
        direct=True,
    ):
        second_chunks.append(chunk)

    assert "direct link" in "".join(first_chunks).lower()
    assert "reused" in "".join(second_chunks).lower()
    assert command_service.process_message.await_count == 2

    active_links = await get_active_links_for_session("sess-a")
    assert len(active_links) == 1
    members = await get_link_members(active_links[0].link_id)
    assert {member.session_id for member in members} == {"sess-a", "sess-b"}


@pytest.mark.asyncio
async def test_direct_send_message_fans_out_to_all_other_link_members(mcp_server):
    """In 3-member link, sender messages should route to all peers and exclude sender."""
    server, command_service, _mock_client = mcp_server
    for sid in ("sess-a", "sess-b", "sess-c"):
        await db.create_session(
            computer_name="TestComputer",
            tmux_session_name=f"tc_{sid}",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title=sid,
            session_id=sid,
        )

    link = await create_link(mode="gathering_link", created_by_session_id="sess-a")
    await add_link_member(link_id=link.link_id, session_id="sess-a", participant_number=1, computer_name="TestComputer")
    await add_link_member(link_id=link.link_id, session_id="sess-b", participant_number=2, computer_name="TestComputer")
    await add_link_member(link_id=link.link_id, session_id="sess-c", participant_number=3, computer_name="TestComputer")

    async for _ in server.teleclaude__send_message(
        computer="local",
        session_id="sess-b",
        message="fanout",
        caller_session_id="sess-a",
        direct=True,
    ):
        pass

    delivered_targets = [
        call.args[0].session_id for call in command_service.process_message.await_args_list if call.args
    ]
    assert sorted(delivered_targets) == ["sess-b", "sess-c"]
    assert await get_active_links_for_session("sess-a")
    assert len(await get_active_links_for_session("sess-a")) == 1


@pytest.mark.asyncio
async def test_close_link_true_severs_link_for_all_members(mcp_server):
    """close_link=True should allow single-party severing."""
    server, _command_service, _mock_client = mcp_server
    await db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tc_a",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Session A",
        session_id="sess-a",
    )
    await db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tc_b",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Session B",
        session_id="sess-b",
    )

    async for _ in server.teleclaude__send_message(
        computer="local",
        session_id="sess-b",
        message="open link",
        caller_session_id="sess-a",
        direct=True,
    ):
        pass

    chunks = []
    async for chunk in server.teleclaude__send_message(
        computer="local",
        session_id="sess-b",
        message="",
        caller_session_id="sess-a",
        close_link=True,
    ):
        chunks.append(chunk)

    assert "closed shared link" in "".join(chunks).lower()
    assert await get_active_links_for_session("sess-a") == []
    assert await get_active_links_for_session("sess-b") == []


@pytest.mark.asyncio
async def test_checkpoint_stop_output_not_fanned_out():
    """Checkpoint stop turns should not cross links."""
    mock_client = MagicMock()
    mock_client.send_request = AsyncMock(return_value=None)
    mock_client.break_threaded_turn = AsyncMock(return_value=None)
    mock_tts = MagicMock()
    mock_tts.speak = AsyncMock(return_value=None)
    coordinator = AgentCoordinator(mock_client, mock_tts, MagicMock())

    await db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tc_sender",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Sender",
        session_id="sender",
    )
    await db.create_session(
        computer_name="TestComputer",
        tmux_session_name="tc_peer",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Peer",
        session_id="peer",
    )
    link = await create_link(mode="direct_link", created_by_session_id="sender")
    await add_link_member(link_id=link.link_id, session_id="sender", computer_name="TestComputer")
    await add_link_member(link_id=link.link_id, session_id="peer", computer_name="TestComputer")

    payload = AgentStopPayload(
        session_id="sender",
        prompt=CHECKPOINT_MESSAGE,
        raw={"agent_name": "claude"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_STOP, session_id="sender", data=payload)

    with (
        patch.object(coordinator, "_extract_agent_output", new=AsyncMock(return_value="should-not-forward")),
        patch.object(coordinator, "_summarize_output", new=AsyncMock(return_value=None)),
        patch.object(coordinator, "_maybe_send_incremental_output", new=AsyncMock(return_value=False)),
        patch.object(coordinator, "_extract_user_input_for_codex", new=AsyncMock(return_value=None)),
        patch.object(coordinator, "_notify_session_listener", new=AsyncMock(return_value=None)),
        patch.object(coordinator, "_forward_stop_to_initiator", new=AsyncMock(return_value=None)),
        patch.object(coordinator, "_maybe_inject_checkpoint", new=AsyncMock(return_value=None)),
        patch.object(coordinator, "_fanout_linked_stop_output", new=AsyncMock(return_value=0)) as mock_fanout,
    ):
        await coordinator.handle_agent_stop(context)

    mock_fanout.assert_not_called()
