"""MCP tool handler implementations for TeleClaude.

This module contains all teleclaude__* handler methods as a mixin class.
The TeleClaudeMCPServer inherits from this mixin to gain all handlers.
"""

# mypy: disable-error-code="misc"
# JSON parsing returns Any types - suppress misc errors for dynamic data handling

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Optional, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.context_selector import build_context_output
from teleclaude.core import command_handlers
from teleclaude.core.agents import normalize_agent_name
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata, ThinkingMode
from teleclaude.core.next_machine import next_maintain, next_prepare, next_work
from teleclaude.core.next_machine.core import (
    detect_circular_dependency,
    get_stash_entries,
    has_uncommitted_changes,
    load_roadmap,
    load_roadmap_deps,
    mark_phase,
    save_roadmap,
    sync_main_planning_to_all_worktrees,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import (
    close_link_for_member,
    create_or_reuse_direct_link,
    get_peer_members,
    register_listener,
    resolve_link_for_sender_target,
    unregister_listener,
)
from teleclaude.mcp.types import (
    ComputerInfo,
    DeployComputerResult,
    EndSessionResult,
    RemoteRequestError,
    RunAgentCommandResult,
    SendResultResult,
    SessionDataResult,
    SessionInfo,
    StartSessionResult,
    StopNotificationsResult,
    WidgetIndexEntry,
)
from teleclaude.transport.redis_transport import RedisTransport
from teleclaude.types import SystemStats
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    GetSessionDataCommand,
    ProcessMessageCommand,
    StartAgentCommand,
)
from teleclaude.utils.markdown import telegramify_markdown

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

# Max chars for session data response
MCP_SESSION_DATA_MAX_CHARS = 48000


def _snippet_ids_require_project_root(snippet_ids: list[str] | None) -> bool:
    """Return True when snippet IDs depend on local project-root resolution."""
    if not snippet_ids:
        return False

    for snippet_id in snippet_ids:
        if "/" not in snippet_id:
            continue
        prefix = snippet_id.split("/", 1)[0].strip().lower()
        if not prefix:
            continue
        # Only local project IDs require resolving a project root from cwd.
        # Cross-project IDs (manifest prefixes) are resolved downstream.
        if prefix == "project":
            return True
    return False


class MCPHandlersMixin:
    """Mixin providing all teleclaude__* MCP tool handlers.

    Requires the following attributes from the inheriting class:
    - client: AdapterClient
    - computer_name: str
    - _is_local_computer(computer: str) -> bool
    - _send_remote_request(...) -> dict
    - _register_listener_if_present(...) -> None
    - _track_background_task(...) -> None
    """

    # Type hints for attributes from TeleClaudeMCPServer
    client: "AdapterClient"
    computer_name: str

    def _normalize_thinking_mode(self, mode: str | ThinkingMode) -> ThinkingMode:
        """Ensure thinking_mode is a ThinkingMode enum member."""
        if isinstance(mode, ThinkingMode):
            return mode
        try:
            return ThinkingMode(str(mode))
        except ValueError:
            return ThinkingMode.SLOW

    def _is_local_computer(self, computer: str) -> bool:
        """Check if the target computer refers to the local machine."""
        raise NotImplementedError

    async def _send_remote_request(
        self,
        computer: str,
        command: str,
        timeout: float = 3.0,
        session_id: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> dict[str, object]:  # guard: loose-dict - MCP envelope
        """Send request to remote computer."""
        raise NotImplementedError

    async def _register_listener_if_present(self, target_session_id: str, caller_session_id: str | None = None) -> None:
        """Register caller as listener for target session."""
        raise NotImplementedError

    def _track_background_task(self, task: asyncio.Task[None], label: str) -> None:
        """Track background task."""
        raise NotImplementedError

    # =========================================================================
    # Computer & Project Tools
    # =========================================================================

    async def teleclaude__list_computers(self) -> list[ComputerInfo]:
        """List available computers including local and remote."""
        logger.debug("teleclaude__list_computers() called")

        # local_info is ComputerInfo dataclass
        local_info = await command_handlers.get_computer_info()
        local_computer: ComputerInfo = {
            "name": self.computer_name,
            "status": "local",
            "last_seen": datetime.now(timezone.utc),
            "user": local_info.user,
            "host": local_info.host,
            "role": local_info.role,
            "system_stats": local_info.system_stats,
            "tmux_binary": local_info.tmux_binary,
        }

        # discover_peers returns list of dicts
        remote_peers_raw = await self.client.discover_peers()
        remote_peers: list[ComputerInfo] = []
        for peer in remote_peers_raw:
            try:
                remote_peers.append(
                    {
                        "name": str(peer["name"]),
                        "status": str(peer["status"]),
                        "last_seen": cast(datetime, peer["last_seen"]),
                        "user": cast("str | None", peer.get("user")),
                        "host": cast("str | None", peer.get("host")),
                        "role": cast("str | None", peer.get("role")),
                        "system_stats": cast("SystemStats | None", peer.get("system_stats")),
                        "tmux_binary": cast("str | None", peer.get("tmux_binary")),
                    }
                )
            except Exception as exc:
                logger.warning("Skipping invalid peer payload: %s", exc)
                continue

        result = [local_computer] + remote_peers
        logger.debug("teleclaude__list_computers() returning %d computers", len(result))
        return result

    async def teleclaude__list_projects(self, computer: Optional[str] = None) -> list[dict[str, str]]:
        """List available projects on target computer, or all computers if None."""
        if computer is None:
            return await self._list_all_projects()
        if self._is_local_computer(computer):
            # returns ProjectInfo dataclasses
            projects = await command_handlers.list_projects()
            return [
                {"name": p.name, "desc": p.description or "", "path": p.path, "computer": self.computer_name}
                for p in projects
            ]
        return await self._list_remote_projects(computer)

    async def _list_remote_projects(self, computer: str) -> list[dict[str, str]]:
        """List projects from remote computer via Redis."""
        peers = await self.client.discover_peers()
        if not any(p["name"] == computer and p["status"] == "online" for p in peers):
            logger.warning("Computer %s not online, skipping list_projects", computer)
            return []

        try:
            envelope = await self._send_remote_request(computer, "list_projects", timeout=3.0)
            data = envelope.get("data", [])
            if not isinstance(data, list):
                logger.warning("Unexpected data format from %s: %s", computer, type(data).__name__)
                return []
            return list(data)
        except RemoteRequestError as e:
            logger.error("list_projects failed on %s: %s", computer, e.message)
            return []

    async def _list_all_projects(self) -> list[dict[str, str]]:
        """List projects from ALL computers (local + online remotes)."""
        # Get local projects
        projects = await command_handlers.list_projects()
        local_projects = [
            {"name": p.name, "desc": p.description or "", "path": p.path, "computer": self.computer_name}
            for p in projects
        ]

        # Get remote projects from all online computers
        redis_transport = self._get_redis_transport()
        if not redis_transport:
            return local_projects

        for computer_name in await redis_transport._get_online_computers():
            remote_projects = await self._list_remote_projects(computer_name)
            for project in remote_projects:
                project["computer"] = computer_name
            local_projects.extend(remote_projects)

        return local_projects

    # =========================================================================
    # Todo Tools
    # =========================================================================

    async def teleclaude__list_todos(
        self,
        computer: str,
        project_path: str,
        *,
        skip_peer_check: bool = False,
    ) -> list[dict[str, object]]:  # guard: loose-dict - Todo structure with mixed value types
        """List roadmap and todo-folder based work items for a project on target computer.

        Args:
            computer: Target computer name
            project_path: Absolute path to project directory
            skip_peer_check: If True, skip the peer online validation (use when caller
                already validated the computer is online, e.g., TUI after fetching projects)
        """
        if self._is_local_computer(computer):
            # returns TodoInfo dataclasses
            todos = await command_handlers.list_todos(project_path)
            return [t.to_dict() for t in todos]
        return await self._list_remote_todos(computer, project_path, skip_peer_check=skip_peer_check)

    async def _list_remote_todos(
        self,
        computer: str,
        project_path: str,
        *,
        skip_peer_check: bool = False,
    ) -> list[dict[str, object]]:  # guard: loose-dict - Todo structure with mixed value types
        """List todos from remote computer via Redis.

        Args:
            computer: Target computer name
            project_path: Absolute path to project directory
            skip_peer_check: If True, skip the peer online validation. Use when caller
                already validated (e.g., TUI fetches projects first which confirms online status).
        """
        # Validate peer is online unless caller explicitly skips (e.g., TUI already validated)
        if not skip_peer_check:
            peers = await self.client.discover_peers()
            if not any(p["name"] == computer and p["status"] == "online" for p in peers):
                logger.warning("Computer %s not online, skipping list_todos", computer)
                return []

        try:
            envelope = await self._send_remote_request(computer, "list_projects_with_todos", timeout=3.0)
            data = envelope.get("data", [])
            if not isinstance(data, list):
                logger.warning("Unexpected data format from %s: %s", computer, type(data).__name__)
                return []

            for project_obj in data:
                if not isinstance(project_obj, dict):
                    continue
                if str(project_obj.get("path", "")) != project_path:
                    continue
                todos_obj = project_obj.get("todos", [])
                if not isinstance(todos_obj, list):
                    logger.warning("Unexpected todos format from %s for %s", computer, project_path)
                    return []
                return [todo for todo in todos_obj if isinstance(todo, dict)]

            return []
        except RemoteRequestError as e:
            logger.warning("list_todos failed on %s: %s", computer, e.message)
            return []

    # =========================================================================
    # Session Tools
    # =========================================================================

    async def teleclaude__start_session(
        self,
        computer: str,
        project_path: str,
        title: str,
        message: str | None = None,
        caller_session_id: str | None = None,
        agent: str = "claude",
        thinking_mode: ThinkingMode = ThinkingMode.SLOW,
        direct: bool = False,
    ) -> StartSessionResult:
        """Create session on local or remote computer."""
        logger.debug(
            "teleclaude__start_session: computer=%s, is_local=%s, direct=%s",
            computer,
            self._is_local_computer(computer),
            direct,
        )
        if self._is_local_computer(computer):
            return await self._start_local_session(
                project_path, title, message, caller_session_id, agent, thinking_mode, direct
            )
        return await self._start_remote_session(
            computer, project_path, title, message, caller_session_id, agent, thinking_mode, direct
        )

    async def _start_local_session(
        self,
        project_path: str,
        title: str,
        message: str | None = None,
        caller_session_id: str | None = None,
        agent: str = "claude",
        thinking_mode: ThinkingMode = ThinkingMode.SLOW,
        direct: bool = False,
    ) -> StartSessionResult:
        """Create session on local computer directly via command service."""
        cmds = get_command_service()
        initiator_agent, initiator_mode = await self._get_caller_agent_info(caller_session_id)

        channel_metadata: dict[str, object] = {"target_computer": self.computer_name}  # guard: loose-dict
        if initiator_agent:
            channel_metadata["initiator_agent"] = initiator_agent
        if initiator_mode:
            channel_metadata["initiator_mode"] = initiator_mode
        if caller_session_id:
            channel_metadata["initiator_session_id"] = caller_session_id

        origin = await self._resolve_origin(caller_session_id)
        cmd = CreateSessionCommand(
            project_path=project_path,
            title=title,
            origin=origin,
            channel_metadata=channel_metadata,
            initiator_session_id=caller_session_id,
        )

        result = await cmds.create_session(cmd)

        session_id = self._extract_session_id(result)
        tmux_session_name = self._extract_tmux_session_name(result)
        if not session_id:
            error_msg = "Session creation failed"
            error_msg = str(result.get("error", "Unknown error"))
            return {"status": "error", "message": f"Local session creation failed: {error_msg}"}

        logger.info("Local session created: %s", session_id[:8])
        if not direct:
            await self._register_listener_if_present(session_id, caller_session_id)
        elif direct and caller_session_id:
            caller = await db.get_session(caller_session_id)
            caller_label = caller.title if caller and caller.title else caller_session_id
            caller_computer = caller.computer_name if caller else self.computer_name
            await create_or_reuse_direct_link(
                caller_session_id=caller_session_id,
                target_session_id=session_id,
                caller_name=caller_label,
                target_name=title,
                caller_computer=caller_computer,
                target_computer=self.computer_name,
            )

        # Start agent in background if message provided (None = skip agent start entirely)
        if message is not None:
            if direct and caller_session_id:
                announcement = (
                    f"[TeleClaude Link Established] - Another agent has established a direct link for conversation.\n"
                    f"Both your outputs will be shared automatically. You do not need to use send_message.\n"
                    f'To close the link: `teleclaude__send_message(computer="local", '
                    f'session_id="{caller_session_id}", message="<goodbye>", close_link=True)`\n'
                    f"A human may be observing silently — address the peer agent, not the user.\n\n"
                )
                message = announcement + message
            agent_args: list[str] = [message] if message else []
            thinking_mode = self._normalize_thinking_mode(thinking_mode)

            async def _run_agent_start() -> None:
                try:
                    start_cmd = StartAgentCommand(
                        session_id=session_id,
                        agent_name=agent,
                        thinking_mode=thinking_mode.value,
                        args=[thinking_mode.value] + agent_args,
                    )
                    await cmds.start_agent(start_cmd)
                except Exception as exc:
                    logger.error("Failed to dispatch StartAgentCommand for session %s: %s", session_id[:8], exc)

            self._track_background_task(asyncio.create_task(_run_agent_start()), f"agent_start:{session_id[:8]}")

        return {"session_id": session_id, "tmux_session_name": tmux_session_name, "status": "success"}

    async def _start_remote_session(
        self,
        computer: str,
        project_path: str,
        title: str,
        message: str | None = None,
        caller_session_id: str | None = None,
        agent: str = "claude",
        thinking_mode: ThinkingMode = ThinkingMode.SLOW,
        direct: bool = False,
    ) -> StartSessionResult:
        """Create session on remote computer via Redis transport."""
        if not await self._is_computer_online(computer):
            return {"status": "error", "message": f"Computer '{computer}' is offline"}

        initiator_agent, initiator_mode = await self._get_caller_agent_info(caller_session_id)
        channel_metadata: dict[str, object] = {"target_computer": self.computer_name}  # guard: loose-dict
        if initiator_agent:
            channel_metadata["initiator_agent"] = initiator_agent
        if initiator_mode:
            channel_metadata["initiator_mode"] = initiator_mode
        if caller_session_id:
            channel_metadata["initiator_session_id"] = caller_session_id

        metadata = MessageMetadata(
            project_path=project_path,
            title=title,
            channel_metadata=channel_metadata,
        )
        message_id = await self.client.send_request(computer_name=computer, command="/new_session", metadata=metadata)

        try:
            response_data = await self.client.read_response(message_id, timeout=5.0, target_computer=computer)
            envelope = json.loads(response_data.strip())

            if envelope.get("status") == "error":
                return {
                    "status": "error",
                    "message": f"Remote session creation failed: {envelope.get('error', 'Unknown')}",
                }

            data = envelope.get("data", {})
            remote_session_id = data.get("session_id") if isinstance(data, dict) else None

            if not remote_session_id:
                return {"status": "error", "message": "Remote did not return session_id"}

            logger.info("Remote session created: %s on %s", remote_session_id[:8], computer)

            if not direct:
                await self._register_remote_listener(str(remote_session_id), caller_session_id)

            # Start agent if message provided (None = skip agent start entirely)
            if message is not None:
                # Build command: /agent_start agent mode [prompt]
                thinking_mode = self._normalize_thinking_mode(thinking_mode)
                cmd_parts = ["/agent", agent, thinking_mode.value]
                if message:
                    cmd_parts.append(shlex.quote(message))
                await self.client.send_request(
                    computer_name=computer,
                    command=" ".join(cmd_parts),
                    metadata=MessageMetadata(),
                    session_id=str(remote_session_id),
                )

            return {"session_id": str(remote_session_id), "status": "success"}

        except TimeoutError:
            return {"status": "error", "message": "Timeout waiting for remote session creation"}
        except Exception as e:
            logger.error("Failed to create remote session: %s", e)
            return {"status": "error", "message": f"Failed to create remote session: {str(e)}"}

    async def teleclaude__list_sessions(
        self,
        computer: Optional[str] = "local",
        caller_session_id: str | None = None,
    ) -> list[SessionInfo]:
        """List sessions from local or remote computer(s)."""
        if computer is None:
            sessions = await self._list_all_sessions()
        elif self._is_local_computer(computer):
            sessions = await self._list_local_sessions()
        else:
            sessions = await self._list_remote_sessions(computer)

        return self._filter_spawned_sessions(sessions, caller_session_id)

    async def _list_local_sessions(self) -> list[SessionInfo]:
        """List sessions from local database directly."""
        # returns SessionSnapshot dataclasses
        sessions = await command_handlers.list_sessions()
        result: list[SessionInfo] = []
        for s in sessions:
            data = s.to_dict()
            data["computer"] = self.computer_name
            result.append(cast(SessionInfo, data))
        return result

    async def _list_remote_sessions(self, computer: str) -> list[SessionInfo]:
        """List sessions from a specific remote computer via Redis."""
        try:
            envelope = await self._send_remote_request(computer, "list_sessions", timeout=3.0)
            data = envelope.get("data", [])
            if not isinstance(data, list):
                logger.warning("Unexpected sessions data format from %s: %s", computer, type(data).__name__)
                return []
            sessions: list[SessionInfo] = cast(list[SessionInfo], data)
            for session in sessions:
                session["computer"] = computer
            return sessions
        except RemoteRequestError as e:
            logger.warning("Failed to get sessions from %s: %s", computer, e.message)
            return []

    async def _list_all_sessions(self) -> list[SessionInfo]:
        """List sessions from ALL computers."""
        all_sessions = await self._list_local_sessions()

        redis_transport = self._get_redis_transport()
        if not redis_transport:
            return all_sessions

        for computer_name in await redis_transport._get_online_computers():
            all_sessions.extend(await self._list_remote_sessions(computer_name))

        return all_sessions

    @staticmethod
    def _filter_spawned_sessions(
        sessions: list[SessionInfo],
        caller_session_id: str | None,
    ) -> list[SessionInfo]:
        if not caller_session_id:
            logger.debug("Missing caller_session_id; returning unfiltered sessions")
            return sessions
        return [session for session in sessions if session.get("initiator_session_id") == caller_session_id]

    async def teleclaude__send_message(
        self,
        computer: str,
        session_id: str,
        message: str,
        caller_session_id: str | None = None,
        direct: bool = False,
        close_link: bool = False,
    ) -> AsyncIterator[str]:
        """Send message to an AI agent session."""
        try:
            if close_link:
                if not caller_session_id:
                    yield "[Error: close_link requires caller_session_id]"
                    return
                closed_link_id = await close_link_for_member(
                    caller_session_id=caller_session_id,
                    target_session_id=session_id,
                )
                if not closed_link_id:
                    yield f"No active link found for caller {caller_session_id}."
                    return
                yield f"Closed shared link {closed_link_id} for caller {caller_session_id}."
                return

            if not direct:
                await self._register_listener_if_present(session_id, caller_session_id)

            origin = await self._resolve_origin(caller_session_id)
            actor_id, actor_name, actor_role, actor_agent, actor_computer = await self._resolve_mcp_actor(
                caller_session_id
            )

            if direct and caller_session_id:
                caller = await db.get_session(caller_session_id)
                target = await db.get_session(session_id)
                caller_label = caller.title if caller and caller.title else caller_session_id
                target_label = target.title if target and target.title else session_id
                caller_computer = caller.computer_name if caller else self.computer_name
                target_computer = self.computer_name if self._is_local_computer(computer) else computer
                link_ctx = await resolve_link_for_sender_target(
                    sender_session_id=caller_session_id,
                    target_session_id=session_id,
                )
                created = False
                if not link_ctx:
                    link, created = await create_or_reuse_direct_link(
                        caller_session_id=caller_session_id,
                        target_session_id=session_id,
                        caller_name=caller_label,
                        target_name=target_label,
                        caller_computer=caller_computer,
                        target_computer=target_computer,
                    )
                    link_ctx = await resolve_link_for_sender_target(
                        sender_session_id=caller_session_id,
                        target_session_id=session_id,
                    )
                    if not link_ctx:
                        raise RuntimeError("Direct link was created but could not be resolved")
                else:
                    link = link_ctx[0]

                _, members = link_ctx
                peers = await get_peer_members(link_id=link.link_id, sender_session_id=caller_session_id)
                if peers:
                    for peer in peers:
                        target_computer_name = (
                            peer.computer_name
                            if peer.computer_name and not self._is_local_computer(peer.computer_name)
                            else self.computer_name
                        )
                        await self._send_message_to_target(
                            computer=target_computer_name,
                            session_id=peer.session_id,
                            message=message,
                            origin=origin,
                            actor_id=actor_id,
                            actor_name=actor_name,
                            actor_role=actor_role,
                            actor_agent=actor_agent,
                            actor_computer=actor_computer,
                        )
                else:
                    # Fallback to explicit target delivery if no other peers are active.
                    await self._send_message_to_target(
                        computer=computer,
                        session_id=session_id,
                        message=message,
                        origin=origin,
                        actor_id=actor_id,
                        actor_name=actor_name,
                        actor_role=actor_role,
                        actor_agent=actor_agent,
                        actor_computer=actor_computer,
                    )

                link_state = "created" if created else "reused"
                peer_count = max(len(members) - 1, 1)
                yield (
                    f"Message sent to direct link {link.link_id} ({link_state}). "
                    f"Delivered to {peer_count} peer(s). Use teleclaude__get_session_data to check status."
                )
                return

            await self._send_message_to_target(
                computer=computer,
                session_id=session_id,
                message=message,
                origin=origin,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_role=actor_role,
                actor_agent=actor_agent,
                actor_computer=actor_computer,
            )
            yield f"Message sent to session {session_id} on {computer}. Use teleclaude__get_session_data to check status."
        except Exception as e:
            logger.error("Failed to send message to session %s: %s", session_id[:8], e)
            yield f"[Error: Failed to send message: {str(e)}]"

    async def _send_message_to_target(
        self,
        *,
        computer: str,
        session_id: str,
        message: str,
        origin: str,
        actor_id: str,
        actor_name: str,
        actor_role: str,
        actor_agent: str,
        actor_computer: str,
    ) -> None:
        if self._is_local_computer(computer):
            cmd = ProcessMessageCommand(
                session_id=session_id,
                text=message,
                origin=origin,
                actor_id=actor_id,
                actor_name=actor_name,
            )
            await get_command_service().process_message(cmd)
            return

        await self.client.send_request(
            computer_name=computer,
            command=f"message {shlex.quote(message)}",
            session_id=session_id,
            metadata=MessageMetadata(
                origin=origin,
                channel_metadata={
                    "actor_id": actor_id,
                    "actor_name": actor_name,
                    "actor_role": actor_role,
                    "actor_agent": actor_agent,
                    "actor_computer": actor_computer,
                },
            ),
        )

    async def teleclaude__run_agent_command(
        self,
        computer: str,
        command: str,
        args: str = "",
        project: str | None = None,
        agent: str = "claude",
        subfolder: str = "",
        caller_session_id: str | None = None,
        thinking_mode: ThinkingMode = ThinkingMode.SLOW,
    ) -> RunAgentCommandResult:
        """Run a slash command on an AI agent session."""
        if not command.startswith("/"):
            return {"status": "error", "message": "command must start with '/'"}
        normalized_cmd = command.lstrip("/")
        normalized_args = args.strip()
        full_command = f"/{normalized_cmd} {normalized_args}" if normalized_args else f"/{normalized_cmd}"

        if not project:
            return {"status": "error", "message": "project required"}

        title = full_command
        quoted_command = shlex.quote(full_command)

        thinking_mode = self._normalize_thinking_mode(thinking_mode)
        auto_command = f"agent_then_message {agent} {thinking_mode.value} {quoted_command}"
        normalized_subfolder = subfolder.strip().strip("/") if subfolder else ""

        # Worker commands require a slug as the first arg
        worker_commands = {"next-build", "next-review", "next-fix-review", "next-finalize"}
        working_slug: str | None = None
        if normalized_cmd in worker_commands:
            if not normalized_args:
                return {"status": "error", "message": f"/{normalized_cmd} requires a slug argument"}
            working_slug = normalized_args.split()[0]

        if self._is_local_computer(computer):
            return await self._start_local_session_with_auto_command(
                project, title, auto_command, caller_session_id, normalized_subfolder, working_slug
            )
        return await self._start_remote_session_with_auto_command(
            computer, project, title, auto_command, caller_session_id, normalized_subfolder, working_slug
        )

    async def _resolve_origin(self, caller_session_id: str | None) -> str:
        """Resolve origin for MCP requests."""
        _ = caller_session_id
        return InputOrigin.MCP.value

    async def _resolve_mcp_actor(self, caller_session_id: str | None) -> tuple[str, str, str, str, str]:
        """Resolve stable AI actor identity for MCP-origin messages."""
        if caller_session_id:
            caller = await db.get_session(caller_session_id)
            if caller:
                computer = (caller.computer_name or config.computer.name).strip() or config.computer.name
                human_email = (caller.human_email or "").strip()
                if human_email:
                    local_part = human_email.split("@", 1)[0] or human_email
                    actor_id = f"human:{human_email}"
                    actor_name = f"{local_part}@{computer}"
                    return (actor_id, actor_name, "human", "human", computer)

                actor_id = f"system:{computer}:{caller_session_id}"
                actor_name = f"system@{computer}"
                return (actor_id, actor_name, "system", "system", computer)

        computer = config.computer.name
        actor_id = f"system:{computer}:{caller_session_id or 'mcp'}"
        actor_name = f"system@{computer}"
        return (actor_id, actor_name, "system", "system", computer)

    async def _start_local_session_with_auto_command(
        self,
        project_path: str,
        title: str,
        auto_command: str,
        caller_session_id: str | None = None,
        subfolder: str = "",
        working_slug: str | None = None,
    ) -> RunAgentCommandResult:
        """Create local session and run auto_command via daemon."""
        initiator_agent, initiator_mode = await self._get_caller_agent_info(caller_session_id)

        channel_metadata: dict[str, object] = {"target_computer": self.computer_name}  # guard: loose-dict
        if initiator_agent:
            channel_metadata["initiator_agent"] = initiator_agent
        if initiator_mode:
            channel_metadata["initiator_mode"] = initiator_mode
        if subfolder:
            channel_metadata["subfolder"] = subfolder
        if working_slug:
            channel_metadata["working_slug"] = working_slug
        if caller_session_id:
            channel_metadata["initiator_session_id"] = caller_session_id

        origin = await self._resolve_origin(caller_session_id)
        cmd = CreateSessionCommand(
            project_path=project_path,
            title=title,
            subdir=subfolder,
            working_slug=working_slug,
            initiator_session_id=caller_session_id,
            origin=origin,
            channel_metadata=channel_metadata,
            auto_command=auto_command,
        )

        result = await get_command_service().create_session(cmd)

        session_id = self._extract_session_id(result)
        tmux_session_name = self._extract_tmux_session_name(result)
        if not session_id:
            error_msg = "Session creation failed"
            error_msg = str(result.get("error", "Unknown error"))
            return {"status": "error", "message": f"Local session creation failed: {error_msg}"}

        await self._register_listener_if_present(session_id, caller_session_id)
        return {"session_id": session_id, "tmux_session_name": tmux_session_name, "status": "success"}

    async def _start_remote_session_with_auto_command(
        self,
        computer: str,
        project_path: str,
        title: str,
        auto_command: str,
        caller_session_id: str | None = None,
        subfolder: str = "",
        working_slug: str | None = None,
    ) -> RunAgentCommandResult:
        """Create remote session and run auto_command via daemon."""
        if not await self._is_computer_online(computer):
            return {"status": "error", "message": f"Computer '{computer}' is offline"}

        initiator_agent, initiator_mode = await self._get_caller_agent_info(caller_session_id)

        channel_metadata: dict[str, object] = {"target_computer": self.computer_name}  # guard: loose-dict
        if initiator_agent:
            channel_metadata["initiator_agent"] = initiator_agent
        if initiator_mode:
            channel_metadata["initiator_mode"] = initiator_mode
        if subfolder:
            channel_metadata["subfolder"] = subfolder
        if working_slug:
            channel_metadata["working_slug"] = working_slug
        if caller_session_id:
            channel_metadata["initiator_session_id"] = caller_session_id

        origin = await self._resolve_origin(caller_session_id)
        metadata = MessageMetadata(
            origin=origin,
            project_path=project_path,
            title=title,
            auto_command=auto_command,
            channel_metadata=channel_metadata if channel_metadata else None,
        )

        message_id = await self.client.send_request(computer_name=computer, command="/new_session", metadata=metadata)

        try:
            response_data = await self.client.read_response(message_id, timeout=5.0, target_computer=computer)
            envelope = json.loads(response_data.strip())

            if envelope.get("status") == "error":
                return {
                    "status": "error",
                    "message": f"Remote session creation failed: {envelope.get('error', 'Unknown')}",
                }

            data = envelope.get("data", {})
            remote_session_id = data.get("session_id") if isinstance(data, dict) else None

            if not remote_session_id:
                return {"status": "error", "message": "Remote did not return session_id"}

            await self._register_listener_if_present(str(remote_session_id), caller_session_id)
            return {"session_id": remote_session_id, "status": "success"}

        except TimeoutError:
            return {"status": "error", "message": "Timeout waiting for remote session creation"}
        except Exception as e:
            logger.error("Failed to create remote session: %s", e)
            return {"status": "error", "message": f"Failed to create remote session: {str(e)}"}

    async def teleclaude__get_session_data(
        self,
        computer: str,
        session_id: str,
        since_timestamp: Optional[str] = None,
        until_timestamp: Optional[str] = None,
        tail_chars: int = 2000,
        caller_session_id: Optional[str] = None,
    ) -> SessionDataResult:
        """Get session data from local or remote computer."""
        # Only register a listener if there is no active direct link between caller and target.
        # Direct links use the fanout relay; registering a listener would duplicate stop notifications.
        link_exists = caller_session_id and await resolve_link_for_sender_target(
            sender_session_id=caller_session_id,
            target_session_id=session_id,
        )
        if not link_exists:
            await self._register_listener_if_present(session_id, caller_session_id)

        requested_tail_chars = tail_chars
        if tail_chars <= 0 or tail_chars > MCP_SESSION_DATA_MAX_CHARS:
            tail_chars = MCP_SESSION_DATA_MAX_CHARS

        if self._is_local_computer(computer):
            result = await self._get_local_session_data(session_id, since_timestamp, until_timestamp, tail_chars)
        else:
            result = await self._get_remote_session_data(
                computer, session_id, since_timestamp, until_timestamp, tail_chars
            )

        if result.get("status") != "success":
            return result

        messages = result.get("messages")
        if isinstance(messages, str):
            capped_messages, truncated = self._cap_session_messages(messages, MCP_SESSION_DATA_MAX_CHARS)
            result["messages"] = capped_messages
            if truncated:
                result["truncated"] = True
                result["max_chars"] = MCP_SESSION_DATA_MAX_CHARS
                result["requested_tail_chars"] = requested_tail_chars
                result["effective_tail_chars"] = tail_chars
                result["cap_notice"] = (
                    "Response capped to 48,000 chars. Use since_timestamp/until_timestamp to page through history."
                )

        result["captured_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return result

    @staticmethod
    def _cap_session_messages(messages: str, max_chars: int) -> tuple[str, bool]:
        """Ensure transcript output stays within max_chars."""
        if len(messages) <= max_chars:
            return messages, False
        notice = f"[...truncated to last {max_chars} chars; use since_timestamp/until_timestamp to page...]\n\n"
        if len(notice) >= max_chars:
            return notice[:max_chars], True
        return f"{notice}{messages[-(max_chars - len(notice)) :]}", True

    async def _get_local_session_data(
        self,
        session_id: str,
        since_timestamp: Optional[str] = None,
        until_timestamp: Optional[str] = None,
        tail_chars: int = 2000,
    ) -> SessionDataResult:
        """Get session data from local computer directly."""
        cmd = GetSessionDataCommand(
            session_id=session_id,
            since_timestamp=since_timestamp,
            until_timestamp=until_timestamp,
            tail_chars=tail_chars,
        )
        payload = await get_command_service().get_session_data(cmd)
        return cast(SessionDataResult, payload)

    async def _get_remote_session_data(
        self,
        computer: str,
        session_id: str,
        since_timestamp: Optional[str] = None,
        until_timestamp: Optional[str] = None,
        tail_chars: int = 2000,
    ) -> SessionDataResult:
        """Get session data from remote computer via Redis."""

        params = [since_timestamp or "-", until_timestamp or "-", str(tail_chars)]
        param_str = " ".join(params)
        command = f"/get_session_data {param_str}"

        try:
            envelope = await self._send_remote_request(computer, command, timeout=5.0, session_id=session_id)
            data = envelope.get("data")
            if isinstance(data, dict):
                return cast(SessionDataResult, data)
            return {"status": "error", "error": "Invalid response data format"}
        except RemoteRequestError as e:
            return {"status": "error", "error": e.message}

    async def teleclaude__stop_notifications(
        self,
        computer: str,
        session_id: str,
        caller_session_id: str | None = None,
    ) -> StopNotificationsResult:
        """Stop receiving notifications from a session without ending it."""
        if not caller_session_id:
            return {"status": "error", "message": "caller_session_id required"}

        if self._is_local_computer(computer):
            success = await unregister_listener(target_session_id=session_id, caller_session_id=caller_session_id)
            if success:
                return {"status": "success", "message": f"Stopped notifications from session {session_id}"}
            return {"status": "error", "message": f"No listener found for session {session_id}"}

        try:
            envelope = await self._send_remote_request(
                computer, f"stop_notifications {session_id} {caller_session_id}", timeout=3.0
            )
            return cast(StopNotificationsResult, envelope.get("data", {"status": "success", "message": "OK"}))
        except RemoteRequestError as e:
            return {"status": "error", "message": e.message}

    async def teleclaude__end_session(self, computer: str, session_id: str) -> EndSessionResult:
        """End a session gracefully (kill tmux, delete session, clean up resources)."""
        logger.info("teleclaude__end_session via MCP for session %s", session_id[:8])
        if self._is_local_computer(computer):
            cmd = CloseSessionCommand(session_id=session_id)
            return await command_handlers.end_session(cmd, self.client)

        try:
            envelope = await self._send_remote_request(computer, f"end_session {session_id}", timeout=5.0)
            return cast(EndSessionResult, envelope.get("data", {"status": "success", "message": "OK"}))
        except RemoteRequestError as e:
            return {"status": "error", "message": e.message}

    # =========================================================================
    # Deploy Tool
    # =========================================================================

    async def teleclaude__deploy(self, computers: list[str] | None = None) -> dict[str, DeployComputerResult]:
        """Deploy latest code to remote computers via Redis."""
        redis_transport = self._get_redis_transport()
        if not redis_transport:
            return {"_error": {"status": "error", "message": "Redis adapter not available"}}

        all_peers = await redis_transport.discover_peers()
        available = [peer.name for peer in all_peers if peer.name != self.computer_name]
        available_set = set(available)

        requested = [str(name) for name in (computers or [])]
        targets = list(available) if not requested else [name for name in requested if name in available_set]

        if requested:
            seen: set[str] = set()
            targets = [name for name in targets if not (name in seen or seen.add(name))]

        results: dict[str, DeployComputerResult] = {}

        if requested:
            for name in requested:
                if name == self.computer_name:
                    results[name] = {"status": "skipped", "message": "Skipping self deployment"}
                elif name not in available_set:
                    results[name] = {"status": "error", "message": "Unknown or offline computer"}

        if not targets:
            return {"_message": {"status": "success", "message": "No remote computers to deploy to"}}

        logger.info("Deploying to computers: %s", targets)

        for computer in targets:
            await redis_transport.send_system_command(
                computer_name=computer, command="deploy", args={"verify_health": True}
            )

        for computer in targets:
            for _ in range(60):
                status = await redis_transport.get_system_command_status(computer_name=computer, command="deploy")
                status_str = str(status.get("status", "unknown"))
                if status_str in ("deployed", "error"):
                    results[computer] = cast(DeployComputerResult, status)
                    break
                await asyncio.sleep(1)
            else:
                results[computer] = {"status": "timeout", "message": "Deployment timed out after 60 seconds"}

        return results

    # =========================================================================
    # File Tools
    # =========================================================================

    async def teleclaude__send_file(self, session_id: str, file_path: str, caption: str | None = None) -> str:
        """Send file via session's UI adapters."""
        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"
        if not path.is_file():
            return f"Error: Not a file: {file_path}"

        session = await db.get_session(session_id)
        if not session:
            return f"Error: Session {session_id} not found"

        try:
            message_id = await self.client.send_file(session=session, file_path=str(path.absolute()), caption=caption)
            return f"File sent successfully: {path.name} (message_id: {message_id})"
        except Exception as e:
            logger.error("Failed to send file %s: %s", file_path, e)
            return f"Error sending file: {e}"

    async def teleclaude__send_result(
        self, session_id: str, content: str, output_format: str = "markdown"
    ) -> SendResultResult:
        """Send formatted result to user as separate message."""
        if not content or not content.strip():
            return {"status": "error", "message": "Content cannot be empty"}

        session = await db.get_session(session_id)
        if not session:
            return {"status": "error", "message": f"Session {session_id} not found"}

        if output_format == "html":
            formatted_content = content
            parse_mode = "HTML"
        else:
            formatted_content = telegramify_markdown(content)
            parse_mode = "MarkdownV2"

        if len(formatted_content) > 4096:
            formatted_content = formatted_content[:4090] + "\n..."

        metadata = MessageMetadata(parse_mode=parse_mode)

        try:
            # MCP send_result creates persistent messages (AI responses to user)
            message_id = await self.client.send_message(
                session=session, text=formatted_content, metadata=metadata, ephemeral=False
            )
            return {"status": "success", "message_id": message_id}
        except Exception as e:
            logger.warning("MarkdownV2 send failed, retrying with default formatting: %s", e)
            try:
                message_id = await self.client.send_message(
                    session=session, text=content[:4096], metadata=MessageMetadata(), ephemeral=False
                )
                return {
                    "status": "success",
                    "message_id": message_id,
                    "warning": "Sent as plain text due to formatting error",
                }
            except Exception as fallback_error:
                return {"status": "error", "message": f"Failed to send result: {fallback_error}"}

    async def teleclaude__get_context(
        self,
        areas: list[str] | None = None,
        snippet_ids: list[str] | None = None,
        baseline_only: bool | None = None,
        include_third_party: bool | None = None,
        domains: list[str] | None = None,
        list_projects: bool | None = None,
        projects: list[str] | None = None,
        project_root: str | None = None,
        cwd: str | None = None,
        caller_session_id: str | None = None,
    ) -> str:
        """Select and return relevant snippet context for the current session.

        Phase 1: Call with areas filter (or no params) to get index.
        Phase 2: Call with snippet_ids to get full content.
        """
        # Determine effective project root: explicit > cwd > default
        effective_root = project_root or cwd
        if not effective_root:
            effective_root = str(config.computer.default_working_dir)
        if areas is None:
            areas = []
        if _snippet_ids_require_project_root(snippet_ids):
            root = Path(effective_root).expanduser().resolve()
            while True:
                if (root / "teleclaude.yml").exists():
                    effective_root = str(root)
                    break
                if root.parent == root:
                    return (
                        "ERROR: NO_PROJECT_ROOT\nProject snippets require a project root with teleclaude.yml and docs/."
                    )
                root = root.parent
        test_agent = None
        test_mode = None
        test_request = None
        test_csv_path = None
        if os.getenv("TELECLAUDE_GET_CONTEXT_TESTING") and caller_session_id:
            session = await db.get_session(caller_session_id)
            if session:
                test_agent = session.active_agent
                test_mode = session.thinking_mode
                test_request = session.last_message_sent
                test_csv_path = str(
                    Path(effective_root).expanduser().resolve() / ".agents" / "tests" / "runs" / "get-context.csv"
                )
        # Resolve caller role for visibility filtering.
        caller_role = "admin"
        human_role: str | None = None
        if caller_session_id:
            caller_session = await db.get_session(caller_session_id)
            if caller_session:
                caller_role = (caller_session.user_role or "admin").strip().lower() or "admin"
                human_role = caller_session.human_role

        resolved_root = Path(effective_root)
        return build_context_output(
            areas=areas,
            project_root=resolved_root,
            snippet_ids=snippet_ids,
            baseline_only=bool(baseline_only),
            include_third_party=bool(include_third_party),
            domains=domains,
            list_projects=bool(list_projects),
            projects=projects,
            caller_role=caller_role,
            human_role=human_role,
            test_agent=test_agent,
            test_mode=test_mode,
            test_request=test_request,
            test_csv_path=test_csv_path,
        )

    # =========================================================================
    # Workflow Tools (Next Machine)
    # =========================================================================

    async def teleclaude__next_prepare(self, slug: str | None = None, cwd: str | None = None, hitl: bool = True) -> str:
        """Phase A state machine: Check preparation state and return instructions."""
        if not cwd:
            cwd = str(config.computer.default_working_dir)
        return await next_prepare(db, slug, cwd, hitl)

    async def teleclaude__next_work(
        self, slug: str | None = None, cwd: str | None = None, caller_session_id: str | None = None
    ) -> str:
        """Phase B: Execute build/review/fix cycle on prepared work items."""
        if not cwd:
            return "ERROR: NO_CWD\nWorking directory not provided. This should be auto-injected by MCP wrapper."
        return await next_work(db, slug, cwd, caller_session_id)

    async def teleclaude__next_maintain(self, cwd: str | None = None) -> str:
        """Phase D: Execute maintenance steps (stub)."""
        if not cwd:
            return "ERROR: NO_CWD\nWorking directory not provided. This should be auto-injected by MCP wrapper."
        return await next_maintain(db, cwd)

    async def teleclaude__mark_phase(self, slug: str, phase: str, status: str, cwd: str | None = None) -> str:
        """Mark a work phase as complete/approved in state.yaml."""
        if not cwd:
            return "ERROR: NO_CWD\nWorking directory not provided."
        if phase not in ("build", "review"):
            return f"ERROR: Invalid phase '{phase}'. Must be 'build' or 'review'."
        if status not in ("pending", "started", "complete", "approved", "changes_requested"):
            return f"ERROR: Invalid status '{status}'. Must be 'pending', 'started', 'complete', 'approved', or 'changes_requested'."

        worktree_cwd = str(Path(cwd) / "trees" / slug)
        if not Path(worktree_cwd).exists():
            return f"ERROR: Worktree not found at {worktree_cwd}"

        terminal_statuses = ("complete", "approved")
        if status in terminal_statuses:
            if has_uncommitted_changes(cwd, slug):
                return (
                    f"ERROR: UNCOMMITTED_CHANGES\nWorktree trees/{slug} has uncommitted changes. "
                    "Please commit them before marking phase as complete."
                )
            stash_entries = get_stash_entries(cwd)
            if stash_entries:
                noun = "entry" if len(stash_entries) == 1 else "entries"
                return (
                    "ERROR: STASH_DEBT\n"
                    f"Repository has {len(stash_entries)} git stash {noun}. "
                    "Clear stash entries before marking phases complete."
                )

        updated_state = mark_phase(worktree_cwd, slug, phase, status)
        return f"OK: {slug} state updated - {phase}: {status}\nCurrent state: {updated_state}"

    async def teleclaude__set_dependencies(self, slug: str, after: list[str], cwd: str | None = None) -> str:
        """Set dependencies for a work item."""
        if not cwd:
            return "ERROR: NO_CWD\nWorking directory not provided."

        slug_pattern = re.compile(r"^[a-z0-9-]+$")
        if not slug_pattern.match(slug):
            return f"ERROR: INVALID_SLUG\nSlug '{slug}' must be lowercase alphanumeric with hyphens only."

        for dep in after:
            if not slug_pattern.match(dep):
                return f"ERROR: INVALID_DEP\nDependency '{dep}' must be lowercase alphanumeric with hyphens only."

        if slug in after:
            return f"ERROR: SELF_REFERENCE\nSlug '{slug}' cannot depend on itself."

        entries = load_roadmap(cwd)
        if not entries:
            return "ERROR: NO_ROADMAP\ntodos/roadmap.yaml not found."

        roadmap_slugs = {e.slug for e in entries}

        if slug not in roadmap_slugs:
            return f"ERROR: SLUG_NOT_FOUND\nSlug '{slug}' not found in roadmap.yaml."

        for dep in after:
            if dep not in roadmap_slugs:
                return f"ERROR: DEP_NOT_FOUND\nDependency '{dep}' not found in roadmap.yaml."

        deps = load_roadmap_deps(cwd)
        cycle = detect_circular_dependency(deps, slug, after)
        if cycle:
            cycle_str = " -> ".join(cycle)
            return f"ERROR: CIRCULAR_DEP\nCircular dependency detected: {cycle_str}"

        # Update the matching entry's after field
        for entry in entries:
            if entry.slug == slug:
                entry.after = after
                break

        save_roadmap(cwd, entries)
        sync_main_planning_to_all_worktrees(cwd)
        return (
            f"OK: Dependencies set for '{slug}': {', '.join(after)}"
            if after
            else f"OK: Dependencies cleared for '{slug}'"
        )

    async def teleclaude__mark_agent_status(
        self,
        agent: str,
        reason: str | None = None,
        unavailable_until: str | None = None,
        clear: bool = False,
        status: str | None = None,
    ) -> str:
        """Set agent dispatch status (available/unavailable/degraded)."""
        agent_name = normalize_agent_name(agent)
        if clear:
            await db.mark_agent_available(agent_name)
            return f"OK: {agent_name} marked available"
        normalized_status = (status or "unavailable").strip().lower()
        if normalized_status not in {"available", "unavailable", "degraded"}:
            return "ERROR: status must be one of: available, unavailable, degraded"
        if normalized_status == "available":
            await db.mark_agent_available(agent_name)
            return f"OK: {agent_name} marked available"
        if normalized_status == "degraded":
            degrade_reason = reason or "degraded"
            await db.mark_agent_degraded(agent_name, degrade_reason)
            return f"OK: {agent_name} marked degraded ({degrade_reason})"
        if not reason:
            return "ERROR: reason is required unless clear is true"
        if not unavailable_until:
            unavailable_until = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        await db.mark_agent_unavailable(agent_name, unavailable_until, reason)
        return f"OK: {agent_name} marked unavailable until {unavailable_until} ({reason})"

    async def teleclaude__mark_agent_unavailable(
        self,
        agent: str,
        reason: str | None = None,
        unavailable_until: str | None = None,
        clear: bool = False,
        status: str | None = None,
    ) -> str:
        """Backward-compatible alias; use teleclaude__mark_agent_status."""
        return await self.teleclaude__mark_agent_status(agent, reason, unavailable_until, clear, status)

    # =========================================================================
    # Channel Tools
    # =========================================================================

    async def teleclaude__publish(
        self,
        channel: str,
        payload: dict[str, object],  # guard: loose-dict - Channel payload is arbitrary user JSON
    ) -> str:
        """Publish a message to a Redis Stream channel."""
        from teleclaude.channels.publisher import publish

        transport = self._get_redis_transport()
        if not transport:
            return "Error: Redis transport not available"
        redis_client = await transport._get_redis()
        msg_id = await publish(redis_client, channel, payload)
        return f"Published to {channel}: {msg_id}"

    async def teleclaude__channels_list(self, project: str | None = None) -> Sequence[object]:
        """List active internal Redis Stream channels."""
        from teleclaude.channels.publisher import list_channels

        transport = self._get_redis_transport()
        if not transport:
            return []
        redis_client = await transport._get_redis()
        return await list_channels(redis_client, project)

    # =========================================================================
    # Widget Tools
    # =========================================================================

    async def teleclaude__render_widget(
        self,
        session_id: str,
        data: dict[str, object],  # guard: loose-dict - Widget expression blob
    ) -> str:
        """Render a widget expression: generate text summary, fanout to adapters, store named widgets."""
        session = await db.get_session(session_id)
        if not session:
            return f"Error: Session {session_id} not found"

        title = str(data.get("title", ""))
        sections = data.get("sections", [])
        footer = str(data.get("footer", ""))
        widget_name = data.get("name")

        if not isinstance(sections, list):
            return "Error: sections must be an array"

        # Generate text summary by walking sections
        summary_parts: list[str] = []
        if title:
            summary_parts.append(f"**{title}**\n")

        file_paths: list[str] = []

        for section in sections:
            if not isinstance(section, dict):
                continue
            section_type = str(section.get("type", ""))
            label = section.get("label")
            if label:
                summary_parts.append(f"_{label}_")

            if section_type == "text":
                content = str(section.get("content", ""))
                if content:
                    summary_parts.append(content)
            elif section_type == "input":
                fields = section.get("fields", [])
                if isinstance(fields, list):
                    field_names = []
                    for f in fields:
                        if isinstance(f, dict):
                            field_names.append(str(f.get("label", f.get("name", "field"))))
                    if field_names:
                        summary_parts.append(f"Form fields: {', '.join(field_names)}")
            elif section_type == "actions":
                buttons = section.get("buttons", [])
                if isinstance(buttons, list):
                    btn_labels = []
                    for b in buttons:
                        if isinstance(b, dict):
                            btn_labels.append(str(b.get("label", "button")))
                    if btn_labels:
                        summary_parts.append(f"Actions: [{'] ['.join(btn_labels)}]")
            elif section_type == "image":
                src = str(section.get("src", ""))
                alt = str(section.get("alt", "image"))
                summary_parts.append(f"[Image: {alt}]")
                if src:
                    file_paths.append(src)
            elif section_type == "table":
                headers = section.get("headers", [])
                rows = section.get("rows", [])
                if isinstance(headers, list) and isinstance(rows, list):
                    summary_parts.append(f"Table: {len(headers)} columns, {len(rows)} rows")
            elif section_type == "file":
                path = str(section.get("path", ""))
                file_label = str(section.get("label", path))
                summary_parts.append(f"File: {file_label}")
                if path:
                    file_paths.append(path)
            elif section_type == "code":
                lang = str(section.get("language", ""))
                content = str(section.get("content", ""))
                lang_label = f" ({lang})" if lang else ""
                preview = content[:100] + "..." if len(content) > 100 else content
                summary_parts.append(f"Code{lang_label}:\n```\n{preview}\n```")
            elif section_type == "divider":
                summary_parts.append("---")
            else:
                summary_parts.append(f"[{section_type}: {json.dumps(section)[:80]}]")

        if footer:
            summary_parts.append(f"\n{footer}")

        text_summary = "\n".join(summary_parts)

        # Send text summary to non-web adapters (Telegram, terminal)
        try:
            await self.client.send_message(
                session=session,
                text=telegramify_markdown(text_summary),
                metadata=MessageMetadata(parse_mode="MarkdownV2"),
                ephemeral=True,
            )
        except Exception as e:
            logger.warning("Widget text summary send failed, retrying plain: %s", e)
            try:
                await self.client.send_message(
                    session=session,
                    text=text_summary,
                    metadata=MessageMetadata(),
                    ephemeral=True,
                )
            except Exception as fallback_err:
                logger.error("Widget text summary send failed: %s", fallback_err)

        # Send files for image/file sections
        from teleclaude.core.session_utils import get_session_output_dir

        workspace = get_session_output_dir(session_id)
        for rel_path in file_paths:
            abs_path = workspace / rel_path
            if abs_path.exists() and abs_path.is_file():
                try:
                    await self.client.send_file(
                        session=session,
                        file_path=str(abs_path),
                        caption=rel_path,
                    )
                except Exception as e:
                    logger.warning("Widget file send failed for %s: %s", rel_path, e)

        # Library collection: store named widgets
        if widget_name and isinstance(widget_name, str):
            try:
                await self._store_widget(session, str(widget_name), data)
            except Exception as e:
                logger.warning("Widget library storage failed for %s: %s", widget_name, e)

        return text_summary

    async def _store_widget(
        self,
        session: object,
        name: str,
        data: dict[str, object],  # guard: loose-dict - Widget expression blob
    ) -> None:
        """Store a named widget to the widgets library."""
        # Determine widgets directory (project-scoped if session has project_path)
        widgets_dir: Path | None = None
        if hasattr(session, "project_path") and getattr(session, "project_path"):
            project_path = Path(str(getattr(session, "project_path")))
            if project_path.is_dir():
                widgets_dir = project_path / "widgets"
        if not widgets_dir:
            widgets_dir = Path.home() / ".teleclaude" / "widgets"

        widgets_dir.mkdir(parents=True, exist_ok=True)

        # Write widget JSON
        widget_path = widgets_dir / f"{name}.json"
        widget_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Update index
        index_path = widgets_dir / "index.json"
        index: list[WidgetIndexEntry] = []
        if index_path.exists():
            try:
                raw = json.loads(index_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    index = [WidgetIndexEntry(**e) for e in raw if isinstance(e, dict)]
            except (json.JSONDecodeError, OSError):
                index = []

        # Update or add entry
        now = datetime.now(timezone.utc).isoformat()
        entry = WidgetIndexEntry(
            name=name,
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            path=str(widget_path),
            updated_at=now,
        )
        # Preserve renderer/types fields if they exist in existing entry
        existing = next((e for e in index if e.get("name") == name), None)
        if existing:
            renderer = existing.get("renderer")
            types_ref = existing.get("types")
            if renderer:
                entry["renderer"] = renderer
            if types_ref:
                entry["types"] = types_ref
            index = [e for e in index if e.get("name") != name]
        index.append(entry)

        index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
        logger.info("Widget stored: %s -> %s", name, widget_path)

    # =========================================================================
    # Escalation
    # =========================================================================

    async def teleclaude__escalate(
        self,
        customer_name: str,
        reason: str,
        context_summary: str | None = None,
        caller_session_id: str | None = None,
    ) -> str:
        """Escalate a customer conversation to an admin.

        Creates a Discord thread in the escalation forum, notifies admins,
        and activates relay mode on the calling session.
        """
        if not caller_session_id:
            return "Error: Could not resolve calling session"

        session = await db.get_session(caller_session_id)
        if not session:
            return f"Error: Session {caller_session_id} not found"

        if session.human_role != "customer":
            return "Error: Escalation is only available in customer sessions"

        # Resolve Discord adapter
        from teleclaude.adapters.discord_adapter import DiscordAdapter

        discord_adapter: DiscordAdapter | None = None
        for adapter in self.client.adapters.values():
            if isinstance(adapter, DiscordAdapter):
                discord_adapter = adapter
                break
        if not discord_adapter:
            return "Error: Discord adapter not available"

        try:
            thread_id = await discord_adapter.create_escalation_thread(
                customer_name=customer_name,
                reason=reason,
                context_summary=context_summary,
                session_id=session.session_id,
            )

            now = datetime.now(timezone.utc)
            await db.update_session(
                session.session_id,
                relay_status="active",
                relay_discord_channel_id=str(thread_id),
                relay_started_at=now.isoformat(),
            )
        except Exception as e:
            logger.error("Escalation failed: %s", e)
            return f"Error creating escalation: {e}"

        logger.info(
            "Escalation created: session=%s thread=%s customer=%s",
            session.session_id[:8],
            thread_id,
            customer_name,
        )
        return (
            f"Escalation thread created in escalation forum (thread {thread_id}). "
            "Admins subscribed to the channel will be notified by Discord. Relay is now active."
        )

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _get_caller_agent_info(self, caller_session_id: str | None) -> tuple[str | None, str | None]:
        """Get caller's agent and mode info for AI-to-AI title format."""
        if not caller_session_id:
            return None, None
        caller_session = await db.get_session(caller_session_id)
        if caller_session:
            return caller_session.active_agent, caller_session.thinking_mode
        return None, None

    def _extract_session_id(self, result: object) -> str | None:
        """Extract session_id from command result envelope."""
        if not isinstance(result, dict):
            return None
        session_id = result.get("session_id")
        if session_id is None and result.get("status") == "success":
            data: object = result.get("data", {})
            if isinstance(data, dict):
                session_id = data.get("session_id")
        return str(session_id) if session_id is not None else None

    def _extract_tmux_session_name(self, result: object) -> str | None:
        """Extract tmux_session_name from command result envelope."""
        if not isinstance(result, dict):
            return None
        tmux_name = result.get("tmux_session_name")
        if tmux_name is None and result.get("status") == "success":
            data: object = result.get("data", {})
            if isinstance(data, dict):
                tmux_name = data.get("tmux_session_name")
        return str(tmux_name) if tmux_name is not None else None

    async def _is_computer_online(self, computer: str) -> bool:
        """Check if a remote computer is online."""
        peers = await self.client.discover_peers()
        return any(p["name"] == computer and p["status"] == "online" for p in peers)

    def _get_redis_transport(self) -> RedisTransport | None:
        """Get Redis transport if available."""
        redis_transport_base = self.client.adapters.get("redis")
        if redis_transport_base and isinstance(redis_transport_base, RedisTransport):
            return redis_transport_base
        logger.warning("Redis transport not available")
        return None

    async def _register_remote_listener(self, remote_session_id: str, caller_session_id: str | None) -> None:
        """Register listener for remote session stop events."""
        if not caller_session_id:
            return

        logger.debug(
            "Attempting listener registration: caller=%s, target=%s", caller_session_id[:8], remote_session_id[:8]
        )

        try:
            caller_session = await db.get_session(caller_session_id)
            if caller_session:
                await register_listener(
                    target_session_id=str(remote_session_id),
                    caller_session_id=caller_session_id,
                    caller_tmux_session=caller_session.tmux_session_name,
                )
                logger.info(
                    "Listener registered: caller=%s -> target=%s (tmux=%s)",
                    caller_session_id[:8],
                    remote_session_id[:8],
                    caller_session.tmux_session_name,
                )
            else:
                logger.warning("Cannot register listener: caller session %s not found", caller_session_id[:8])
        except RuntimeError as e:
            logger.warning("Database not initialized for listener registration: %s", e)
