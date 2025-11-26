"""Protocol definitions for adapter capabilities."""

from typing import AsyncIterator, Dict, Optional, Protocol, runtime_checkable


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
        request_id: str,
        command: str,
        metadata: Optional[Dict[str, object]] = None,
    ) -> str:
        """Send request to remote computer via transport layer.

        Args:
            computer_name: Target computer identifier
            request_id: Correlation ID for request/response matching
            command: Command to send to remote computer
            metadata: Optional metadata (title, project_dir for session creation)

        Returns:
            Redis stream entry ID

        Raises:
            RuntimeError: If transport layer fails
        """
        ...

    async def send_response(self, request_id: str, data: str) -> str:
        """Send response for an ephemeral request.

        Args:
            request_id: Correlation ID from the request
            data: Response data (typically JSON)

        Returns:
            Stream entry ID

        Raises:
            RuntimeError: If transport layer fails
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

        Raises:
            TimeoutError: If no response received within timeout
        """
        ...
