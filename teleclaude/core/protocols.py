"""Protocol definitions for adapter capabilities."""

from typing import AsyncIterator, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class RemoteExecutionProtocol(Protocol):
    """Protocol for adapters that can send messages to remote computers.

    This protocol defines the interface for cross-computer communication,
    enabling AI-to-AI orchestration via transport adapters (Redis, Postgres, etc.).

    UI-only adapters (Telegram, Slack) do NOT implement this protocol.
    """

    async def send_message_to_computer(
        self,
        computer_name: str,
        session_id: str,
        message: str,
        metadata: Optional[Dict[str, object]] = None,
    ) -> str:
        """Send message to remote computer via transport layer.

        Args:
            computer_name: Target computer identifier
            session_id: Session ID for the message
            message: Message to send to remote computer
            metadata: Optional metadata for the message

        Returns:
            Request ID for tracking the message

        Raises:
            RuntimeError: If transport layer fails
        """
        ...

    def poll_output_stream(
        self,
        session_id: str,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Stream output from remote session.

        Args:
            session_id: Session ID to poll output from
            timeout: Maximum time to wait for output (seconds)

        Yields:
            Output chunks from the remote session

        Raises:
            TimeoutError: If no output received within timeout
        """
        ...
