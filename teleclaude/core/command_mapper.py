"""Mapper module to normalize transport inputs into internal command models."""

from typing import Dict, List, Optional, cast

from teleclaude.core.events import parse_command_string
from teleclaude.core.models import MessageMetadata, SessionLaunchIntent
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    GetSessionDataCommand,
    InternalCommand,
    KeysCommand,
    RestartAgentCommand,
    ResumeAgentCommand,
    SendMessageCommand,
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
                origin="telegram",
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
            return SendMessageCommand(
                session_id=session_id or "",
                text=" ".join(args),
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
        session_id: Optional[str] = None,
        project_path: Optional[str] = None,
        title: Optional[str] = None,
        channel_metadata: Optional[Dict[str, object]] = None,
        launch_intent: Optional[SessionLaunchIntent | Dict[str, object]] = None,
    ) -> InternalCommand:
        """Map Redis inbound message to internal command."""
        cmd_name, args = parse_command_string(command_str)
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
            return SendMessageCommand(
                session_id=session_id or "",
                text=" ".join(args) if args else "",
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
                origin="redis",
                channel_metadata=channel_metadata,
                launch_intent=launch_intent_obj,
            )

        if cmd_name == "message":
            return SendMessageCommand(
                session_id=session_id or "",
                text=" ".join(args),
            )

        if cmd_name in ["claude", "gemini", "codex"]:
            return StartAgentCommand(
                session_id=session_id or "",
                agent_name=cmd_name,
                args=args,
            )

        if cmd_name in ["claude_resume", "gemini_resume", "codex_resume"]:
            agent_name = cmd_name.replace("_resume", "")
            return ResumeAgentCommand(
                session_id=session_id or "",
                agent_name=agent_name,
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
        event: str,
        payload: Dict[str, object],
        metadata: MessageMetadata,
    ) -> InternalCommand:
        """Map API input to internal command."""
        session_id = str(payload.get("session_id", ""))

        if event == "new_session":
            return CreateSessionCommand(
                project_path=metadata.project_path or "",
                title=metadata.title,
                subdir=metadata.subdir,
                origin="api",
                channel_metadata=metadata.channel_metadata,
                launch_intent=metadata.launch_intent,
                auto_command=metadata.auto_command,
            )

        if event == "message":
            return SendMessageCommand(
                session_id=session_id,
                text=str(payload.get("text", "")),
            )

        if event == "agent":
            args = cast(List[str], payload.get("args", []))
            agent_name = args[0] if args else "claude"
            return StartAgentCommand(
                session_id=session_id,
                agent_name=agent_name,
                args=args[1:] if len(args) > 1 else [],
            )

        if event == "agent_restart":
            args = cast(List[str], payload.get("args", []))
            agent_name = args[0] if args else None
            return RestartAgentCommand(
                session_id=session_id,
                agent_name=agent_name,
            )

        if event == "end_session":
            return CloseSessionCommand(session_id=session_id)

        raise ValueError(f"Unknown api command: {event}")
