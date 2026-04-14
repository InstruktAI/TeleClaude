"""Mapper module to normalize transport inputs into internal command models."""

from typing import cast

from teleclaude.core.agents import get_default_agent, get_known_agents
from teleclaude.core.events import parse_command_string
from teleclaude.core.models import MessageMetadata, SessionLaunchIntent
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    GetSessionDataCommand,
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


_KEY_COMMANDS = {
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
    def map_telegram_input(  # pylint: disable=too-many-return-statements
        event: str,
        args: list[str],
        metadata: MessageMetadata,
        session_id: str | None = None,
    ) -> InternalCommand:
        """Map Telegram adapter input to internal command."""
        if event in _KEY_COMMANDS:
            return KeysCommand(
                session_id=session_id or "",
                key=event,
                args=args,
            )

        if event == "new_session":
            return CreateSessionCommand(
                project_path=metadata.project_path or "",
                title=metadata.title or (args[0] if args else None),
                subdir=metadata.subdir,
                origin=InputOrigin.TELEGRAM.value,
                origin_metadata=metadata.origin_metadata,
                auto_command=metadata.auto_command,
            )

        if event == "message":
            return ProcessMessageCommand(
                session_id=session_id or "",
                text=" ".join(args),
                origin=metadata.origin or InputOrigin.TELEGRAM.value,
                actor_id=metadata.actor_id,
                actor_name=metadata.actor_name,
                actor_avatar_url=metadata.actor_avatar_url,
            )

        if event == "agent":
            agent_name = args[0] if args else get_default_agent()
            agent_args = args[1:] if len(args) > 1 else []
            return StartAgentCommand(
                session_id=session_id or "",
                agent_name=agent_name,
                args=agent_args,
            )

        if event == "agent_resume":
            agent_name = args[0] if args else None
            return ResumeAgentCommand(
                session_id=session_id or "",
                agent_name=agent_name,
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
    def map_redis_input(  # pylint: disable=too-many-arguments,too-many-branches,too-many-locals,too-many-return-statements
        command_str: str,
        *,
        origin: str,
        session_id: str | None = None,
        project_path: str | None = None,
        title: str | None = None,
        metadata: MessageMetadata | None = None,
        launch_intent: SessionLaunchIntent | dict[str, object] | None = None,
        initiator: str | None = None,  # pylint: disable=unused-argument
    ) -> InternalCommand:
        """Map Redis inbound message to internal command."""
        cmd_name, args = parse_command_string(command_str)
        if not origin:
            raise ValueError("Redis inbound message missing origin")
        launch_intent_obj: SessionLaunchIntent | None = None
        if isinstance(launch_intent, dict):
            launch_intent_obj = SessionLaunchIntent.from_dict(launch_intent)  # type: ignore[arg-type]
        elif isinstance(launch_intent, SessionLaunchIntent):
            launch_intent_obj = launch_intent

        if cmd_name in _KEY_COMMANDS:
            return KeysCommand(
                session_id=session_id or "",
                key=cmd_name,
                args=args,
            )

        if cmd_name == "message":
            return ProcessMessageCommand(
                session_id=session_id or "",
                text=" ".join(args) if args else "",
                origin=origin,
                actor_id=metadata.actor_id if metadata else None,
                actor_name=metadata.actor_name if metadata else None,
                actor_avatar_url=metadata.actor_avatar_url if metadata else None,
                source_message_id=metadata.platform_message_id if metadata else None,
            )

        if cmd_name == "agent":
            agent_name = args[0] if args else get_default_agent()
            return StartAgentCommand(
                session_id=session_id or "",
                agent_name=agent_name,
                args=args[1:] if len(args) > 1 else [],
            )

        if cmd_name in set(get_known_agents()):
            return StartAgentCommand(
                session_id=session_id or "",
                agent_name=cmd_name,
                args=args,
            )

        if cmd_name == "agent_resume":
            agent_name = args[0] if args else None
            native_session_id = args[1] if len(args) > 1 else None
            return ResumeAgentCommand(
                session_id=session_id or "",
                agent_name=agent_name,
                native_session_id=native_session_id,
            )

        known_agents = set(get_known_agents())
        resume_aliases = {f"{agent}_resume" for agent in known_agents}
        if cmd_name in resume_aliases:
            return ResumeAgentCommand(
                session_id=session_id or "",
                agent_name=cmd_name.replace("_resume", ""),
                native_session_id=args[0] if args else None,
            )

        if cmd_name == "new_session":
            return CreateSessionCommand(
                project_path=project_path or "",
                title=title or (" ".join(args) if args else None),
                origin=origin,
                launch_intent=launch_intent_obj,
            )

        if cmd_name == "agent_restart":
            agent_name = args[0] if args else None
            return RestartAgentCommand(
                session_id=session_id or "",
                agent_name=agent_name,
            )

        if cmd_name == "end_session":
            return CloseSessionCommand(session_id=session_id or "")

        if cmd_name == "get_session_data":
            since = None
            until = None
            tail_chars = 5000

            if len(args) == 1:
                candidate = args[0]
                if candidate not in ("", "-"):
                    try:
                        tail_chars = int(candidate)
                    except ValueError:
                        since = candidate
            elif len(args) >= 2:
                since = args[0]
                until = args[1]
                if len(args) > 2:
                    try:
                        tail_chars = int(args[2])
                    except ValueError:
                        tail_chars = 5000
            return GetSessionDataCommand(
                session_id=session_id or "",
                since_timestamp=since if since not in ("", "-") else None,
                until_timestamp=until if until not in ("", "-") else None,
                tail_chars=tail_chars,
            )

        raise ValueError(f"Unknown redis command: {cmd_name}")

    @staticmethod
    def map_api_input(  # pylint: disable=too-many-locals,too-many-return-statements
        command_name: str,
        payload: dict[str, object],
        metadata: MessageMetadata,
    ) -> InternalCommand:
        """Map API input to internal command."""
        session_id = str(payload.get("session_id", ""))

        if command_name == "new_session":
            skip_listener_registration_raw = payload.get("skip_listener_registration")
            skip_listener_registration = (
                skip_listener_registration_raw if isinstance(skip_listener_registration_raw, bool) else False
            )
            initiator_raw = payload.get("initiator_session_id")
            initiator_session_id = str(initiator_raw) if initiator_raw else None
            return CreateSessionCommand(
                project_path=metadata.project_path or "",
                title=metadata.title,
                subdir=metadata.subdir,
                human_email=metadata.human_email,
                human_role=metadata.human_role,
                origin=metadata.origin,
                origin_metadata=metadata.origin_metadata,
                launch_intent=metadata.launch_intent,
                auto_command=metadata.auto_command,
                system_role=metadata.system_role,
                job=metadata.job,
                skip_listener_registration=skip_listener_registration,
                initiator_session_id=initiator_session_id,
            )

        if command_name == "message":
            payload_actor_id_obj = payload.get("actor_id")
            payload_actor_name_obj = payload.get("actor_name")
            payload_actor_avatar_obj = payload.get("actor_avatar_url")
            payload_actor_id = str(payload_actor_id_obj).strip() if payload_actor_id_obj is not None else ""
            payload_actor_name = str(payload_actor_name_obj).strip() if payload_actor_name_obj is not None else ""
            payload_actor_avatar = str(payload_actor_avatar_obj).strip() if payload_actor_avatar_obj is not None else ""
            return ProcessMessageCommand(
                session_id=session_id,
                text=str(payload.get("text", "")),
                origin=metadata.origin or _require_origin(),
                actor_id=payload_actor_id or metadata.actor_id,
                actor_name=payload_actor_name or metadata.actor_name,
                actor_avatar_url=payload_actor_avatar or metadata.actor_avatar_url,
            )

        if command_name == "keys":
            key = str(payload.get("key", ""))
            args = cast(list[str], payload.get("args", []))
            return KeysCommand(
                session_id=session_id,
                key=key,
                args=args,
            )

        if command_name == "handle_voice":
            payload_actor_id_obj = payload.get("actor_id")
            payload_actor_name_obj = payload.get("actor_name")
            payload_actor_avatar_obj = payload.get("actor_avatar_url")
            payload_actor_id = str(payload_actor_id_obj).strip() if payload_actor_id_obj is not None else ""
            payload_actor_name = str(payload_actor_name_obj).strip() if payload_actor_name_obj is not None else ""
            payload_actor_avatar = str(payload_actor_avatar_obj).strip() if payload_actor_avatar_obj is not None else ""
            return HandleVoiceCommand(
                session_id=session_id,
                file_path=str(payload.get("file_path", "")),
                duration=cast(float | None, payload.get("duration")),
                message_id=cast(str | None, payload.get("message_id")),
                message_thread_id=cast(int | None, payload.get("message_thread_id")),
                origin=metadata.origin or _require_origin(),
                actor_id=payload_actor_id or metadata.actor_id,
                actor_name=payload_actor_name or metadata.actor_name,
                actor_avatar_url=payload_actor_avatar or metadata.actor_avatar_url,
            )

        if command_name == "handle_file":
            return HandleFileCommand(
                session_id=session_id,
                file_path=str(payload.get("file_path", "")),
                filename=str(payload.get("filename", "")),
                caption=cast(str | None, payload.get("caption")),
                file_size=cast(int, payload.get("file_size", 0)),
            )

        if command_name == "agent":
            args = cast(list[str], payload.get("args", []))
            agent_name = args[0] if args else get_default_agent()
            return StartAgentCommand(
                session_id=session_id,
                agent_name=agent_name,
                args=args[1:] if len(args) > 1 else [],
            )

        if command_name == "agent_restart":
            args = cast(list[str], payload.get("args", []))
            agent_name = args[0] if args else None
            return RestartAgentCommand(
                session_id=session_id,
                agent_name=agent_name,
                self_restart=bool(payload.get("self_restart")),
            )

        if command_name == "end_session":
            return CloseSessionCommand(session_id=session_id)

        raise ValueError(f"Unknown api command: {command_name}")
