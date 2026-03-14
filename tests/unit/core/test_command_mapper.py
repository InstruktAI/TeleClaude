"""Characterization tests for teleclaude.core.command_mapper."""

from __future__ import annotations

import pytest

# _KEY_COMMANDS: public API (CommandMapper.map_*_input) requires transport-specific
# context objects; testing the mapping constant directly pins the dispatch table.
from teleclaude.core.command_mapper import _KEY_COMMANDS, CommandMapper
from teleclaude.core.models import MessageMetadata
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    KeysCommand,
    ProcessMessageCommand,
    StartAgentCommand,
)


class TestKeyCommands:
    @pytest.mark.unit
    def test_cancel_is_key_command(self):
        assert "cancel" in _KEY_COMMANDS

    @pytest.mark.unit
    def test_enter_is_key_command(self):
        assert "enter" in _KEY_COMMANDS


class TestCommandMapperTelegram:
    @pytest.mark.unit
    def test_key_event_returns_keys_command(self):
        metadata = MessageMetadata()
        cmd = CommandMapper.map_telegram_input("cancel", [], metadata, "sess-1")
        assert isinstance(cmd, KeysCommand)
        assert cmd.key == "cancel"

    @pytest.mark.unit
    def test_new_session_event_returns_create_command(self):
        metadata = MessageMetadata(project_path="/tmp/proj")
        cmd = CommandMapper.map_telegram_input("new_session", [], metadata)
        assert isinstance(cmd, CreateSessionCommand)

    @pytest.mark.unit
    def test_message_event_returns_process_message_command(self):
        metadata = MessageMetadata()
        cmd = CommandMapper.map_telegram_input("message", ["hello", "world"], metadata, "sess-1")
        assert isinstance(cmd, ProcessMessageCommand)
        assert cmd.text == "hello world"

    @pytest.mark.unit
    def test_agent_event_returns_start_agent_command(self):
        metadata = MessageMetadata()
        cmd = CommandMapper.map_telegram_input("agent", ["claude"], metadata, "sess-1")
        assert isinstance(cmd, StartAgentCommand)
        assert cmd.agent_name == "claude"

    @pytest.mark.unit
    def test_exit_event_returns_close_session_command(self):
        metadata = MessageMetadata()
        cmd = CommandMapper.map_telegram_input("exit", [], metadata, "sess-1")
        assert isinstance(cmd, CloseSessionCommand)

    @pytest.mark.unit
    def test_unknown_event_raises_value_error(self):
        metadata = MessageMetadata()
        with pytest.raises(ValueError, match="Unknown telegram command"):
            CommandMapper.map_telegram_input("unknown_event_xyz", [], metadata)


class TestCommandMapperRedis:
    @pytest.mark.unit
    def test_message_command_returns_process_message(self):
        cmd = CommandMapper.map_redis_input(
            "message hello world",
            origin="api",
            session_id="sess-2",
        )
        assert isinstance(cmd, ProcessMessageCommand)
        assert cmd.text == "hello world"

    @pytest.mark.unit
    def test_key_command_returns_keys_command(self):
        cmd = CommandMapper.map_redis_input("cancel", origin="telegram", session_id="sess-3")
        assert isinstance(cmd, KeysCommand)
        assert cmd.key == "cancel"

    @pytest.mark.unit
    def test_unknown_redis_command_raises(self):
        with pytest.raises(ValueError, match="Unknown redis command"):
            CommandMapper.map_redis_input("unknown_xyz_command", origin="api")

    @pytest.mark.unit
    def test_end_session_returns_close_command(self):
        cmd = CommandMapper.map_redis_input("end_session", origin="api", session_id="sess-4")
        assert isinstance(cmd, CloseSessionCommand)


class TestCommandMapperApi:
    @pytest.mark.unit
    def test_new_session_returns_create_command(self):
        metadata = MessageMetadata(project_path="/tmp/proj", origin="api")
        cmd = CommandMapper.map_api_input("new_session", {}, metadata)
        assert isinstance(cmd, CreateSessionCommand)

    @pytest.mark.unit
    def test_message_returns_process_command(self):
        metadata = MessageMetadata(origin="api")
        cmd = CommandMapper.map_api_input("message", {"session_id": "s1", "text": "hi"}, metadata)
        assert isinstance(cmd, ProcessMessageCommand)
        assert cmd.text == "hi"

    @pytest.mark.unit
    def test_end_session_returns_close_command(self):
        metadata = MessageMetadata(origin="api")
        cmd = CommandMapper.map_api_input("end_session", {"session_id": "s1"}, metadata)
        assert isinstance(cmd, CloseSessionCommand)

    @pytest.mark.unit
    def test_unknown_api_command_raises(self):
        metadata = MessageMetadata(origin="api")
        with pytest.raises(ValueError, match="Unknown api command"):
            CommandMapper.map_api_input("not_a_command", {}, metadata)
