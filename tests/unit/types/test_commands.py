"""Tests for command payload assembly — conditional field inclusion and argument building."""

from __future__ import annotations

from teleclaude.types.commands import (
    CreateSessionCommand,
    GetSessionDataCommand,
    HandleFileCommand,
    HandleVoiceCommand,
    ProcessMessageCommand,
    ResumeAgentCommand,
    SystemCommand,
)


def test_create_session_includes_title_in_args_when_provided() -> None:
    titled = CreateSessionCommand(project_path="/repo", origin="telegram", title="Release check")
    untitled = CreateSessionCommand(project_path="/repo", origin="telegram")

    assert titled.to_payload()["args"] == ["Release check"]
    assert untitled.to_payload()["args"] == []


def test_resume_agent_conditionally_appends_agent_name_and_native_session_id() -> None:
    full = ResumeAgentCommand(session_id="s-1", agent_name="claude", native_session_id="native-9")
    name_only = ResumeAgentCommand(session_id="s-1", agent_name="claude")
    bare = ResumeAgentCommand(session_id="s-1")

    assert full.to_payload()["args"] == ["claude", "native-9"]
    assert name_only.to_payload()["args"] == ["claude"]
    assert bare.to_payload()["args"] == []


def test_process_message_omits_actor_fields_when_not_provided() -> None:
    minimal = ProcessMessageCommand(session_id="s-1", text="hello", origin="telegram")
    enriched = ProcessMessageCommand(
        session_id="s-1",
        text="hello",
        origin="telegram",
        actor_id="user-7",
        actor_name="Mo",
        actor_avatar_url="https://example.com/a.png",
    )

    minimal_payload = minimal.to_payload()
    assert "actor_id" not in minimal_payload
    assert "actor_name" not in minimal_payload
    assert "actor_avatar_url" not in minimal_payload

    enriched_payload = enriched.to_payload()
    assert enriched_payload["actor_id"] == "user-7"
    assert enriched_payload["actor_name"] == "Mo"
    assert "actor_avatar_url" in enriched_payload


def test_handle_voice_omits_optional_fields_when_not_provided() -> None:
    minimal = HandleVoiceCommand(session_id="s-1", file_path="/tmp/a.ogg")
    full = HandleVoiceCommand(
        session_id="s-1",
        file_path="/tmp/a.ogg",
        duration=2.5,
        message_id="msg-8",
        message_thread_id=42,
        origin="telegram",
    )

    minimal_payload = minimal.to_payload()
    assert "duration" not in minimal_payload
    assert "message_id" not in minimal_payload

    full_payload = full.to_payload()
    assert full_payload["duration"] == 2.5
    assert full_payload["message_id"] == "msg-8"
    assert full_payload["message_thread_id"] == 42


def test_handle_file_omits_caption_when_not_provided() -> None:
    with_caption = HandleFileCommand(session_id="s-1", file_path="/tmp/f.md", filename="f.md", caption="notes")
    without = HandleFileCommand(session_id="s-1", file_path="/tmp/f.md", filename="f.md")

    assert "caption" in with_caption.to_payload()
    assert "caption" not in without.to_payload()


def test_get_session_data_omits_timestamps_when_not_provided() -> None:
    minimal = GetSessionDataCommand(session_id="s-1")
    full = GetSessionDataCommand(
        session_id="s-1",
        since_timestamp="2024-01-01T00:00:00+00:00",
        until_timestamp="2024-01-01T00:05:00+00:00",
    )

    minimal_payload = minimal.to_payload()
    assert "since_timestamp" not in minimal_payload
    assert "until_timestamp" not in minimal_payload
    assert "tail_chars" in minimal_payload

    full_payload = full.to_payload()
    assert "since_timestamp" in full_payload
    assert "until_timestamp" in full_payload


def test_system_command_extracts_from_computer_from_data() -> None:
    cmd = SystemCommand(
        command="list-sessions",
        data={"from_computer": "laptop", "limit": 5},
        session_id="s-1",
    )
    payload = cmd.to_payload()

    assert payload["from_computer"] == "laptop"
    assert payload["data"] == {"from_computer": "laptop", "limit": 5}


def test_system_command_omits_data_and_session_when_not_provided() -> None:
    cmd = SystemCommand(command="list-sessions")
    payload = cmd.to_payload()

    assert "data" not in payload
    assert "session_id" not in payload
