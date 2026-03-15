"""Characterization tests for teleclaude.types.commands."""

from __future__ import annotations

from teleclaude.types.commands import (
    CloseSessionCommand,
    CommandType,
    CreateSessionCommand,
    GetSessionDataCommand,
    HandleFileCommand,
    HandleVoiceCommand,
    InternalCommand,
    KeysCommand,
    ProcessMessageCommand,
    RestartAgentCommand,
    ResumeAgentCommand,
    RunAgentCommand,
    StartAgentCommand,
    SystemCommand,
)


def test_command_type_values_cover_internal_dispatch_commands() -> None:
    assert [member.value for member in CommandType] == [
        "create_session",
        "handle_voice",
        "handle_file",
        "keys",
        "start_agent",
        "resume_agent",
        "process_message",
        "run_agent_command",
        "restart_agent",
        "get_session_data",
        "close_session",
        "system_command",
    ]


def test_internal_command_base_payload_is_empty_dict() -> None:
    command = InternalCommand(command_type=CommandType.SYSTEM, request_id="req-1")

    assert command.to_payload() == {}


def test_create_session_payload_uses_blank_session_id_and_optional_title_arg() -> None:
    titled = CreateSessionCommand(project_path="/repo", origin="telegram", title="Release check")
    untitled = CreateSessionCommand(project_path="/repo", origin="telegram")

    assert titled.to_payload() == {"session_id": "", "args": ["Release check"]}
    assert untitled.to_payload() == {"session_id": "", "args": []}


def test_start_resume_and_restart_commands_build_argument_lists_from_optional_values() -> None:
    start = StartAgentCommand(session_id="session-1", agent_name="codex", args=["--fast"])
    resume = ResumeAgentCommand(session_id="session-2", agent_name="claude", native_session_id="native-9")
    restart = RestartAgentCommand(session_id="session-3")

    assert start.to_payload() == {"session_id": "session-1", "args": ["codex", "--fast"]}
    assert resume.to_payload() == {"session_id": "session-2", "args": ["claude", "native-9"]}
    assert restart.to_payload() == {"session_id": "session-3", "args": []}


def test_process_message_payload_omits_optional_actor_fields_when_missing() -> None:
    minimal = ProcessMessageCommand(session_id="session-1", text="hello", origin="telegram")
    enriched = ProcessMessageCommand(
        session_id="session-2",
        text="hello",
        origin="discord",
        actor_id="user-7",
        actor_name="Morriz",
        actor_avatar_url="https://example.com/avatar.png",
    )

    assert minimal.to_payload() == {"session_id": "session-1", "text": "hello", "origin": "telegram"}
    assert enriched.to_payload() == {
        "session_id": "session-2",
        "text": "hello",
        "origin": "discord",
        "actor_id": "user-7",
        "actor_name": "Morriz",
        "actor_avatar_url": "https://example.com/avatar.png",
    }


def test_handle_voice_and_file_payloads_include_only_present_optional_fields() -> None:
    voice = HandleVoiceCommand(
        session_id="session-1",
        file_path="/tmp/audio.ogg",
        duration=2.5,
        message_id="msg-8",
        message_thread_id=42,
        origin="telegram",
        actor_id="user-7",
    )
    uploaded_file = HandleFileCommand(
        session_id="session-1",
        file_path="/tmp/spec.md",
        filename="spec.md",
        caption="todo",
        file_size=512,
    )

    assert voice.to_payload() == {
        "session_id": "session-1",
        "file_path": "/tmp/audio.ogg",
        "duration": 2.5,
        "message_id": "msg-8",
        "message_thread_id": 42,
        "origin": "telegram",
        "actor_id": "user-7",
    }
    assert uploaded_file.to_payload() == {
        "session_id": "session-1",
        "file_path": "/tmp/spec.md",
        "filename": "spec.md",
        "file_size": 512,
        "caption": "todo",
    }


def test_keys_run_get_session_close_and_system_commands_preserve_dispatch_shape() -> None:
    keys = KeysCommand(session_id="session-1", key="enter", args=["ctrl"])
    run = RunAgentCommand(session_id="session-1", command="/test", args="value", origin="telegram")
    session_data = GetSessionDataCommand(
        session_id="session-1",
        since_timestamp="2024-01-01T00:00:00+00:00",
        until_timestamp="2024-01-01T00:05:00+00:00",
        tail_chars=9000,
    )
    close = CloseSessionCommand(session_id="session-2")
    system = SystemCommand(
        command="list-sessions",
        args=["--json"],
        data={"from_computer": "laptop", "limit": 5},
        session_id="session-3",
    )

    assert keys.to_payload() == {"session_id": "session-1", "args": ["ctrl"]}
    assert run.to_payload() == {
        "session_id": "session-1",
        "command": "/test",
        "args": "value",
        "origin": "telegram",
    }
    assert session_data.to_payload() == {
        "session_id": "session-1",
        "since_timestamp": "2024-01-01T00:00:00+00:00",
        "until_timestamp": "2024-01-01T00:05:00+00:00",
        "tail_chars": 9000,
    }
    assert close.to_payload() == {"session_id": "session-2", "args": []}
    assert system.to_payload() == {
        "command": "list-sessions",
        "args": ["--json"],
        "session_id": "session-3",
        "data": {"from_computer": "laptop", "limit": 5},
        "from_computer": "laptop",
    }
