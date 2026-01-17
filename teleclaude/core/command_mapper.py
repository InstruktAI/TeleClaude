"""Mapper module to normalize transport inputs into internal command models."""

import base64
from typing import Dict, List, Optional, cast

from teleclaude.core.events import AgentHookEvents, parse_command_string
from teleclaude.core.models import MessageMetadata, SessionLaunchIntent
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    InternalCommand,
    ResumeAgentCommand,
    SendMessageCommand,
    StartAgentCommand,
    SystemCommand,
)


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
        if event == "new_session":
            return CreateSessionCommand(
                project_path=metadata.project_path or "",
                title=metadata.title or (args[0] if args else None),
                subdir=metadata.subdir,
                adapter_type="telegram",
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

        if event == "exit":
            return CloseSessionCommand(session_id=session_id or "")

        # Fallback for other commands
        return SystemCommand(command=event, args=args)

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

        if cmd_name == "stop_notification":
            target_session_id = args[0] if len(args) > 0 else ""
            source_computer = args[1] if len(args) > 1 else "unknown"
            title_b64 = args[2] if len(args) > 2 else None
            resolved_title = None
            if title_b64:
                try:
                    resolved_title = base64.b64decode(title_b64).decode()
                except Exception:
                    pass

            # Map to AGENT_EVENT stop
            event_data = {
                "session_id": target_session_id,
                "source_computer": source_computer,
            }
            if resolved_title:
                event_data["title"] = resolved_title

            return SystemCommand(
                command="agent_event",
                args=[],
                data={
                    "session_id": target_session_id,
                    "event_type": AgentHookEvents.AGENT_STOP,
                    "data": event_data,
                },
            )

        if cmd_name == "input_notification":
            target_session_id = args[0] if len(args) > 0 else ""
            source_computer = args[1] if len(args) > 1 else "unknown"
            message_b64 = args[2] if len(args) > 2 else ""
            message = ""
            try:
                message = base64.b64decode(message_b64).decode()
            except Exception:
                pass

            return SystemCommand(
                command="agent_event",
                args=[],
                data={
                    "session_id": target_session_id,
                    "event_type": AgentHookEvents.AGENT_NOTIFICATION,
                    "data": {
                        "session_id": target_session_id,
                        "source_computer": source_computer,
                        "message": message,
                    },
                },
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
                adapter_type="redis",
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

        if cmd_name == "end_session":
            return CloseSessionCommand(session_id=session_id or "")

        # Query/list commands don't have specific InternalCommand types
        # They use SystemCommand but with the proper command name
        # The command name will map to the correct TeleClaudeEvent in handle_command
        return SystemCommand(command=cmd_name or "unknown", args=args)

    @staticmethod
    def map_rest_input(
        event: str,
        payload: Dict[str, object],
        metadata: MessageMetadata,
    ) -> InternalCommand:
        """Map REST API input to internal command."""
        session_id = str(payload.get("session_id", ""))

        if event == "new_session":
            return CreateSessionCommand(
                project_path=metadata.project_path or "",
                title=metadata.title,
                subdir=metadata.subdir,
                adapter_type="rest",
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
            return SystemCommand(
                command="agent_restart",
                args=cast(List[str], payload.get("args", [])),
                session_id=session_id,
            )

        if event == "end_session":
            return CloseSessionCommand(session_id=session_id)

        if event == "get_session_data":
            return SystemCommand(
                command="get_session_data",
                args=cast(List[str], payload.get("args", [])),
                session_id=session_id,
            )

        return SystemCommand(command=event, args=cast(List[str], payload.get("args", [])))
