"""Remote data pull operations for RedisTransport (sessions, projects, todos)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.models import JsonDict, MessageMetadata, ProjectInfo, SessionSnapshot, TodoInfo

logger = get_logger(__name__)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache


class _PullMixin:  # pyright: ignore[reportUnusedClass]
    """Mixin: pull sessions, projects, and todos from remote computers."""

    if TYPE_CHECKING:
        client: AdapterClient

        @property
        def cache(self) -> DaemonCache | None: ...

        async def send_request(
            self,
            computer_name: str,
            command: str,
            metadata: MessageMetadata,
            session_id: str | None = None,
            args: list[str] | None = None,
        ) -> str: ...

    async def _pull_initial_sessions(self) -> None:
        """Pull existing sessions from remote computers that have registered interest.

        This ensures remote sessions appear in TUI on startup, not just after new events.
        Only pulls from computers that the local client has explicitly subscribed to.
        """
        if not self.cache:
            logger.warning("Cache unavailable, skipping initial session pull")
            return

        logger.info("Performing initial session pull from interested computers")

        # Get computers that we have interest in for sessions
        interested_computers = self.cache.get_interested_computers("sessions")
        if not interested_computers:
            logger.debug("No interested computers for session pull")
            return

        # Get all known remote computers from cache
        all_computers = self.cache.get_computers()
        computer_map = {c.name: c for c in all_computers}

        # Pull sessions only from computers we're interested in
        for computer_name in interested_computers:
            if computer_name not in computer_map:
                logger.debug("Interested computer %s not found in heartbeats, skipping", computer_name)
                continue
            try:
                # Request sessions via Redis (calls list_sessions handler on remote)
                message_id = await self.send_request(computer_name, "list_sessions", MessageMetadata())

                # Wait for response with short timeout
                response_data = await self.client.read_response(message_id, timeout=3.0, target_computer=computer_name)
                envelope_obj: object = json.loads(response_data.strip())

                if not isinstance(envelope_obj, dict):
                    logger.warning("Invalid response from %s: not a dict", computer_name)
                    continue

                envelope: JsonDict = envelope_obj

                # Check response status
                status = envelope.get("status")
                if status == "error":
                    error_msg = envelope.get("error", "unknown error")
                    logger.warning("Error from %s: %s", computer_name, error_msg)
                    continue

                # Extract sessions data
                data = envelope.get("data")
                if not isinstance(data, list):
                    logger.warning("Invalid sessions data from %s: %s", computer_name, type(data))
                    continue

                # Populate cache with sessions
                for session_obj in data:
                    if isinstance(session_obj, dict):
                        snapshot = SessionSnapshot.from_dict(session_obj)
                        snapshot.computer = computer_name
                        self.cache.update_session(snapshot)

                logger.info("Pulled %d sessions from %s", len(data), computer_name)

            except Exception as e:
                logger.warning("Failed to pull sessions from %s: %s", computer_name, e)
                continue

    async def pull_interested_sessions(self) -> None:
        """Pull sessions for currently interested computers."""
        await self._pull_initial_sessions()

    async def pull_remote_projects(self, computer: str) -> None:
        """Pull projects from a remote computer via Redis.

        Args:
            computer: Name of the remote computer to pull projects from
        """
        if not self.cache:
            logger.warning("Cache unavailable, skipping projects pull from %s", computer)
            return

        logger.debug("Pulling projects from remote computer: %s", computer)

        try:
            # Request projects via Redis (calls list_projects handler on remote)
            message_id = await self.send_request(computer, "list_projects", MessageMetadata())

            # Wait for response with short timeout
            response_data = await self.client.read_response(message_id, timeout=3.0, target_computer=computer)
            envelope_obj: object = json.loads(response_data.strip())

            if not isinstance(envelope_obj, dict):
                logger.warning("Invalid response from %s: not a dict", computer)
                return

            envelope: JsonDict = envelope_obj

            # Check response status
            status = envelope.get("status")
            if status == "error":
                error_msg = envelope.get("error", "unknown error")
                logger.warning("Error from %s: %s", computer, error_msg)
                if isinstance(error_msg, str) and "list_projects_with_todos" in error_msg:
                    await self.pull_remote_projects(computer)
                return

            # Extract projects data
            data = envelope.get("data")
            if not isinstance(data, list):
                logger.warning("Invalid projects data from %s: %s", computer, type(data))
                return

            # Convert to ProjectInfo list
            projects: list[ProjectInfo] = []
            for project_obj in data:
                if isinstance(project_obj, dict):
                    # Ensure computer name is set from the pull source
                    info = ProjectInfo.from_dict(project_obj)
                    info.computer = computer
                    projects.append(info)

            # Store in cache
            self.cache.apply_projects_snapshot(computer, projects)
            logger.info("Pulled %d projects from %s", len(projects), computer)

        except Exception as e:
            logger.warning("Failed to pull projects from %s: %s", computer, e)

    async def pull_remote_projects_with_todos(self, computer: str) -> None:
        """Pull projects with embedded todos from a remote computer via Redis."""
        if not self.cache:
            logger.warning("Cache unavailable, skipping projects-with-todos pull from %s", computer)
            return

        logger.debug("Pulling projects-with-todos from %s", computer)

        try:
            message_id = await self.send_request(computer, "list_projects_with_todos", MessageMetadata())

            response_data = await self.client.read_response(message_id, timeout=5.0, target_computer=computer)
            envelope_obj: object = json.loads(response_data.strip())

            if not isinstance(envelope_obj, dict):
                logger.warning("Invalid response from %s: not a dict", computer)
                return

            envelope: JsonDict = envelope_obj

            status = envelope.get("status")
            if status == "error":
                error_msg = envelope.get("error", "unknown error")
                logger.warning("Error from %s: %s", computer, error_msg)
                if isinstance(error_msg, str) and "list_projects_with_todos" in error_msg:
                    await self.pull_remote_projects(computer)
                return

            data = envelope.get("data")
            if not isinstance(data, list):
                logger.warning("Invalid projects-with-todos data from %s: %s", computer, type(data))
                return

            projects: list[ProjectInfo] = []
            todos_by_project: dict[str, list[TodoInfo]] = {}
            for project_obj in data:
                if not isinstance(project_obj, dict):
                    continue
                project_path = str(project_obj.get("path", ""))
                if not project_path:
                    continue
                info = ProjectInfo.from_dict(project_obj)
                info.computer = computer
                projects.append(info)
                todos_by_project[project_path] = info.todos

            self.cache.apply_projects_snapshot(computer, projects)
            self.cache.apply_todos_snapshot(computer, todos_by_project)
            logger.info("Pulled %d projects-with-todos from %s", len(projects), computer)

        except Exception as e:
            logger.warning("Failed to pull projects-with-todos from %s: %s", computer, e)

    async def pull_remote_todos(self, computer: str, project_path: str) -> None:
        """Pull todos for a specific project from a remote computer via Redis.

        Args:
            computer: Name of the remote computer
            project_path: Path to the project on the remote computer
        """
        if not self.cache:
            logger.warning("Cache unavailable, skipping todos pull from %s:%s", computer, project_path)
            return

        logger.debug("Pulling todos from %s:%s", computer, project_path)

        try:
            # Request projects snapshot with embedded todos, then filter to the target project.
            message_id = await self.send_request(computer, "list_projects_with_todos", MessageMetadata())

            # Wait for response with short timeout
            response_data = await self.client.read_response(message_id, timeout=3.0, target_computer=computer)
            envelope_obj: object = json.loads(response_data.strip())

            if not isinstance(envelope_obj, dict):
                logger.warning("Invalid response from %s: not a dict", computer)
                return

            envelope: JsonDict = envelope_obj

            # Check response status
            status = envelope.get("status")
            if status == "error":
                error_msg = envelope.get("error", "unknown error")
                logger.warning("Error from %s: %s", computer, error_msg)
                if isinstance(error_msg, str) and "list_projects_with_todos" in error_msg:
                    await self.pull_remote_projects(computer)
                return

            # Extract projects-with-todos data
            data = envelope.get("data")
            if not isinstance(data, list):
                logger.warning("Invalid projects-with-todos data from %s: %s", computer, type(data))
                return

            todos: list[TodoInfo] = []
            for project_obj in data:
                if not isinstance(project_obj, dict):
                    continue
                path = str(project_obj.get("path", ""))
                if path != project_path:
                    continue
                todos_obj = project_obj.get("todos", [])
                if not isinstance(todos_obj, list):
                    logger.warning("Invalid todos payload for %s:%s", computer, project_path)
                    return
                for todo_obj in todos_obj:
                    if isinstance(todo_obj, dict):
                        todos.append(TodoInfo.from_dict(todo_obj))
                break

            self.cache.set_todos(computer, project_path, todos)
            logger.info("Pulled %d todos from %s:%s via projects-with-todos", len(todos), computer, project_path)

        except Exception as e:
            logger.warning("Failed to pull todos from %s:%s: %s", computer, project_path, e)
