"""Mapper module to normalize transport inputs into internal command models."""

from typing import cast

from teleclaude.config.machine import config
from teleclaude.constants import EVENT_NEW_SESSION
from teleclaude.core.agents import get_default_agent
from teleclaude.core.command_input import CommandInputMode
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    HandleFileCommand,
    HandleVoiceCommand,
    HandoffAgentCommand,
    InternalCommand,
    KeysCommand,
    ProcessMessageCommand,
    RestartAgentCommand,
    StartAgentCommand,
)


def _require_origin() -> str:
    """Fail-fast: origin must be provided by caller."""
    raise ValueError("MessageMetadata.origin is required - caller must set it")


def _with_computer(command: InternalCommand, computer: str | None) -> InternalCommand:
    command.computer = computer
    return command


KEY_COMMANDS = {
    "cancel",
    "cancel2x",
    "kill",
    "tab",
    "shift_tab",
    "enter",
    "escape",
    "escape2x",
    "backspace",
    "key_up",
    "key_down",
    "key_left",
    "key_right",
    "ctrl",
}

_ORIGIN_PAYLOAD_KEY = "origin"
_ACTOR_ID_PAYLOAD_KEY = "actor_id"
_SOURCE_MESSAGE_ID_PAYLOAD_KEY = "source_message_id"
_SOURCE_FEATURE_BY_ORIGIN = {
    InputOrigin.TELEGRAM.value: InjectedTextSourceFeature.TELEGRAM,
    InputOrigin.DISCORD.value: InjectedTextSourceFeature.DISCORD,
    InputOrigin.WHATSAPP.value: InjectedTextSourceFeature.WHATSAPP,
    InputOrigin.GITHUB.value: InjectedTextSourceFeature.GITHUB,
    InputOrigin.REMINDER.value: InjectedTextSourceFeature.REMINDER,
    InputOrigin.TERMINAL.value: InjectedTextSourceFeature.CALLER_SEND,
}


def _source_feature_for_origin(origin: str) -> InjectedTextSourceFeature:
    """Resolve a closed source feature at the transport boundary."""
    try:
        return _SOURCE_FEATURE_BY_ORIGIN[origin]
    except KeyError as exc:
        raise ValueError(f"Unsupported message origin: {origin}") from exc


class CommandMapper:
    """Maps transport-specific payloads to internal command models."""

    @staticmethod
    def map_api_input(
        command_name: str,
        payload: dict[str, object],
        metadata: MessageMetadata,
        computer: str | None = None,
    ) -> InternalCommand:
        """Map API input to internal command."""
        session_id = str(payload.get("session_id", ""))

        if command_name == EVENT_NEW_SESSION:
            skip_listener_registration_raw = payload.get("skip_listener_registration")
            skip_listener_registration = (
                skip_listener_registration_raw if isinstance(skip_listener_registration_raw, bool) else False
            )
            initiator_raw = payload.get("initiator_session_id")
            initiator_session_id = str(initiator_raw) if initiator_raw else None
            initial_input_raw = payload.get("initial_input")
            initial_input = str(initial_input_raw) if initial_input_raw is not None else None
            title_raw = payload.get("title")
            title = str(title_raw) if title_raw is not None else None
            working_slug_raw = payload.get("working_slug")
            working_slug = str(working_slug_raw) if working_slug_raw is not None else None
            command_raw = payload.get("command")
            command = str(command_raw) if command_raw is not None else None
            raw_command_input_mode = payload.get("command_input_mode", CommandInputMode.ORDINARY)
            command_input_mode = CommandInputMode(str(raw_command_input_mode))
            command_input_source_text_raw = payload.get("command_input_source_text")
            command_input_source_text = (
                str(command_input_source_text_raw) if command_input_source_text_raw is not None else None
            )
            return _with_computer(
                CreateSessionCommand(
                    project_path=metadata.project_path or "",
                    initial_input=initial_input,
                    title=title,
                    subdir=metadata.subdir,
                    human_email=metadata.human_email,
                    human_role=metadata.human_role,
                    origin=metadata.origin or _require_origin(),
                    origin_metadata=metadata.origin_metadata,
                    launch_intent=metadata.launch_intent,
                    role=metadata.role,
                    job=metadata.job,
                    company=metadata.company,
                    skip_listener_registration=skip_listener_registration,
                    initiator_session_id=initiator_session_id,
                    initiator_computer=config.computer.name if initiator_session_id else None,
                    startup_work_expected=bool(payload.get("startup_work_expected", False)),
                    command=command,
                    working_slug=working_slug,
                    command_input_mode=command_input_mode,
                    command_input_source_text=command_input_source_text,
                ),
                computer,
            )

        if command_name == "message":
            payload_actor_id_obj = payload.get("actor_id")
            payload_actor_name_obj = payload.get("actor_name")
            payload_actor_avatar_obj = payload.get("actor_avatar_url")
            payload_actor_id = str(payload_actor_id_obj).strip() if payload_actor_id_obj is not None else ""
            payload_actor_name = str(payload_actor_name_obj).strip() if payload_actor_name_obj is not None else ""
            payload_actor_avatar = str(payload_actor_avatar_obj).strip() if payload_actor_avatar_obj is not None else ""
            raw_text_kind = payload.get("text_kind")
            text_kind = (
                TranscriptEntryKind(str(raw_text_kind))
                if raw_text_kind is not None
                else metadata.text_kind
                or (
                    TranscriptEntryKind.IDENTITY_CONTENT if metadata.caller_session_id else TranscriptEntryKind.ORDINARY
                )
            )
            raw_source_feature = payload.get("source_feature")
            raw_command_input_mode = payload.get("command_input_mode", CommandInputMode.ORDINARY)
            command_input_mode = CommandInputMode(str(raw_command_input_mode))
            sender_human_role_raw = payload.get("sender_human_role")
            sender_human_role = str(sender_human_role_raw) if sender_human_role_raw is not None else None
            source_feature = (
                InjectedTextSourceFeature(str(raw_source_feature))
                if raw_source_feature is not None
                else (
                    InjectedTextSourceFeature.CALLER_SEND
                    if metadata.caller_session_id
                    else _source_feature_for_origin(metadata.origin or _require_origin())
                )
            )
            return _with_computer(
                ProcessMessageCommand(
                    session_id=session_id,
                    text=str(payload.get("text", "")),
                    origin=metadata.origin or _require_origin(),
                    text_kind=text_kind,
                    source_feature=source_feature,
                    occurrence_key=cast(str | None, payload.get("occurrence_key"))
                    or cast(str | None, payload.get("source_message_id")),
                    actor_id=payload_actor_id or metadata.actor_id,
                    actor_name=payload_actor_name or metadata.actor_name,
                    actor_avatar_url=payload_actor_avatar or metadata.actor_avatar_url,
                    origin_metadata=metadata.origin_metadata,
                    caller_session_id=metadata.caller_session_id,
                    caller_author_kind=metadata.caller_author_kind,
                    caller_author_display=metadata.caller_author_display,
                    caller_agent_runtime=metadata.caller_agent_runtime,
                    caller_thinking_mode=metadata.caller_thinking_mode,
                    caller_machine_role=metadata.caller_machine_role,
                    caller_job_role=metadata.caller_job_role,
                    caller_origin_prefix_len=metadata.caller_origin_prefix_len,
                    caller_origin_suffix_len=metadata.caller_origin_suffix_len,
                    source_message_id=cast(str | None, payload.get("source_message_id")),
                    source_channel_id=cast(str | None, payload.get("source_channel_id")),
                    command_input_mode=command_input_mode,
                    sender_human_role=sender_human_role,
                ),
                computer,
            )

        if command_name == "keys":
            key = str(payload.get("key", ""))
            args = cast(list[str], payload.get("args", []))
            return _with_computer(
                KeysCommand(
                    session_id=session_id,
                    key=key,
                    args=args,
                ),
                computer,
            )

        if command_name == "handle_voice":
            payload_actor_id_obj = payload.get("actor_id")
            payload_actor_name_obj = payload.get("actor_name")
            payload_actor_avatar_obj = payload.get("actor_avatar_url")
            payload_transcription_id_obj = payload.get("voice_transcription_id")
            payload_notice_message_id_obj = payload.get("notice_message_id")
            payload_actor_id = str(payload_actor_id_obj).strip() if payload_actor_id_obj is not None else ""
            payload_actor_name = str(payload_actor_name_obj).strip() if payload_actor_name_obj is not None else ""
            payload_actor_avatar = str(payload_actor_avatar_obj).strip() if payload_actor_avatar_obj is not None else ""
            payload_transcription_id = (
                int(cast(int | str, payload_transcription_id_obj)) if payload_transcription_id_obj is not None else None
            )
            payload_notice_message_id = (
                str(payload_notice_message_id_obj).strip() if payload_notice_message_id_obj is not None else ""
            )
            return _with_computer(
                HandleVoiceCommand(
                    session_id=session_id,
                    file_path=str(payload.get("file_path", "")),
                    duration=cast(float | None, payload.get("duration")),
                    message_id=cast(str | None, payload.get("message_id")),
                    message_thread_id=cast(int | None, payload.get("message_thread_id")),
                    origin=metadata.origin or _require_origin(),
                    actor_id=payload_actor_id or metadata.actor_id,
                    actor_name=payload_actor_name or metadata.actor_name,
                    actor_avatar_url=payload_actor_avatar or metadata.actor_avatar_url,
                    origin_metadata=metadata.origin_metadata,
                    voice_transcription_id=payload_transcription_id,
                    notice_message_id=payload_notice_message_id or None,
                    source_message_id=cast(str | None, payload.get(_SOURCE_MESSAGE_ID_PAYLOAD_KEY)),
                ),
                computer,
            )

        if command_name == "handle_file":
            return _with_computer(
                HandleFileCommand(
                    session_id=session_id,
                    file_path=str(payload.get("file_path", "")),
                    filename=str(payload.get("filename", "")),
                    caption=cast(str | None, payload.get("caption")),
                    file_size=cast(int, payload.get("file_size", 0)),
                    origin=cast(str | None, payload.get(_ORIGIN_PAYLOAD_KEY)) or metadata.origin,
                    actor_id=cast(str | None, payload.get(_ACTOR_ID_PAYLOAD_KEY)) or metadata.actor_id,
                    source_message_id=cast(str | None, payload.get(_SOURCE_MESSAGE_ID_PAYLOAD_KEY)),
                ),
                computer,
            )

        if command_name == "agent":
            args = cast(list[str], payload.get("args", []))
            agent_name = args[0] if args else get_default_agent()
            return _with_computer(
                StartAgentCommand(
                    session_id=session_id,
                    agent_name=agent_name,
                    args=args[1:] if len(args) > 1 else [],
                    origin=metadata.origin,
                ),
                computer,
            )

        if command_name in {"agent_restart", "agent_handoff"}:
            args = cast(list[str], payload.get("args", []))
            agent_name = args[0] if args else None
            if command_name == "agent_handoff" or bool(payload.get("handoff")):
                return _with_computer(
                    HandoffAgentCommand(
                        session_id=session_id,
                        agent_name=cast(str | None, payload.get("agent")) or agent_name,
                        caller_role=cast(str | None, payload.get("caller_role")),
                    ),
                    computer,
                )
            return _with_computer(
                RestartAgentCommand(
                    session_id=session_id,
                    self_restart=bool(payload.get("self_restart")),
                ),
                computer,
            )

        if command_name == "end_session":
            return _with_computer(CloseSessionCommand(session_id=session_id), computer)

        raise ValueError(f"Unknown api command: {command_name}")
