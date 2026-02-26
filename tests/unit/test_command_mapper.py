"""Unit tests for CommandMapper."""

import pytest

from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.models import MessageMetadata, SessionLaunchIntent, SessionLaunchKind
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import (
    CreateSessionCommand,
    KeysCommand,
    ProcessMessageCommand,
    StartAgentCommand,
)


def test_map_telegram_new_session():
    metadata = MessageMetadata(project_path="/path/to/project", title="Test Session", origin=InputOrigin.TELEGRAM.value)
    cmd = CommandMapper.map_telegram_input("new_session", [], metadata)
    assert isinstance(cmd, CreateSessionCommand)
    assert cmd.project_path == "/path/to/project"
    assert cmd.title == "Test Session"
    assert cmd.origin == InputOrigin.TELEGRAM.value


def test_map_telegram_message():
    metadata = MessageMetadata(origin=InputOrigin.TELEGRAM.value)
    cmd = CommandMapper.map_telegram_input("message", ["Hello", "World"], metadata, session_id="sess_123")
    assert isinstance(cmd, ProcessMessageCommand)
    assert cmd.session_id == "sess_123"
    assert cmd.text == "Hello World"
    assert cmd.origin == InputOrigin.TELEGRAM.value


def test_map_telegram_keys():
    cmd = CommandMapper.map_telegram_input("cancel", [], MessageMetadata(), session_id="sess_123")
    assert isinstance(cmd, KeysCommand)
    assert cmd.session_id == "sess_123"
    assert cmd.key == "cancel"
    assert cmd.args == []


def test_map_redis_new_session():
    launch_intent = SessionLaunchIntent(kind=SessionLaunchKind.AGENT, agent="claude")
    cmd = CommandMapper.map_redis_input(
        "new_session",
        project_path="/path/to/project",
        title="Redis Session",
        launch_intent=launch_intent,
        origin=InputOrigin.REDIS.value,
    )
    assert isinstance(cmd, CreateSessionCommand)
    assert cmd.project_path == "/path/to/project"
    assert cmd.title == "Redis Session"
    assert cmd.launch_intent == launch_intent
    assert cmd.origin == InputOrigin.REDIS.value


def test_map_redis_agent_start():
    cmd = CommandMapper.map_redis_input("claude --slow", session_id="sess_456", origin=InputOrigin.REDIS.value)
    assert isinstance(cmd, StartAgentCommand)
    assert cmd.session_id == "sess_456"
    assert cmd.agent_name == "claude"
    assert cmd.args == ["--slow"]


def test_map_redis_keys():
    cmd = CommandMapper.map_redis_input("key_up 3", session_id="sess_456", origin=InputOrigin.REDIS.value)
    assert isinstance(cmd, KeysCommand)
    assert cmd.session_id == "sess_456"
    assert cmd.key == "key_up"
    assert cmd.args == ["3"]


def test_map_rest_message():
    payload = {"session_id": "sess_789", "text": "REST message"}
    metadata = MessageMetadata(origin=InputOrigin.API.value)
    cmd = CommandMapper.map_api_input("message", payload, metadata)
    assert isinstance(cmd, ProcessMessageCommand)
    assert cmd.session_id == "sess_789"
    assert cmd.text == "REST message"
    assert cmd.origin == InputOrigin.API.value


def test_map_api_agent_defers_default_selection_when_no_explicit_agent() -> None:
    cmd = CommandMapper.map_api_input(
        "agent",
        {"session_id": "sess_789", "args": []},
        MessageMetadata(origin=InputOrigin.API.value),
    )
    assert isinstance(cmd, StartAgentCommand)
    assert cmd.agent_name is None
    assert cmd.args == []


def test_map_api_agent_treats_thinking_mode_as_arg_when_agent_omitted() -> None:
    cmd = CommandMapper.map_api_input(
        "agent",
        {"session_id": "sess_789", "args": ["slow"]},
        MessageMetadata(origin=InputOrigin.API.value),
    )
    assert isinstance(cmd, StartAgentCommand)
    assert cmd.agent_name is None
    assert cmd.args == ["slow"]


def test_map_api_agent_preserves_unknown_first_token_as_explicit_agent() -> None:
    cmd = CommandMapper.map_api_input(
        "agent",
        {"session_id": "sess_789", "args": ["claud"]},
        MessageMetadata(origin=InputOrigin.API.value),
    )
    assert isinstance(cmd, StartAgentCommand)
    assert cmd.agent_name == "claud"
    assert cmd.args == []


# --- R1/R2: Actor attribution parity across adapters ---


def test_map_telegram_message_actor_from_channel_metadata():
    """Telegram actor fields extracted from channel_metadata via telegram_user_id fallback."""
    metadata = MessageMetadata(
        origin=InputOrigin.TELEGRAM.value,
        channel_metadata={"telegram_user_id": "42", "user_name": "alice"},
    )
    cmd = CommandMapper.map_telegram_input("message", ["hi"], metadata, session_id="s1")
    assert isinstance(cmd, ProcessMessageCommand)
    assert cmd.origin == InputOrigin.TELEGRAM.value
    assert cmd.actor_id == "telegram:42"
    assert cmd.actor_name == "alice"


def test_map_telegram_message_actor_explicit_fields_take_precedence():
    """Explicit actor_id/actor_name in channel_metadata win over derived fallbacks."""
    metadata = MessageMetadata(
        origin=InputOrigin.TELEGRAM.value,
        channel_metadata={
            "actor_id": "custom_id",
            "actor_name": "Custom Name",
            "telegram_user_id": "99",
        },
    )
    cmd = CommandMapper.map_telegram_input("message", ["hi"], metadata, session_id="s2")
    assert isinstance(cmd, ProcessMessageCommand)
    assert cmd.actor_id == "custom_id"
    assert cmd.actor_name == "Custom Name"


def test_map_discord_message_actor_from_channel_metadata():
    """Discord actor_id derived from discord_user_id when no explicit actor fields."""
    cmd = CommandMapper.map_redis_input(
        "message hi there",
        origin=InputOrigin.DISCORD.value,
        session_id="s3",
        channel_metadata={"discord_user_id": "777", "display_name": "bob"},
    )
    assert isinstance(cmd, ProcessMessageCommand)
    assert cmd.origin == InputOrigin.DISCORD.value
    assert cmd.actor_id == "discord:777"
    assert cmd.actor_name == "bob"


def test_map_api_message_actor_from_payload():
    """API message uses actor fields from payload directly."""
    payload = {
        "session_id": "s4",
        "text": "hello",
        "actor_id": "web:user_123",
        "actor_name": "Web User",
        "actor_avatar_url": "https://example.com/avatar.png",
    }
    metadata = MessageMetadata(origin=InputOrigin.API.value)
    cmd = CommandMapper.map_api_input("message", payload, metadata)
    assert isinstance(cmd, ProcessMessageCommand)
    assert cmd.origin == InputOrigin.API.value
    assert cmd.actor_id == "web:user_123"
    assert cmd.actor_name == "Web User"
    assert cmd.actor_avatar_url == "https://example.com/avatar.png"


def test_all_interactive_adapters_produce_process_message_with_origin():
    """Parity check: all adapter paths produce ProcessMessageCommand with a non-empty origin."""
    telegram_cmd = CommandMapper.map_telegram_input(
        "message",
        ["hi"],
        MessageMetadata(origin=InputOrigin.TELEGRAM.value),
        session_id="s",
    )
    redis_cmd = CommandMapper.map_redis_input(
        "message hi",
        origin=InputOrigin.REDIS.value,
        session_id="s",
    )
    api_cmd = CommandMapper.map_api_input(
        "message",
        {"session_id": "s", "text": "hi"},
        MessageMetadata(origin=InputOrigin.API.value),
    )
    discord_cmd = CommandMapper.map_redis_input(
        "message hi",
        origin=InputOrigin.DISCORD.value,
        session_id="s",
    )

    for cmd in (telegram_cmd, redis_cmd, api_cmd, discord_cmd):
        assert isinstance(cmd, ProcessMessageCommand)
        assert cmd.origin, f"origin must be set for {type(cmd)}"
