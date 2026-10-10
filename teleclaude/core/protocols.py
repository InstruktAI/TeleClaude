"""Protocol definitions for adapter capabilities."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from teleclaude.core.endpoints import DeskIdentifier
from teleclaude.core.models import (
    JsonDict,
    MessageMetadata,
    ObservedStopPublication,
    PeerCapabilityMissing,
    Session,
    SessionFinalOutput,
)


@dataclass(frozen=True)
class EscalationThread:
    """Discord thread opened for a help-desk escalation."""

    thread_id: str
    link: str


@runtime_checkable
class EscalationThreadAdapter(Protocol):
    """Thread transport capability used by the core-owned escalation relay."""

    async def open_escalation_thread(
        self,
        desk: DeskIdentifier,
        *,
        title: str,
        brief: str,
    ) -> EscalationThread:
        """Open the escalation thread in the desk's forum.

        Raises:
            AdapterError: If the forum is unavailable or the thread cannot be opened.
        """
        ...

    async def post_to_escalation_thread(self, thread_id: str, *, sender: str, text: str) -> None:
        """Post a message into an escalation thread.

        Raises:
            AdapterError: If the thread is unavailable or the message cannot be posted.
        """
        ...

    async def session_thread_link(self, session: Session) -> str:
        """Ensure the session mirror exists and return its Discord thread link.

        Raises:
            AdapterError: If the session thread cannot be created or linked.
        """
        ...


@runtime_checkable
class RemoteExecutionProtocol(Protocol):
    """Protocol for adapters supporting request/response pattern.

    This protocol defines the interface for cross-computer communication,
    enabling AI-to-AI orchestration via transport adapters (Redis, Postgres, etc.).

    Two communication patterns:
    - Request/Response: For ephemeral queries (list_projects, etc.)
    - Message: For real session communication (requires DB session)

    UI-only adapters (Telegram, Slack) do NOT implement this protocol.
    """

    async def send_request(
        self,
        computer_name: str,
        command: str,
        metadata: MessageMetadata,
        *,
        principal: str,
        session_id: str | None = None,
        command_payload: JsonDict | None = None,
    ) -> str:
        """Send request to remote computer via transport layer.

        Transport layer generates request_id from Redis for correlation.

        Args:
            computer_name: Target computer identifier
            command: Command to send to remote computer
            session_id: Optional TeleClaude session ID (for session commands)
            metadata: Metadata (title, project_path for session creation)

        Returns:
            Redis message ID (for response correlation via read_response)

        Raises:
            RuntimeError: If transport layer fails
        """
        ...

    async def send_response(self, message_id: str, data: str) -> str:
        """Send response for an ephemeral request.

        Args:
            message_id: Stream entry ID from the original request
            data: Response data (typically JSON)

        Returns:
            Stream entry ID of the response

        Raises:
            RuntimeError: If transport layer fails
        """
        ...

    async def read_response(self, message_id: str, timeout: float = 3.0, target_computer: str | None = None) -> str:
        """Read response from ephemeral request (non-streaming).

        Used for one-shot queries like list_projects, get_computer_info.
        Reads the response in one go instead of streaming.

        Args:
            message_id: Stream entry ID from the original request
            timeout: Maximum time to wait for response (seconds, default 3.0)

        Returns:
            Response data as string

        Raises:
            TimeoutError: If no response received within timeout
        """
        ...

    def poll_output_stream(
        self,
        request_id: str,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Stream response for a request.

        Args:
            request_id: Request ID to poll response from
            timeout: Maximum time to wait for response (seconds)

        Yields:
            Response chunks

        Note:
            Current tool usage polls session output via get_session_data; Redis output streaming is disabled.

        Raises:
            TimeoutError: If no response received within timeout
        """
        ...

    async def notify_session_observed_stop(self, session_id: str, output_version: str) -> ObservedStopPublication:
        """Notify this session's observer, if any, that its agent stopped.

        Every transport error is caught inside the implementation and
        reported as `published=False` — this never raises.

        Args:
            session_id: The session whose agent just stopped.
            output_version: The stop marker (`last_output_stop_at`) this notification carries.

        Returns:
            Whether a notification was published, and to which observer.
        """
        ...

    async def observe_session(self, computer: str, session_id: str, ttl_s: int) -> bool:
        """Signal interest in a remote session for `ttl_s` seconds.

        Args:
            computer: The computer hosting the session.
            session_id: The session to observe.
            ttl_s: How long the observation window lasts before it must be renewed.

        Returns:
            Whether the signal was sent successfully.
        """
        ...

    def request_sessions_refresh(self, computer: str, reason: str) -> None:
        """Ask this computer's session cache to refresh from `computer`.

        Args:
            computer: The peer whose sessions should be refreshed.
            reason: One of the transport's allowed refresh reasons.
        """
        ...

    async def fetch_session_final_output(
        self, computer: str, session_id: str
    ) -> SessionFinalOutput | PeerCapabilityMissing:
        """Pull a remote session's current final output.

        Args:
            computer: The computer hosting the session.
            session_id: The session to query.

        Returns:
            The session's current output, or `PeerCapabilityMissing` when the
            peer does not answer this request.
        """
        ...
