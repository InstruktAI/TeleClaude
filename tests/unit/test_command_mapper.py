"""Unit tests for CommandMapper."""

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
