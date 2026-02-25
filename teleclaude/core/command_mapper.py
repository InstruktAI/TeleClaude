"""Mapper module to normalize transport inputs into internal command models."""

from typing import Dict, List, Optional, cast

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
    def _normalize_actor_id(source: str, source_id: object) -> Optional[str]:
        text = str(source_id).strip() if source_id is not None else ""
        if not text:
            return None
        return f"{source}:{text}"

    @staticmethod
    def _extract_actor_from_channel_metadata(
        channel_metadata: Optional[Dict[str, object]], source: str
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        if not channel_metadata:
            return (None, None, None)

        actor_id_obj = channel_metadata.get("actor_id")
        actor_name_obj = channel_metadata.get("actor_name")
        actor_avatar_obj = channel_metadata.get("actor_avatar_url")

        actor_id = str(actor_id_obj).strip() if actor_id_obj is not None else ""
        actor_name = str(actor_name_obj).strip() if actor_name_obj is not None else ""
        actor_avatar = str(actor_avatar_obj).strip() if actor_avatar_obj is not None else ""
        if actor_id and actor_name:
            return (
                actor_id,
                actor_name,
                actor_avatar or None,
            )

        source_user_id = channel_metadata.get("user_id")
        if source_user_id is None and source == InputOrigin.DISCORD.value:
            source_user_id = channel_metadata.get("discord_user_id")
        if source_user_id is None and source == InputOrigin.TELEGRAM.value:
            source_user_id = channel_metadata.get("telegram_user_id")
        if source == InputOrigin.DISCORD.value and source_user_id is not None:
            actor_id = actor_id or CommandMapper._normalize_actor_id("discord", source_user_id) or ""
        elif source == InputOrigin.TELEGRAM.value and source_user_id is not None:
            actor_id = actor_id or CommandMapper._normalize_actor_id("telegram", source_user_id) or ""

        source_name_obj = channel_metadata.get("user_name") or channel_metadata.get("display_name")
        source_name = str(source_name_obj).strip() if source_name_obj is not None else ""
        actor_name = actor_name or source_name or actor_id

        return (
            actor_id or None,
            actor_name or None,
            actor_avatar or None,
        )

    @staticmethod
    def map_telegram_input(
        event: str,
        args: List[str],
        metadata: MessageMetadata,
        session_id: Optional[str] = None,
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
                channel_metadata=metadata.channel_metadata,
                auto_command=metadata.auto_command,
                working_slug=cast(Optional[str], metadata.channel_metadata.get("working_slug"))
                if metadata.channel_metadata
                else None,
                initiator_session_id=cast(Optional[str], metadata.channel_metadata.get("initiator_session_id"))
                if metadata.channel_metadata
                else None,
            )

        if event == "message":
            actor_id, actor_name, actor_avatar_url = CommandMapper._extract_actor_from_channel_metadata(
                metadata.channel_metadata,
                metadata.origin or InputOrigin.TELEGRAM.value,
            )
            return ProcessMessageCommand(
                session_id=session_id or "",
                text=" ".join(args),
                origin=metadata.origin or InputOrigin.TELEGRAM.value,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_avatar_url=actor_avatar_url,
            )

        if event == "agent":
            agent_name = args[0] if args else "claude"
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
    def map_redis_input(
        command_str: str,
        *,
        origin: str,
        session_id: Optional[str] = None,
        project_path: Optional[str] = None,
        title: Optional[str] = None,
        channel_metadata: Optional[Dict[str, object]] = None,
        launch_intent: Optional[SessionLaunchIntent | Dict[str, object]] = None,
        initiator: Optional[str] = None,
    ) -> InternalCommand:
        """Map Redis inbound message to internal command."""
        cmd_name, args = parse_command_string(command_str)
        if not origin:
            origin = InputOrigin.REDIS.value
        launch_intent_obj: Optional[SessionLaunchIntent] = None
        if isinstance(launch_intent, dict):
            launch_intent_obj = SessionLaunchIntent.from_dict(launch_intent)
        elif isinstance(launch_intent, SessionLaunchIntent):
            launch_intent_obj = launch_intent

        if cmd_name in _KEY_COMMANDS:
            return KeysCommand(
                session_id=session_id or "",
                key=cmd_name,
                args=args,
            )

        if cmd_name == "message":
            actor_id, actor_name, actor_avatar_url = CommandMapper._extract_actor_from_channel_metadata(
                channel_metadata,
                origin,
            )
            return ProcessMessageCommand(
                session_id=session_id or "",
                text=" ".join(args) if args else "",
                origin=origin,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_avatar_url=actor_avatar_url,
            )

        if cmd_name == "agent":
            agent_name = args[0] if args else "claude"
            return StartAgentCommand(
                session_id=session_id or "",
                agent_name=agent_name,
                args=args[1:] if len(args) > 1 else [],
            )

        if cmd_name in {"claude", "gemini", "codex"}:
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

        if cmd_name in {"claude_resume", "gemini_resume", "codex_resume"}:
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
                channel_metadata=channel_metadata,
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
    def map_api_input(
        command_name: str,
        payload: Dict[str, object],
        metadata: MessageMetadata,
    ) -> InternalCommand:
        """Map API input to internal command."""
        session_id = str(payload.get("session_id", ""))

        if command_name == "new_session":
            return CreateSessionCommand(
                project_path=metadata.project_path or "",
                title=metadata.title,
                subdir=metadata.subdir,
                origin=metadata.origin,
                channel_metadata=metadata.channel_metadata,
                launch_intent=metadata.launch_intent,
                auto_command=metadata.auto_command,
                session_metadata=metadata.session_metadata,
            )

        if command_name == "message":
            payload_actor_id_obj = payload.get("actor_id")
            payload_actor_name_obj = payload.get("actor_name")
            payload_actor_avatar_obj = payload.get("actor_avatar_url")
            payload_actor_id = str(payload_actor_id_obj).strip() if payload_actor_id_obj is not None else ""
            payload_actor_name = str(payload_actor_name_obj).strip() if payload_actor_name_obj is not None else ""
            payload_actor_avatar = str(payload_actor_avatar_obj).strip() if payload_actor_avatar_obj is not None else ""
            meta_actor_id, meta_actor_name, meta_actor_avatar = CommandMapper._extract_actor_from_channel_metadata(
                metadata.channel_metadata,
                metadata.origin or InputOrigin.API.value,
            )
            return ProcessMessageCommand(
                session_id=session_id,
                text=str(payload.get("text", "")),
                origin=metadata.origin or InputOrigin.API.value,
                actor_id=payload_actor_id or meta_actor_id,
                actor_name=payload_actor_name or meta_actor_name,
                actor_avatar_url=payload_actor_avatar or meta_actor_avatar,
            )

        if command_name == "keys":
            key = str(payload.get("key", ""))
            args = cast(List[str], payload.get("args", []))
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
            meta_actor_id, meta_actor_name, meta_actor_avatar = CommandMapper._extract_actor_from_channel_metadata(
                metadata.channel_metadata,
                metadata.origin or InputOrigin.API.value,
            )
            return HandleVoiceCommand(
                session_id=session_id,
                file_path=str(payload.get("file_path", "")),
                duration=cast(float | None, payload.get("duration")),
                message_id=cast(str | None, payload.get("message_id")),
                message_thread_id=cast(int | None, payload.get("message_thread_id")),
                origin=metadata.origin or InputOrigin.API.value,
                actor_id=payload_actor_id or meta_actor_id,
                actor_name=payload_actor_name or meta_actor_name,
                actor_avatar_url=payload_actor_avatar or meta_actor_avatar,
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
            args = cast(List[str], payload.get("args", []))
            agent_name = args[0] if args else "claude"
            return StartAgentCommand(
                session_id=session_id,
                agent_name=agent_name,
                args=args[1:] if len(args) > 1 else [],
            )

        if command_name == "agent_restart":
            args = cast(List[str], payload.get("args", []))
            agent_name = args[0] if args else None
            return RestartAgentCommand(
                session_id=session_id,
                agent_name=agent_name,
            )

        if command_name == "end_session":
            return CloseSessionCommand(session_id=session_id)

        raise ValueError(f"Unknown api command: {command_name}")
