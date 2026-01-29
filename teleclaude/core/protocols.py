"""Protocol definitions for adapter capabilities."""

from typing import AsyncIterator, Optional, Protocol, runtime_checkable

from teleclaude.core.models import MessageMetadata


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
        session_id: Optional[str] = None,
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
            Current MCP usage polls session output via get_session_data; Redis output streaming is disabled.

        Raises:
            TimeoutError: If no response received within timeout
        """
        ...
