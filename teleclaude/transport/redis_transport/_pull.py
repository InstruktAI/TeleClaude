"""Remote data pull operations for RedisTransport (sessions, projects, todos)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.core.models import JsonDict, MessageMetadata, ProjectInfo, SessionSnapshot, TodoInfo

logger = get_logger(__name__)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache


_PULL_EXCEPTIONS = (RedisError, TimeoutError, OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError)


class _PullMixin:  # pyright: ignore[reportUnusedClass]
    """Mixin: pull sessions, projects, and todos from remote computers."""

    if TYPE_CHECKING:
        client: AdapterClient

        @property
        def cache(self) -> DaemonCache | None:
            """Return the shared daemon cache."""
            raise NotImplementedError

        async def send_request(
            self,
            computer_name: str,
            command: str,
            metadata: MessageMetadata,
            session_id: str | None = None,
        ) -> str:
            """Send a request to a remote computer."""
            _ = (computer_name, command, metadata, session_id)
            raise NotImplementedError

    def _parse_envelope(self, computer: str, response_data: str, label: str) -> JsonDict | None:
        """Parse a JSON envelope response, logging and returning `None` on invalid data."""
        envelope_obj: object = json.loads(response_data.strip())
        if not isinstance(envelope_obj, dict):
            logger.warning("Invalid %s response from %s: not a dict", label, computer)
            return None
        return envelope_obj

    def _extract_response_data(self, envelope: JsonDict, computer: str, label: str) -> list[JsonDict] | None:
        """Return the `data` list from a response envelope when successful."""
        data = envelope.get("data")
        if not isinstance(data, list):
            logger.warning("Invalid %s data from %s: %s", label, computer, type(data))
            return None
        return [item for item in data if isinstance(item, dict)]

    async def _handle_error_status(
        self,
        computer: str,
        error_msg: object,
        *,
        fallback_to_projects: bool = False,
    ) -> None:
        """Mirror the existing fallback behavior for remote error envelopes."""
        logger.warning("Error from %s: %s", computer, error_msg)
        if fallback_to_projects and isinstance(error_msg, str) and "list_projects_with_todos" in error_msg:
            await self.pull_remote_projects(computer)

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

            except _PULL_EXCEPTIONS as e:
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
            message_id = await self.send_request(computer, "list_projects", MessageMetadata())
            response_data = await self.client.read_response(message_id, timeout=3.0, target_computer=computer)
            envelope = self._parse_envelope(computer, response_data, "projects")
            if envelope is None:
                return

            if envelope.get("status") == "error":
                await self._handle_error_status(computer, envelope.get("error", "unknown error"))
                return

            data = self._extract_response_data(envelope, computer, "projects")
            if data is None:
                return

            projects: list[ProjectInfo] = []
            for project_obj in data:
                info = ProjectInfo.from_dict(project_obj)
                info.computer = computer
                projects.append(info)
            self.cache.apply_projects_snapshot(computer, projects)
            logger.info("Pulled %d projects from %s", len(projects), computer)

        except _PULL_EXCEPTIONS as e:
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
            envelope = self._parse_envelope(computer, response_data, "projects-with-todos")
            if envelope is None:
                return

            if envelope.get("status") == "error":
                await self._handle_error_status(
                    computer,
                    envelope.get("error", "unknown error"),
                    fallback_to_projects=True,
                )
                return

            data = self._extract_response_data(envelope, computer, "projects-with-todos")
            if data is None:
                return

            projects: list[ProjectInfo] = []
            todos_by_project: dict[str, list[TodoInfo]] = {}
            for project_obj in data:
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

        except _PULL_EXCEPTIONS as e:
            logger.warning("Failed to pull projects-with-todos from %s: %s", computer, e)

    def _extract_todos_for_project(self, data: list[object], computer: str, project_path: str) -> list[TodoInfo] | None:
        """Extract todos for one project from a projects-with-todos payload."""
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
                return None
            for todo_obj in todos_obj:
                if isinstance(todo_obj, dict):
                    todos.append(TodoInfo.from_dict(todo_obj))
            break
        return todos

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
            message_id = await self.send_request(computer, "list_projects_with_todos", MessageMetadata())
            response_data = await self.client.read_response(message_id, timeout=3.0, target_computer=computer)
            envelope = self._parse_envelope(computer, response_data, "projects-with-todos")
            if envelope is None:
                return

            if envelope.get("status") == "error":
                await self._handle_error_status(
                    computer,
                    envelope.get("error", "unknown error"),
                    fallback_to_projects=True,
                )
                return

            data = self._extract_response_data(envelope, computer, "projects-with-todos")
            if data is None:
                return

            todos = self._extract_todos_for_project(data, computer, project_path)
            if todos is None:
                return
            self.cache.set_todos(computer, project_path, todos)
            logger.info("Pulled %d todos from %s:%s via projects-with-todos", len(todos), computer, project_path)

        except _PULL_EXCEPTIONS as e:
            logger.warning("Failed to pull todos from %s:%s: %s", computer, project_path, e)
