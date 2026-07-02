"""Mapper module to normalize transport inputs into internal command models."""

from typing import cast

from teleclaude.constants import EVENT_NEW_SESSION
from teleclaude.core.agents import get_default_agent
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    HandleFileCommand,
    HandleVoiceCommand,
    InternalCommand,
    KeysCommand,
    ProcessMessageCommand,
    RestartAgentCommand,
    ResumeAgentCommand,
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


class CommandMapper:
    """Maps transport-specific payloads to internal command models."""

    @staticmethod
    def map_telegram_input(
        event: str,
        args: list[str],
        metadata: MessageMetadata,
        session_id: str | None = None,
    ) -> InternalCommand:
        """Map Telegram adapter input to internal command."""
        if event in KEY_COMMANDS:
            return KeysCommand(
                session_id=session_id or "",
                key=event,
                args=args,
            )

        if event == EVENT_NEW_SESSION:
            initial_input = None
            if metadata.launch_intent and metadata.launch_intent.message:
                initial_input = metadata.launch_intent.message
            elif args:
                initial_input = " ".join(args)
            return CreateSessionCommand(
                project_path=metadata.project_path or "",
                initial_input=initial_input,
                subdir=metadata.subdir,
                origin=InputOrigin.TELEGRAM.value,
                origin_metadata=metadata.origin_metadata,
                launch_intent=metadata.launch_intent,
            )

        if event == "message":
            return ProcessMessageCommand(
                session_id=session_id or "",
                text=" ".join(args),
                origin=metadata.origin or InputOrigin.TELEGRAM.value,
                actor_id=metadata.actor_id,
                actor_name=metadata.actor_name,
                actor_avatar_url=metadata.actor_avatar_url,
                source_message_id=metadata.platform_message_id,
                origin_metadata=metadata.origin_metadata,
            )

        if event == "agent":
            agent_name = args[0] if args else get_default_agent()
            agent_args = args[1:] if len(args) > 1 else []
            return StartAgentCommand(
                session_id=session_id or "",
                agent_name=agent_name,
                args=agent_args,
                origin=metadata.origin or InputOrigin.TELEGRAM.value,
            )

        if event == "agent_resume":
            agent_name = args[0] if args else None
            return ResumeAgentCommand(
                session_id=session_id or "",
                agent_name=agent_name,
                origin=metadata.origin or InputOrigin.TELEGRAM.value,
            )

        if event == "agent_restart":
            agent_name = args[0] if args else None
            return RestartAgentCommand(
                session_id=session_id or "",
                agent_name=agent_name,
            )

        if event == "exit":
            return CloseSessionCommand(session_id=session_id or "")

        raise ValueError(f"Unknown telegram command: {event}")

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
            working_slug_raw = payload.get("working_slug")
            working_slug = str(working_slug_raw) if working_slug_raw is not None else None
            return _with_computer(
                CreateSessionCommand(
                    project_path=metadata.project_path or "",
                    initial_input=initial_input,
                    subdir=metadata.subdir,
                    human_email=metadata.human_email,
                    human_role=metadata.human_role,
                    origin=metadata.origin,
                    origin_metadata=metadata.origin_metadata,
                    launch_intent=metadata.launch_intent,
                    system_role=metadata.system_role,
                    job=metadata.job,
                    skip_listener_registration=skip_listener_registration,
                    initiator_session_id=initiator_session_id,
                    working_slug=working_slug,
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
            return _with_computer(
                ProcessMessageCommand(
                    session_id=session_id,
                    text=str(payload.get("text", "")),
                    origin=metadata.origin or _require_origin(),
                    actor_id=payload_actor_id or metadata.actor_id,
                    actor_name=payload_actor_name or metadata.actor_name,
                    actor_avatar_url=payload_actor_avatar or metadata.actor_avatar_url,
                    origin_metadata=metadata.origin_metadata,
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

        if command_name == "agent_restart":
            args = cast(list[str], payload.get("args", []))
            agent_name = args[0] if args else None
            return _with_computer(
                RestartAgentCommand(
                    session_id=session_id,
                    agent_name=agent_name,
                    self_restart=bool(payload.get("self_restart")),
                ),
                computer,
            )

        if command_name == "end_session":
            return _with_computer(CloseSessionCommand(session_id=session_id), computer)

        raise ValueError(f"Unknown api command: {command_name}")
